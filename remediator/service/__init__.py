"""HTTP service for remediating documents.

Work runs on a bounded pool and is tracked in a job store, so a request returns
straight away and a long document is not killed by a proxy timeout. Progress is
streamed from the pipeline itself rather than animated on a timer.
"""

from __future__ import annotations

from .app import build_commit, create_app
from .jobs import Job, JobRunner, JobState, JobStore, QueueFull
from .security import RateLimiter, UploadVerdict, validate_upload

__all__ = [
    "Job",
    "JobRunner",
    "JobState",
    "JobStore",
    "QueueFull",
    "RateLimiter",
    "UploadVerdict",
    "build_commit",
    "create_app",
    "validate_upload",
]
