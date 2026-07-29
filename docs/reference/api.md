# HTTP API

The full description is served at `/api/openapi.json` and two tests keep it in step with the routes in both directions.

Documents are processed asynchronously, because remediation can outlast a proxy timeout.

```bash
# Submit; returns immediately
curl -F pdf=@input.pdf http://localhost:5000/api/jobs
# {"id": "a1b2...", "state": "queued"}

# Follow real progress from the pipeline
curl -N http://localhost:5000/api/jobs/a1b2.../events

# Retrieve
curl -O -J http://localhost:5000/api/jobs/a1b2.../download
```

| Endpoint | Purpose |
|---|---|
| `POST /api/jobs` | Submit a document. Accepts `undescribedImages` as `figure` or `artifact`. |
| `GET /api/jobs/{id}` | The job record, including the audit once it finishes. |
| `GET /api/jobs/{id}/events` | Server-sent events carrying the pipeline's own stages. |
| `GET /api/jobs/{id}/download` | The tagged document. |
| `GET /health` | Liveness. |
| `GET /ready` | Readiness, which is separate: a process that cannot reach its job store should leave rotation rather than restart. |
| `GET /metrics` | Prometheus text exposition. |

## Operating it

Uploads are validated for extension, size and signature before any parser sees them. Encryption and active content produce warnings rather than refusals, because a legitimate document can carry both.

**Uploads and results are deleted after one hour**, on a timer as well as on upload. Rate limiting is per worker, not fleet-wide.
