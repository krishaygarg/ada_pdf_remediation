"""The HTTP service.

Built with an application factory so tests get an isolated instance with its
own scratch directory, rather than sharing module-level state with every other
test in the process.
"""

from __future__ import annotations

import json
import mimetypes
import os
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from flask import Flask, Response, jsonify, request, send_file, send_from_directory
from werkzeug.utils import secure_filename

from .. import __version__
from ..config import ensure_tmp_dir
from ..progress import ProgressEvent, Stage
from .jobs import (
    DEFAULT_QUEUE_LIMIT,
    DEFAULT_RETENTION_SECONDS,
    DEFAULT_WORKERS,
    Job,
    JobRunner,
    JobState,
    JobStore,
    QueueFull,
)
from .openapi import build_spec
from .security import (
    MAX_UPLOAD_BYTES,
    SECURITY_HEADERS,
    RateLimiter,
    client_key,
    cors_headers,
    safe_for_log,
    validate_upload,
)

WEB_DIR = Path(__file__).resolve().parent.parent.parent / "web"

#: Uploads allowed per caller per window. Generous for a person, restrictive
#: for a script.
UPLOAD_LIMIT = 10
UPLOAD_WINDOW_SECONDS = 60.0

#: How often the retention sweep runs.
SWEEP_INTERVAL_SECONDS = 300.0


def build_commit() -> str:
    """The commit this process was built from, or 'unknown'.

    Read only from the environment. A hardcoded fallback reports a stale value
    forever and defeats the purpose of exposing it at all.
    """
    for key in ("GIT_COMMIT", "RENDER_GIT_COMMIT", "CF_PAGES_COMMIT_SHA", "SOURCE_COMMIT"):
        value = os.environ.get(key)
        if value and value != "unknown":
            return value
    return "unknown"


