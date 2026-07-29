"""The OpenAPI description of the service.

Written by hand and kept next to the routes. A test asserts every route the
application exposes appears here, which is the part that actually stops the
two drifting apart.
"""

from __future__ import annotations

from typing import Any

from ..audit import RemediationStatus
from .security import MAX_UPLOAD_BYTES

#: Derived from the enum rather than restated, so a new status cannot be added
#: to the model while the published description keeps advertising the old set.
REMEDIATION_STATUSES = tuple(status.value for status in RemediationStatus)


def build_spec(version: str) -> dict[str, Any]:
    """Return the OpenAPI 3.1 document for the service."""
    limit_mb = MAX_UPLOAD_BYTES // (1024 * 1024)
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "ADA PDF Remediator",
            "version": version,
            "summary": "Remediate PDF documents towards PDF/UA-1 and audit the result.",
            "description": (
                "Documents are processed asynchronously. Upload to POST /api/jobs, "
                "follow GET /api/jobs/{id}/events for real progress, then retrieve "
                "the result from GET /api/jobs/{id}/download.\n\n"
                "Uploaded documents and their results are deleted after one hour."
            ),
            "license": {"name": "MIT", "identifier": "MIT"},
        },
        "servers": [{"url": "/", "description": "This instance"}],
        "paths": {
            "/health": {
                "get": {
                    "summary": "Liveness probe",
                    "operationId": "health",
                    "responses": {
                        "200": {
                            "description": "The process is running.",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/Health"}
                                }
                            },
                        }
                    },
                }
            },
            "/ready": {
                "get": {
                    "summary": "Readiness probe",
                    "description": "Reports whether dependencies are reachable.",
                    "operationId": "ready",
                    "responses": {
                        "200": {"description": "Ready to accept work."},
                        "503": {"description": "Running but unable to serve."},
                    },
                }
            },
            "/metrics": {
                "get": {
                    "summary": "Prometheus metrics",
                    "operationId": "metrics",
                    "responses": {
                        "200": {
                            "description": "Metrics in the text exposition format.",
                            "content": {"text/plain": {"schema": {"type": "string"}}},
                        }
                    },
                }
            },
            "/api/jobs": {
                "post": {
                    "summary": "Submit a document",
                    "operationId": "createJob",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "multipart/form-data": {
                                "schema": {
                                    "type": "object",
                                    "required": ["pdf"],
                                    "properties": {
                                        "pdf": {
                                            "type": "string",
                                            "format": "binary",
                                            "description": f"The document, up to {limit_mb} MB.",
                                        },
                                        "undescribedImages": {
                                            "type": "string",
                                            "enum": ["figure", "artifact"],
                                            "default": "figure",
                                            "description": (
                                                "How to treat an image nobody has described. "
                                                "'figure' tags it as content and reports the "
                                                "missing description, which does not conform. "
                                                "'artifact' marks it decorative, which conforms "
                                                "but removes it from the reading order."
                                            ),
                                        },
                                    },
                                }
                            }
                        },
                    },
                    "responses": {
                        "202": {
                            "description": "Accepted and queued.",
                            "content": {
                                "application/json": {"schema": {"$ref": "#/components/schemas/Job"}}
                            },
                        },
                        "400": {"description": "The upload was rejected."},
                        "413": {"description": "The file exceeds the size limit."},
                        "429": {"description": "Rate limited."},
                        "503": {"description": "The queue is full."},
                    },
                }
            },
            "/api/jobs/{jobId}": {
                "get": {
                    "summary": "Read a job",
                    "operationId": "readJob",
                    "parameters": [_job_id_parameter()],
                    "responses": {
                        "200": {
                            "description": "The job record.",
                            "content": {
                                "application/json": {"schema": {"$ref": "#/components/schemas/Job"}}
                            },
                        },
                        "404": {"description": "Unknown or expired."},
                    },
                }
            },
            "/api/jobs/{jobId}/events": {
                "get": {
                    "summary": "Follow progress",
                    "description": (
                        "Server-sent events carrying the pipeline's own progress, "
                        "ending when the job reaches a terminal state."
                    ),
                    "operationId": "jobEvents",
                    "parameters": [_job_id_parameter()],
                    "responses": {
                        "200": {
                            "description": "An event stream.",
                            "content": {"text/event-stream": {"schema": {"type": "string"}}},
                        },
                        "404": {"description": "Unknown or expired."},
                    },
                }
            },
            "/api/jobs/{jobId}/download": {
                "get": {
                    "summary": "Retrieve the remediated document",
                    "operationId": "downloadJob",
                    "parameters": [_job_id_parameter()],
                    "responses": {
                        "200": {
                            "description": "The document.",
                            "content": {
                                "application/pdf": {
                                    "schema": {"type": "string", "format": "binary"}
                                }
                            },
                        },
                        "404": {"description": "Unknown or expired."},
                        "409": {"description": "The job has not succeeded."},
                        "410": {
                            "description": "The result has been deleted by the retention policy."
                        },
                    },
                }
            },
            "/api/openapi.json": {
                "get": {
                    "summary": "This document",
                    "operationId": "openapi",
                    "responses": {"200": {"description": "The OpenAPI description."}},
                }
            },
        },
        "components": {
            "schemas": {
                "Health": {
                    "type": "object",
                    "properties": {
                        "status": {"type": "string"},
                        "service": {"type": "string"},
                        "version": {"type": "string"},
                        "commit": {"type": "string"},
                        "uptimeSeconds": {"type": "number"},
                    },
                },
                "Job": {
                    "type": "object",
                    "required": ["id", "state", "filename"],
                    "properties": {
                        "id": {"type": "string"},
                        "state": {
                            "type": "string",
                            "enum": ["queued", "running", "succeeded", "failed"],
                        },
                        "filename": {"type": "string"},
                        "createdAt": {"type": "number"},
                        "updatedAt": {"type": "number"},
                        "error": {"type": ["string", "null"]},
                        "warnings": {"type": "array", "items": {"type": "string"}},
                        "result": {
                            "type": ["object", "null"],
                            "properties": {"audit": {"$ref": "#/components/schemas/AuditReport"}},
                        },
                    },
                },
                "AuditReport": {
                    "type": "object",
                    "properties": {
                        "conformant": {"type": "boolean"},
                        "rulesRun": {"type": "integer"},
                        "counts": {
                            "type": "object",
                            "properties": {
                                "errors": {"type": "integer"},
                                "warnings": {"type": "integer"},
                                "review": {"type": "integer"},
                            },
                        },
                        "remediation": {
                            "type": "object",
                            "description": (
                                "Findings by repair status. Every status is present, including "
                                "the zeroes, so an absent key means an older server rather than "
                                "a count of none."
                            ),
                            "properties": {
                                status: {"type": "integer"} for status in REMEDIATION_STATUSES
                            },
                        },
                        "findings": {
                            "type": "array",
                            "items": {"$ref": "#/components/schemas/Finding"},
                        },
                    },
                },
                "Finding": {
                    "type": "object",
                    "properties": {
                        "condition": {
                            "type": "string",
                            "description": "Matterhorn Protocol failure condition, such as 13-004.",
                        },
                        "checkpoint": {"type": "string"},
                        "severity": {"type": "string", "enum": ["error", "warning", "review"]},
                        "message": {"type": "string"},
                        "remedy": {"type": ["string", "null"]},
                        "remediation": {
                            "type": "string",
                            "enum": list(REMEDIATION_STATUSES),
                            "description": (
                                "What a repair attempt did. Separate from severity: "
                                "not_attempted and failed are both unfixed, and they call "
                                "for different next actions."
                            ),
                        },
                        "remediationDetail": {
                            "type": ["string", "null"],
                            "description": "Why a repair failed, or what it changed.",
                        },
                    },
                },
            }
        },
    }


def _job_id_parameter() -> dict[str, Any]:
    return {
        "name": "jobId",
        "in": "path",
        "required": True,
        "schema": {"type": "string", "pattern": "^[0-9a-f]{32}$"},
    }


__all__ = ["build_spec"]
