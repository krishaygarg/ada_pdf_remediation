"""Request limits, response headers and upload validation.

The service accepts arbitrary PDF files from anonymous callers and parses them
with libraries written in C. That is the whole threat model in one sentence, so
the checks here are about refusing input early and cheaply.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass

#: Uploads above this are refused before being read into the worker.
MAX_UPLOAD_BYTES = 50 * 1024 * 1024

#: A PDF begins with this signature. Checking it rejects a mislabelled upload
#: without handing it to the parser.
PDF_MAGIC = b"%PDF-"

#: How far into the file the signature may appear. The specification allows
#: leading bytes, and some producers emit them, but not many.
PDF_MAGIC_SEARCH_WINDOW = 1024

#: Actions that make a viewer do something other than display the document.
#: Their presence is reported rather than treated as fatal, because a legitimate
#: document can carry them, but the operator should know before publishing.
RISKY_ACTIONS = ("/JavaScript", "/JS", "/Launch", "/EmbeddedFile", "/RichMedia", "/GoToR")


@dataclass(frozen=True)
class UploadVerdict:
    """The outcome of validating an upload."""

    accepted: bool
    reason: str = ""
    warnings: tuple[str, ...] = ()


def validate_upload(data: bytes, filename: str) -> UploadVerdict:
    """Check an uploaded file before it reaches the pipeline."""
    if not filename.lower().endswith(".pdf"):
        return UploadVerdict(False, "The file must have a .pdf extension.")
    if not data:
        return UploadVerdict(False, "The uploaded file is empty.")
    if len(data) > MAX_UPLOAD_BYTES:
        limit = MAX_UPLOAD_BYTES // (1024 * 1024)
        return UploadVerdict(False, f"The file exceeds the {limit} MB limit.")
    if PDF_MAGIC not in data[:PDF_MAGIC_SEARCH_WINDOW]:
        return UploadVerdict(False, "The file does not look like a PDF.")

    warnings: list[str] = []
    if b"/Encrypt" in data:
        warnings.append(
            "The document appears to be encrypted. Remediation may fail or produce "
            "an incomplete result."
        )
    present = sorted({action for action in RISKY_ACTIONS if action.encode("ascii") in data})
    if present:
        warnings.append(
            "The document contains active content ("
            + ", ".join(name.lstrip("/") for name in present)
            + "). Review it before publishing the result."
        )
    return UploadVerdict(True, warnings=tuple(warnings))


class RateLimiter:
    """A fixed-window limiter keyed by caller.

    In process and therefore per worker, which is the honest description: it
    exists to stop one client saturating an instance, not to enforce a quota
    across a fleet. A shared store would be needed for that.
    """

    def __init__(self, limit: int, window_seconds: float) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str) -> tuple[bool, float]:
        """Return ``(allowed, seconds until a slot frees)``."""
        now = time.time()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] > self.window_seconds:
                hits.popleft()
            if len(hits) >= self.limit:
                return False, max(0.0, self.window_seconds - (now - hits[0]))
            hits.append(now)
            # Callers that have gone quiet are dropped so the map cannot grow
            # without bound on a long-lived process.
            if len(self._hits) > 4096:
                for other in [k for k, v in self._hits.items() if not v]:
                    del self._hits[other]
            return True, 0.0

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


#: Applied to every response. The interface loads no third-party code, so the
#: policy can be strict enough to be worth having.
SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self'; "
        "img-src 'self' data: blob:; "
        "font-src 'self'; "
        "connect-src 'self'; "
        "object-src 'none'; "
        "base-uri 'none'; "
        "form-action 'self'; "
        "frame-ancestors 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), interest-cohort=()",
}


#: Origins allowed to call the API from a browser. The interface is served
#: from Cloudflare Pages while the API runs elsewhere, so the two are always
#: cross-origin in the deployed configuration and the browser will not send the
#: request at all without this.
#:
#: An allowlist rather than "*", because a wildcard forecloses ever using
#: cookies and quietly invites anyone's page to drive the service.
DEFAULT_ALLOWED_ORIGINS = (
    "https://ada-pdf-remediator.pages.dev",
    "http://localhost:5000",
    "http://127.0.0.1:5000",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
)

#: Comma separated origins to allow in addition, for a fork or a preview
#: deployment that does not share this project's hostnames.
ALLOWED_ORIGINS_ENV_VAR = "ADA_ALLOWED_ORIGINS"


def allowed_origins() -> tuple[str, ...]:
    """Origins the API answers cross-origin requests from."""
    import os

    extra = os.environ.get(ALLOWED_ORIGINS_ENV_VAR, "")
    configured = tuple(value.strip() for value in extra.split(",") if value.strip())
    return DEFAULT_ALLOWED_ORIGINS + configured


def cors_headers(origin: str | None) -> dict[str, str]:
    """Headers permitting ``origin``, or nothing when it is not allowed.

    Returning no header rather than a rejection is deliberate: the browser
    enforces the policy, and echoing back a refusal tells a probing page
    nothing it could not already infer.
    """
    if not origin or origin not in allowed_origins():
        return {}
    return {
        "Access-Control-Allow-Origin": origin,
        # The response differs by origin, so a cache must key on it. Without
        # this a shared cache can serve one origin's headers to another.
        "Vary": "Origin",
        "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type",
        "Access-Control-Max-Age": "600",
    }


def client_key(remote_addr: str | None, forwarded_for: str | None) -> str:
    """Identify the caller for rate limiting.

    The first entry of X-Forwarded-For is used when present, because the
    deployment sits behind a proxy and every request would otherwise share the
    proxy's address. The header is client-controlled, so this is a fairness
    measure and not a security boundary.
    """
    if forwarded_for:
        first = forwarded_for.split(",")[0].strip()
        if first:
            return first
    return remote_addr or "unknown"


__all__ = [
    "ALLOWED_ORIGINS_ENV_VAR",
    "DEFAULT_ALLOWED_ORIGINS",
    "MAX_UPLOAD_BYTES",
    "PDF_MAGIC",
    "RISKY_ACTIONS",
    "SECURITY_HEADERS",
    "RateLimiter",
    "UploadVerdict",
    "allowed_origins",
    "client_key",
    "cors_headers",
    "validate_upload",
]