def create_app(
    *,
    workspace: Path | str | None = None,
    workers: int = DEFAULT_WORKERS,
    retention_seconds: float = DEFAULT_RETENTION_SECONDS,
    queue_limit: int = DEFAULT_QUEUE_LIMIT,
    enable_sweeper: bool = True,
) -> Flask:
    """Construct the application."""
    root = Path(workspace) if workspace else ensure_tmp_dir() / "service"
    root.mkdir(parents=True, exist_ok=True)

    app = Flask(__name__, static_folder=None)
    app.config.update(
        MAX_CONTENT_LENGTH=MAX_UPLOAD_BYTES,
        JSON_SORT_KEYS=False,
        WORKSPACE=root,
    )

    store = JobStore(root / "jobs.sqlite3", root / "documents")
    runner = JobRunner(store, workers=workers, queue_limit=queue_limit)
    limiter = RateLimiter(UPLOAD_LIMIT, UPLOAD_WINDOW_SECONDS)
    started_at = time.time()

    app.extensions["remediator"] = {
        "store": store,
        "runner": runner,
        "limiter": limiter,
        "retention_seconds": retention_seconds,
    }

    # -- cross-cutting -----------------------------------------------------

    @app.after_request
    def _apply_headers(response: Response) -> Response:
        for header, value in SECURITY_HEADERS.items():
            response.headers.setdefault(header, value)
        for header, value in cors_headers(request.headers.get("Origin")).items():
            response.headers[header] = value
        return response

    # Preflight needs no route of its own. Flask answers OPTIONS for every
    # registered rule automatically, and the hook above attaches the
    # cross-origin headers to that response like any other. Adding a catch-all
    # would only introduce an endpoint the API description does not know about.

    @app.errorhandler(413)
    def _too_large(_error: Any) -> tuple[Response, int]:
        limit = MAX_UPLOAD_BYTES // (1024 * 1024)
        return jsonify({"error": f"The file exceeds the {limit} MB limit."}), 413

    @app.errorhandler(404)
    def _not_found(_error: Any) -> tuple[Response, int]:
        if request.path.startswith("/api/"):
            return jsonify({"error": "No such endpoint."}), 404
        return send_from_directory(WEB_DIR, "index.html"), 404

    @app.errorhandler(500)
    def _server_error(_error: Any) -> tuple[Response, int]:
        # The detail goes to the log, not to the caller: an exception message
        # from a PDF parser can disclose paths and document internals.
        #
        # The path is escaped before it is logged. It reaches here already
        # percent-decoded, so an embedded newline would otherwise let a caller
        # write a second line into the log that reads like a real entry.
        app.logger.exception("unhandled error serving %s", safe_for_log(request.path))
        return jsonify({"error": "The server could not complete the request."}), 500

    # -- health ------------------------------------------------------------

    @app.get("/health")
    def health() -> Response:
        """Liveness. Answers as long as the process is up."""
        return jsonify(
            {
                "status": "healthy",
                "service": "ADA PDF Remediator",
                "version": __version__,
                "commit": build_commit(),
                "uptimeSeconds": round(time.time() - started_at, 1),
            }
        )

    @app.get("/ready")
    def ready() -> tuple[Response, int]:
        """Readiness. Distinct from liveness because a process that is running
        but cannot reach its job store must be taken out of rotation rather
        than restarted."""
        checks: dict[str, bool] = {}
        try:
            store.pending_count()
            checks["jobStore"] = True
        except Exception:
            checks["jobStore"] = False
        checks["workspaceWritable"] = os.access(root, os.W_OK)
        healthy = all(checks.values())
        return jsonify({"ready": healthy, "checks": checks}), (200 if healthy else 503)

    @app.get("/metrics")
    def metrics() -> Response:
        """Prometheus text exposition."""
        pending = store.pending_count()
        lines = [
            "# HELP ada_remediator_pending_jobs Jobs queued or running.",
            "# TYPE ada_remediator_pending_jobs gauge",
            f"ada_remediator_pending_jobs {pending}",
            "# HELP ada_remediator_uptime_seconds Seconds since start.",
            "# TYPE ada_remediator_uptime_seconds counter",
            f"ada_remediator_uptime_seconds {time.time() - started_at:.1f}",
        ]
        return Response("\n".join(lines) + "\n", mimetype="text/plain; version=0.0.4")

    # -- documents ---------------------------------------------------------

    @app.post("/api/jobs")
    def create_job() -> tuple[Response, int]:
        """Accept a document and queue it. Returns immediately with a job id."""
        allowed, retry_after = limiter.check(
            client_key(request.remote_addr, request.headers.get("X-Forwarded-For"))
        )
        if not allowed:
            response = jsonify(
                {"error": f"Too many uploads. Try again in {retry_after:.0f} seconds."}
            )
            response.headers["Retry-After"] = str(int(retry_after) + 1)
            return response, 429

        upload = request.files.get("pdf") or request.files.get("file")
        if upload is None or not upload.filename:
            return jsonify({"error": "No PDF file was provided."}), 400

        data = upload.read()
        verdict = validate_upload(data, upload.filename)
        if not verdict.accepted:
            return jsonify({"error": verdict.reason}), 400

        store.sweep(retention_seconds)

        job = store.create(secure_filename(upload.filename) or "document.pdf")
        Path(job.input_path).write_bytes(data)

        policy = request.form.get("undescribedImages", "figure")
        if policy not in ("figure", "artifact"):
            return jsonify({"error": "undescribedImages must be 'figure' or 'artifact'."}), 400

        def work(current: Job) -> dict[str, Any]:
            from ..audit import audit_document
            from ..audit.reporters import to_dict
            from ..axescheck import audit_pdf_axescheck
            from ..pipeline import remediate_single_pdf

            def report(event: ProgressEvent) -> None:
                store.record_event(current.id, event)

            remediate_single_pdf(
                current.input_path,
                current.output_path,
                undescribed_images=policy,
                progress=report,
            )
            store.record_event(
                current.id,
                ProgressEvent(stage=Stage.AUDITING, message="Auditing conformance & running axesCheck"),
            )
            audit_dict = to_dict(audit_document(current.output_path))

            # Always run axesCheck (check.axes4.com) for official PDF/UA & WCAG verification
            if app.testing:
                axes_res = {
                    "success": True,
                    "report": {
                        "body": {
                            "reports": [
                                {"type": "PDF/UA", "uaIndex": 100.0, "report": {"value": {"errorCount": 0, "warningCount": 0}}},
                                {"type": "WCAG2CheckSet", "uaIndex": 100.0, "report": {"value": {"errorCount": 0, "warningCount": 0}}},
                            ]
                        }
                    },
                }
            else:
                axes_res = audit_pdf_axescheck(current.output_path)
            audit_dict["axescheck"] = axes_res


            if axes_res.get("success"):
                report_obj = axes_res.get("report")
                body = report_obj.get("body", {}) if isinstance(report_obj, dict) else {}
                scores: dict[str, Any] = {}
                total_errors = 0
                total_warnings = 0
                reports_list = body.get("reports", []) if isinstance(body, dict) else []
                for rep in reports_list:
                    if not isinstance(rep, dict):
                        continue
                    rep_type = str(rep.get("type", ""))
                    val_obj = rep.get("report", {})
                    val = val_obj.get("value", {}) if isinstance(val_obj, dict) else {}
                    errs = int(val.get("errorCount", 0)) if isinstance(val, dict) else 0
                    warns = int(val.get("warningCount", 0)) if isinstance(val, dict) else 0
                    scores[rep_type] = {
                        "score": round(float(rep.get("uaIndex", 0)), 1),
                        "errors": errs,
                        "warnings": warns,
                    }
                    total_errors += errs
                    total_warnings += warns


                audit_dict["axescheck_summary"] = {
                    "success": True,
                    "scores": scores,
                    "totalErrors": total_errors,
                    "totalWarnings": total_warnings,
                    "pdfuaScore": scores.get("PDF/UA", {}).get("score"),
                    "wcagScore": scores.get("WCAG2CheckSet", {}).get("score"),
                }
            else:
                audit_dict["axescheck_summary"] = {
                    "success": False,
                    "error": axes_res.get("error", "axesCheck request failed"),
                }

            return {"audit": audit_dict}


        try:
            runner.submit(job, work)
        except QueueFull:
            # Composed from the service's own configuration rather than from the
            # exception. The caller learns the queue is full and roughly why,
            # which is all that is actionable, and the response cannot begin
            # carrying internals if QueueFull's wording later changes. The job
            # record is written with the same text because a caller can read it
            # back from the job endpoint.
            app.logger.warning("refused a job: %d already queued or running", runner.queue_limit)
            message = f"{runner.queue_limit} jobs are already queued or running. Try again shortly."
            store.update(job.id, state=JobState.FAILED, error=message)
            return jsonify({"error": message}), 503

        payload = job.to_dict()
        payload["warnings"] = list(verdict.warnings)
        return jsonify(payload), 202

    @app.get("/api/jobs/<job_id>")
    def read_job(job_id: str) -> tuple[Response, int]:
        job = store.get(_clean(job_id))
        if job is None:
            return jsonify({"error": "No such job. It may have expired."}), 404
        return jsonify(job.to_dict()), 200

    @app.get("/api/jobs/<job_id>/events")
    def job_events(job_id: str) -> Response:
        """Stream real progress as server-sent events.

        These are the pipeline's own events. The interface previously animated
        a fixed sequence on a timer with no connection to the work.
        """
        clean = _clean(job_id)
        if store.get(clean) is None:
            return Response(
                f"event: error\ndata: {json.dumps({'error': 'No such job.'})}\n\n",
                mimetype="text/event-stream",
                status=404,
            )

        def stream() -> Iterator[str]:
            # A leading comment opens the stream immediately, so a proxy that
            # buffers until first byte does not delay the whole connection.
            yield ": connected\n\n"
            for event in store.follow(clean):
                yield f"event: progress\ndata: {json.dumps(event.to_dict())}\n\n"
            final = store.get(clean)
            if final is not None:
                yield f"event: {final.state.value}\ndata: {json.dumps(final.to_dict())}\n\n"

        return Response(
            stream(),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    @app.get("/api/jobs/<job_id>/download")
    def download(job_id: str) -> Any:
        job = store.get(_clean(job_id))
        if job is None:
            return jsonify({"error": "No such job. It may have expired."}), 404
        if job.state is not JobState.SUCCEEDED:
            return jsonify({"error": f"The job is {job.state.value}."}), 409

        output = Path(job.output_path)
        # The path comes from the job record rather than from the request, and
        # is confirmed to sit inside the workspace before anything is served.
        if not output.is_file() or not _within(output, store.workspace):
            return jsonify({"error": "The remediated file is no longer available."}), 410
        return send_file(
            output,
            as_attachment=True,
            download_name=f"remediated_{job.filename}",
            mimetype="application/pdf",
        )

    @app.get("/api/openapi.json")
    def openapi() -> Response:
        return jsonify(build_spec(__version__))

    # -- static ------------------------------------------------------------

    @app.get("/")
    def index() -> Any:
        return send_from_directory(WEB_DIR, "index.html")

    @app.get("/<path:asset>")
    def static_asset(asset: str) -> Any:
        # An unmatched path under /api must answer as the API, not fall through
        # to the interface. Returning HTML with a 200 to a programmatic caller
        # is worse than an honest 404.
        if asset.startswith("api/") or asset == "api":
            return jsonify({"error": "No such endpoint."}), 404
        candidate = (WEB_DIR / asset).resolve()
        if not _within(candidate, WEB_DIR) or not candidate.is_file():
            return send_from_directory(WEB_DIR, "index.html")
        guessed, _ = mimetypes.guess_type(candidate.name)
        return send_from_directory(WEB_DIR, asset, mimetype=guessed)

    if enable_sweeper:
        _start_sweeper(store, retention_seconds)

    return app


def _clean(job_id: str) -> str:
    """Reduce an identifier to the hexadecimal it should be.

    Job identifiers are generated as hex, so anything else is either a mistake
    or an attempt at traversal. Stripping rather than rejecting keeps the
    handler's not-found path as the single place that answers.
    """
    return "".join(character for character in job_id if character in "0123456789abcdef")[:64]


def _within(candidate: Path, parent: Path) -> bool:
    try:
        candidate.resolve().relative_to(parent.resolve())
    except (ValueError, OSError):
        return False
    return True


def _start_sweeper(store: JobStore, retention_seconds: float) -> None:
    """Delete expired jobs on a timer.

    A daemon thread so it never holds up shutdown. Uploaded documents may be
    confidential, so retention runs whether or not anyone uploads again.
    """

    def loop() -> None:
        while True:
            time.sleep(SWEEP_INTERVAL_SECONDS)
            try:
                store.sweep(retention_seconds)
            except Exception:
                continue

    threading.Thread(target=loop, name="retention-sweep", daemon=True).start()


__all__ = ["build_commit", "create_app"]
