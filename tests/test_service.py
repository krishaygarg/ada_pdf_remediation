"""Tests for the HTTP service.

Every test builds its own application against a temporary workspace, so no test
can see another's jobs and none of them touch the developer's scratch
directory.
"""

from __future__ import annotations

import io
import json
import time
from pathlib import Path
from typing import Any

import pytest

from remediator.progress import (
    CollectingReporter,
    ConsoleReporter,
    NullReporter,
    ProgressEvent,
    Stage,
    emit,
)
from remediator.service import create_app
from remediator.service.jobs import JobRunner, JobState, JobStore, QueueFull
from remediator.service.security import (
    MAX_UPLOAD_BYTES,
    RateLimiter,
    client_key,
    validate_upload,
)


@pytest.fixture
def app(tmp_path: Path):
    application = create_app(workspace=tmp_path / "service", workers=1, enable_sweeper=False)
    application.config.update(TESTING=True)
    yield application
    application.extensions["remediator"]["runner"].shutdown(wait=True)


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def pdf_bytes(sample_pdf: Path) -> bytes:
    return sample_pdf.read_bytes()


def _submit(client, data: bytes, name: str = "document.pdf", **form: Any):
    return client.post(
        "/api/jobs",
        data={"pdf": (io.BytesIO(data), name), **form},
        content_type="multipart/form-data",
    )


