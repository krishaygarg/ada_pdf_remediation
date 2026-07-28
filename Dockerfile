# syntax=docker/dockerfile:1.7

# ---------------------------------------------------------------------------
# Builder: resolve and compile wheels once, so the runtime layer needs no
# compiler toolchain and stays small.
# ---------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /build

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Dependencies are installed before the source is copied so that editing code
# does not invalidate the dependency layer.
COPY requirements.txt ./
RUN pip install --require-hashes=false -r requirements.txt

COPY pyproject.toml README.md LICENSE ./
COPY remediator ./remediator
RUN pip install --no-deps .

# ---------------------------------------------------------------------------
# Runtime
# ---------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS runtime

LABEL org.opencontainers.image.title="ADA PDF Remediator" \
      org.opencontainers.image.description="Automated PDF/UA-1 and WCAG remediation and auditing" \
      org.opencontainers.image.source="https://github.com/krishaygarg/ada_pdf_remediation" \
      org.opencontainers.image.licenses="MIT"

# Poppler backs pdf2image, Tesseract backs the OCR fallback, libgomp is a
# runtime dependency of Tesseract's OpenMP build.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        poppler-utils \
        tesseract-ocr \
        tesseract-ocr-eng \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# An unprivileged account with no login shell. Running as root inside a
# container that parses untrusted documents removes a useful layer of defence.
RUN useradd --system --create-home --uid 10001 --shell /usr/sbin/nologin remediator

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY --chown=remediator:remediator app.py mcp_server_axescheck.py ./
COPY --chown=remediator:remediator web ./web
COPY --chown=remediator:remediator samples ./samples

# Build metadata, surfaced by the health endpoint so a running deployment can
# be matched to the commit that produced it.
ARG GIT_COMMIT=unknown
ENV GIT_COMMIT=${GIT_COMMIT}

ENV PATH="/opt/venv/bin:$PATH" \
    PORT=5000 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    ADA_REMEDIATOR_TMP=/tmp/ada-remediator

RUN install -d -o remediator -g remediator /tmp/ada-remediator

USER remediator

EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,os,sys; \
sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','5000')+'/health', timeout=4).status==200 else 1)"

# Remediation is CPU bound and can take tens of seconds on a large document, so
# the worker timeout is generous and the worker count stays low.
CMD ["sh", "-c", "exec gunicorn --bind 0.0.0.0:${PORT:-5000} --workers 2 --threads 4 --timeout 300 --graceful-timeout 30 --access-logfile - --error-logfile - app:app"]