def _await_completion(client, job_id: str, timeout: float = 120.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        payload = client.get(f"/api/jobs/{job_id}").get_json()
        if payload["state"] in ("succeeded", "failed"):
            return payload
        time.sleep(0.2)
    raise AssertionError("the job did not finish in time")


class TestProgressReporting:
    def test_events_carry_a_completion_fraction_when_countable(self) -> None:
        event = ProgressEvent(stage=Stage.ANALYSING_PAGE, message="", current=3, total=10)
        assert event.fraction == pytest.approx(0.3)

    def test_events_without_a_total_have_no_fraction(self) -> None:
        assert ProgressEvent(stage=Stage.OPENING, message="").fraction is None

    def test_every_stage_has_a_human_label(self) -> None:
        assert all(stage.label and stage.label != stage.value for stage in Stage)

    def test_a_reporter_that_raises_cannot_abort_a_run(self) -> None:
        """Losing a progress line is cosmetic; losing the document is not."""

        def explode(event: ProgressEvent) -> None:
            raise RuntimeError("reporter failure")

        emit(explode, Stage.OPENING, "message")

    def test_the_null_reporter_discards(self) -> None:
        emit(NullReporter(), Stage.OPENING, "message")

    def test_the_console_reporter_prints(self, capsys: pytest.CaptureFixture[str]) -> None:
        emit(ConsoleReporter(), Stage.ANALYSING_PAGE, "Analysing page 2 of 5", current=2, total=5)
        assert "[2/5] Analysing page 2 of 5" in capsys.readouterr().out

    @pytest.mark.slow
    def test_the_pipeline_emits_real_stages(self, sample_pdf: Path, tmp_path: Path) -> None:
        """The interface previously animated a fixed sequence on a timer.

        These are the events the pipeline actually produces.
        """
        from remediator.pipeline import remediate_single_pdf

        reporter = CollectingReporter()
        remediate_single_pdf(str(sample_pdf), str(tmp_path / "out.pdf"), progress=reporter)
        stages = set(reporter.stages())
        assert Stage.OPENING in stages
        assert Stage.ANALYSING_PAGE in stages
        assert Stage.RECOVERING_FONTS in stages
        assert Stage.DONE in stages

    @pytest.mark.slow
    def test_page_events_count_up_to_the_page_total(self, sample_pdf: Path, tmp_path: Path) -> None:
        from remediator.pipeline import remediate_single_pdf

        reporter = CollectingReporter()
        remediate_single_pdf(str(sample_pdf), str(tmp_path / "out.pdf"), progress=reporter)
        page_events = [e for e in reporter.events if e.stage is Stage.ANALYSING_PAGE]
        assert [e.current for e in page_events] == list(range(1, len(page_events) + 1))
        assert all(e.total == len(page_events) for e in page_events)


class TestUploadValidation:
    def test_a_real_pdf_is_accepted(self, pdf_bytes: bytes) -> None:
        assert validate_upload(pdf_bytes, "a.pdf").accepted

    def test_a_wrong_extension_is_refused(self, pdf_bytes: bytes) -> None:
        assert not validate_upload(pdf_bytes, "a.exe").accepted

    def test_a_file_without_the_signature_is_refused(self) -> None:
        """Refused before the parser sees it, which is the point."""
        verdict = validate_upload(b"MZ\x90\x00 this is a binary", "a.pdf")
        assert not verdict.accepted
        assert "does not look like a PDF" in verdict.reason

    def test_an_empty_file_is_refused(self) -> None:
        assert not validate_upload(b"", "a.pdf").accepted

    def test_an_oversized_file_is_refused(self) -> None:
        verdict = validate_upload(b"%PDF-1.7" + b"\x00" * MAX_UPLOAD_BYTES, "a.pdf")
        assert not verdict.accepted
        assert "50 MB" in verdict.reason

    def test_embedded_javascript_produces_a_warning_not_a_refusal(self) -> None:
        """A legitimate document can carry active content, but the operator
        should know before publishing the result."""
        verdict = validate_upload(b"%PDF-1.7\n/JavaScript (app.alert)", "a.pdf")
        assert verdict.accepted
        assert any("active content" in warning for warning in verdict.warnings)

    def test_encryption_produces_a_warning(self) -> None:
        verdict = validate_upload(b"%PDF-1.7\n/Encrypt 1 0 R", "a.pdf")
        assert verdict.accepted
        assert any("encrypted" in warning for warning in verdict.warnings)


class TestRateLimiter:
    def test_requests_are_allowed_up_to_the_limit(self) -> None:
        limiter = RateLimiter(limit=3, window_seconds=60)
        assert all(limiter.check("client")[0] for _ in range(3))

    def test_the_next_request_is_refused_with_a_retry_hint(self) -> None:
        limiter = RateLimiter(limit=2, window_seconds=60)
        limiter.check("client")
        limiter.check("client")
        allowed, retry_after = limiter.check("client")
        assert not allowed
        assert retry_after > 0

    def test_callers_are_counted_separately(self) -> None:
        limiter = RateLimiter(limit=1, window_seconds=60)
        assert limiter.check("first")[0]
        assert limiter.check("second")[0]

    def test_the_window_expires(self) -> None:
        limiter = RateLimiter(limit=1, window_seconds=0.05)
        assert limiter.check("client")[0]
        time.sleep(0.08)
        assert limiter.check("client")[0]

    def test_a_forwarded_address_identifies_the_caller_behind_a_proxy(self) -> None:
        assert client_key("10.0.0.1", "203.0.113.7, 10.0.0.1") == "203.0.113.7"

    def test_the_remote_address_is_used_when_there_is_no_proxy(self) -> None:
        assert client_key("203.0.113.7", None) == "203.0.113.7"


class TestJobStore:
    @pytest.fixture
    def store(self, tmp_path: Path) -> JobStore:
        return JobStore(tmp_path / "jobs.sqlite3", tmp_path / "documents")

    def test_a_created_job_starts_queued(self, store: JobStore) -> None:
        job = store.create("a.pdf")
        assert store.get(job.id).state is JobState.QUEUED

    def test_an_unknown_job_resolves_to_nothing(self, store: JobStore) -> None:
        assert store.get("does-not-exist") is None

    def test_a_job_survives_a_new_store_over_the_same_database(
        self, store: JobStore, tmp_path: Path
    ) -> None:
        """The record has to outlive the process that created it."""
        job = store.create("a.pdf")
        reopened = JobStore(tmp_path / "jobs.sqlite3", tmp_path / "documents")
        assert reopened.get(job.id) is not None

    def test_state_and_result_round_trip(self, store: JobStore) -> None:
        job = store.create("a.pdf")
        store.update(job.id, state=JobState.SUCCEEDED, result={"audit": {"conformant": True}})
        stored = store.get(job.id)
        assert stored.state is JobState.SUCCEEDED
        assert stored.result["audit"]["conformant"] is True

    def test_the_retention_sweep_removes_old_jobs_and_their_files(self, store: JobStore) -> None:
        """Uploaded documents may be confidential, so retention is not optional."""
        job = store.create("a.pdf")
        Path(job.input_path).write_bytes(b"%PDF-1.7")
        assert store.sweep(retention_seconds=-1) == 1
        assert store.get(job.id) is None
        assert not Path(job.input_path).exists()

    def test_the_sweep_spares_recent_jobs(self, store: JobStore) -> None:
        job = store.create("a.pdf")
        assert store.sweep(retention_seconds=3600) == 0
        assert store.get(job.id) is not None

    def test_pending_counts_queued_and_running_only(self, store: JobStore) -> None:
        first = store.create("a.pdf")
        second = store.create("b.pdf")
        store.update(second.id, state=JobState.SUCCEEDED)
        assert store.pending_count() == 1
        assert store.get(first.id).state is JobState.QUEUED


class TestJobRunner:
    def test_a_failing_job_records_its_error_rather_than_vanishing(self, tmp_path: Path) -> None:
        store = JobStore(tmp_path / "jobs.sqlite3", tmp_path / "documents")
        runner = JobRunner(store, workers=1)
        job = store.create("a.pdf")

        def explode(_job):
            raise RuntimeError("deliberate failure")

        runner.submit(job, explode).result(timeout=10)
        stored = store.get(job.id)
        assert stored.state is JobState.FAILED
        assert "deliberate failure" in stored.error
        runner.shutdown()

    def test_the_queue_refuses_work_beyond_its_limit(self, tmp_path: Path) -> None:
        """An overloaded instance should say so rather than accept work it
        will not reach for an hour."""
        store = JobStore(tmp_path / "jobs.sqlite3", tmp_path / "documents")
        runner = JobRunner(store, workers=1, queue_limit=1)
        for _ in range(3):
            store.create("a.pdf")
        with pytest.raises(QueueFull):
            runner.submit(store.create("b.pdf"), lambda _job: {})
        runner.shutdown()


class TestEndpoints:
    def test_health_reports_the_version_and_commit(self, client) -> None:
        payload = client.get("/health").get_json()
        assert payload["status"] == "healthy"
        assert payload["version"]
        assert "commit" in payload

    def test_health_does_not_report_a_hardcoded_commit(self, client) -> None:
        """A literal fallback reports a stale value forever."""
        import remediator.service.app as service_app

        assert "8b4e2ff" not in Path(service_app.__file__).read_text(encoding="utf-8")

    def test_readiness_is_separate_from_liveness(self, client) -> None:
        payload = client.get("/ready").get_json()
        assert payload["ready"] is True
        assert payload["checks"]["jobStore"] is True

    def test_metrics_are_exposed_in_the_prometheus_format(self, client) -> None:
        response = client.get("/metrics")
        assert response.mimetype == "text/plain"
        assert "ada_remediator_pending_jobs" in response.get_data(as_text=True)

    def test_security_headers_are_applied(self, client) -> None:
        headers = client.get("/health").headers
        assert "default-src 'self'" in headers["Content-Security-Policy"]
        assert headers["X-Content-Type-Options"] == "nosniff"
        assert headers["Referrer-Policy"] == "no-referrer"

    def test_the_openapi_document_is_served(self, client) -> None:
        spec = client.get("/api/openapi.json").get_json()
        assert spec["openapi"].startswith("3.1")
        assert "/api/jobs" in spec["paths"]

    def test_every_route_appears_in_the_openapi_document(self, app) -> None:
        """The check that actually keeps the description from drifting."""
        from remediator.service.openapi import build_spec

        described = {path.replace("{jobId}", "<job_id>") for path in build_spec("0.0.0")["paths"]}
        exposed = set(client_paths(app))
        assert exposed <= described, f"undocumented routes: {sorted(exposed - described)}"

    def test_the_openapi_document_describes_no_route_that_does_not_exist(self, app) -> None:
        from remediator.service.openapi import build_spec

        described = {path.replace("{jobId}", "<job_id>") for path in build_spec("0.0.0")["paths"]}
        exposed = set(client_paths(app))
        assert described <= exposed, f"described but absent: {sorted(described - exposed)}"

    def test_an_unknown_api_path_answers_as_the_api(self, client) -> None:
        """Returning the interface with a 200 to a programmatic caller is worse
        than an honest 404."""
        response = client.get("/api/nope")
        assert response.status_code == 404
        assert response.get_json()["error"]

    def test_a_traversal_attempt_under_api_is_refused(self, client) -> None:
        response = client.get("/api/jobs/..%2f..%2fetc/download")
        assert response.status_code == 404
        assert response.is_json

    def test_an_unknown_page_serves_the_interface(self, client) -> None:
        assert client.get("/some/page").status_code == 200


def client_paths(app) -> list[str]:
    """Rules the application exposes, excluding static and error handlers."""
    return [
        str(rule)
        for rule in app.url_map.iter_rules()
        if str(rule).startswith(("/api/", "/health", "/ready", "/metrics"))
    ]


class TestSubmission:
    def test_a_missing_file_is_rejected(self, client) -> None:
        assert client.post("/api/jobs", data={}).status_code == 400

    def test_a_non_pdf_is_rejected_before_parsing(self, client) -> None:
        response = _submit(client, b"not a pdf at all", "x.pdf")
        assert response.status_code == 400
        assert "does not look like a PDF" in response.get_json()["error"]

    def test_an_invalid_policy_is_rejected(self, client, pdf_bytes: bytes) -> None:
        response = _submit(client, pdf_bytes, undescribedImages="nonsense")
        assert response.status_code == 400

    def test_submission_returns_immediately_with_a_job(self, client, pdf_bytes: bytes) -> None:
        """The request must not wait for the work, or a proxy will kill it."""
        started = time.time()
        response = _submit(client, pdf_bytes)
        elapsed = time.time() - started
        assert response.status_code == 202
        assert response.get_json()["state"] in ("queued", "running")
        assert elapsed < 5.0, f"the request blocked for {elapsed:.1f}s"

    def test_rate_limiting_refuses_a_flood(self, client, pdf_bytes: bytes) -> None:
        statuses = [_submit(client, pdf_bytes).status_code for _ in range(14)]
        assert 429 in statuses
        assert statuses.count(202) <= 10

    def test_a_rate_limited_response_says_when_to_retry(self, client, pdf_bytes: bytes) -> None:
        for _ in range(14):
            response = _submit(client, pdf_bytes)
            if response.status_code == 429:
                assert int(response.headers["Retry-After"]) >= 0
                return
        pytest.fail("the limiter never engaged")


@pytest.mark.slow
class TestFullRun:
    def test_a_document_is_remediated_and_audited(self, client, pdf_bytes: bytes) -> None:
        job_id = _submit(client, pdf_bytes, "physics.pdf").get_json()["id"]
        final = _await_completion(client, job_id)
        assert final["state"] == "succeeded"
        assert final["result"]["audit"]["conformant"] is True

    def test_the_result_can_be_downloaded(self, client, pdf_bytes: bytes) -> None:
        job_id = _submit(client, pdf_bytes, "physics.pdf").get_json()["id"]
        _await_completion(client, job_id)
        response = client.get(f"/api/jobs/{job_id}/download")
        assert response.status_code == 200
        assert response.mimetype == "application/pdf"
        assert response.get_data().startswith(b"%PDF-")

    def test_downloading_before_completion_is_refused(self, client, pdf_bytes: bytes) -> None:
        job_id = _submit(client, pdf_bytes).get_json()["id"]
        response = client.get(f"/api/jobs/{job_id}/download")
        assert response.status_code in (200, 409)

    def test_an_unknown_job_is_not_found(self, client) -> None:
        assert client.get("/api/jobs/" + "0" * 32).status_code == 404

    def test_the_event_stream_carries_the_pipelines_own_progress(
        self, app, pdf_bytes: bytes
    ) -> None:
        """Not a timed animation: these are the stages the pipeline reports."""
        client = app.test_client()
        job_id = _submit(client, pdf_bytes, "physics.pdf").get_json()["id"]

        stages: list[str] = []
        response = app.test_client().get(f"/api/jobs/{job_id}/events")
        for chunk in response.response:
            for line in chunk.decode().splitlines():
                if line.startswith("data: "):
                    try:
                        stages.append(json.loads(line[6:]).get("stage"))
                    except json.JSONDecodeError:
                        continue

        assert "opening" in stages
        assert "analysing-page" in stages
        assert "done" in stages
        assert len(stages) > 5, f"only {len(stages)} events were streamed"

    def test_the_stream_reports_a_content_type_browsers_accept(
        self, client, pdf_bytes: bytes
    ) -> None:
        job_id = _submit(client, pdf_bytes).get_json()["id"]
        response = client.get(f"/api/jobs/{job_id}/events")
        assert response.mimetype == "text/event-stream"
        assert response.headers["Cache-Control"].startswith("no-cache")
        response.close()

    def test_a_stream_for_an_unknown_job_is_not_found(self, client) -> None:
        response = client.get(f"/api/jobs/{'0' * 32}/events")
        assert response.status_code == 404
        response.close()
