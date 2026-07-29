"""Job store and worker pool.

Remediation previously ran inside the request thread. A large document takes
longer than a proxy or a gunicorn worker will wait, so the request was killed
mid-run and the caller saw a timeout with no way to find out what happened.

Work is now submitted to a bounded pool and tracked in SQLite. SQLite rather
than a dictionary because a job outlives the request that created it and should
outlive a worker restart, and because it gives the retention sweep something to
query. A queue server would be the right answer at a different scale; it is not
worth the operational weight here.
"""

from __future__ import annotations

import enum
import json
import sqlite3
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..progress import ProgressEvent, Stage

#: Jobs and their files are deleted after this long. An uploaded document may
#: be confidential, so keeping it indefinitely is a liability rather than a
#: convenience.
DEFAULT_RETENTION_SECONDS = 60 * 60

#: Concurrent remediations. Each one is CPU bound and can allocate heavily on a
#: large document, so the default is deliberately small.
DEFAULT_WORKERS = 2

#: Queued jobs beyond this are refused, so an overloaded instance says so
#: rather than accepting work it will not reach for an hour.
DEFAULT_QUEUE_LIMIT = 32


class JobState(enum.Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"

    @property
    def is_terminal(self) -> bool:
        return self in (JobState.SUCCEEDED, JobState.FAILED)


@dataclass
class Job:
    id: str
    state: JobState
    filename: str
    created_at: float
    updated_at: float
    input_path: str
    output_path: str
    error: str | None = None
    result: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "state": self.state.value,
            "filename": self.filename,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
            "error": self.error,
            "result": self.result or None,
        }


class QueueFull(RuntimeError):
    """Raised when the pending queue is at its limit."""


_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id           TEXT PRIMARY KEY,
    state        TEXT NOT NULL,
    filename     TEXT NOT NULL,
    created_at   REAL NOT NULL,
    updated_at   REAL NOT NULL,
    input_path   TEXT NOT NULL,
    output_path  TEXT NOT NULL,
    error        TEXT,
    result       TEXT
);
CREATE INDEX IF NOT EXISTS jobs_created_at ON jobs (created_at);
CREATE INDEX IF NOT EXISTS jobs_state ON jobs (state);
"""


class JobStore:
    """Persistent job records with an in-process event stream per job."""

    def __init__(self, database: Path | str, workspace: Path | str) -> None:
        self.database = Path(database)
        self.workspace = Path(workspace)
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        # Events live in memory only. They are useful while a job runs and
        # uninteresting afterwards, so persisting them would trade disk for
        # nothing.
        self._events: dict[str, list[ProgressEvent]] = {}
        self._conditions: dict[str, threading.Condition] = {}
        with self._connect() as connection:
            connection.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database, timeout=10.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    # -- lifecycle ---------------------------------------------------------

    def create(self, filename: str) -> Job:
        job_id = uuid.uuid4().hex
        directory = self.workspace / job_id
        directory.mkdir(parents=True, exist_ok=True)
        now = time.time()
        job = Job(
            id=job_id,
            state=JobState.QUEUED,
            filename=filename,
            created_at=now,
            updated_at=now,
            input_path=str(directory / "input.pdf"),
            output_path=str(directory / "remediated.pdf"),
        )
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT INTO jobs (id, state, filename, created_at, updated_at,"
                " input_path, output_path) VALUES (?,?,?,?,?,?,?)",
                (
                    job.id,
                    job.state.value,
                    job.filename,
                    job.created_at,
                    job.updated_at,
                    job.input_path,
                    job.output_path,
                ),
            )
        self._events[job_id] = []
        self._conditions[job_id] = threading.Condition()
        return job

    def get(self, job_id: str) -> Job | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            return None
        return Job(
            id=row["id"],
            state=JobState(row["state"]),
            filename=row["filename"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            input_path=row["input_path"],
            output_path=row["output_path"],
            error=row["error"],
            result=json.loads(row["result"]) if row["result"] else {},
        )

    def update(
        self,
        job_id: str,
        *,
        state: JobState | None = None,
        error: str | None = None,
        result: dict[str, Any] | None = None,
    ) -> None:
        fields: list[str] = ["updated_at = ?"]
        values: list[Any] = [time.time()]
        if state is not None:
            fields.append("state = ?")
            values.append(state.value)
        if error is not None:
            fields.append("error = ?")
            values.append(error)
        if result is not None:
            fields.append("result = ?")
            values.append(json.dumps(result))
        values.append(job_id)
        with self._lock, self._connect() as connection:
            connection.execute(f"UPDATE jobs SET {', '.join(fields)} WHERE id = ?", values)

    def pending_count(self) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS n FROM jobs WHERE state IN (?, ?)",
                (JobState.QUEUED.value, JobState.RUNNING.value),
            ).fetchone()
        return int(row["n"])

    # -- events ------------------------------------------------------------

    def record_event(self, job_id: str, event: ProgressEvent) -> None:
        condition = self._conditions.get(job_id)
        if condition is None:
            return
        with condition:
            self._events.setdefault(job_id, []).append(event)
            condition.notify_all()

    def follow(self, job_id: str, timeout: float = 300.0) -> Iterator[ProgressEvent]:
        """Yield events as they arrive, ending when the job reaches a terminal state.

        The deadline is a safety net. Without one, a client that never
        disconnects would hold a worker thread open indefinitely if a job were
        somehow lost.
        """
        condition = self._conditions.get(job_id)
        if condition is None:
            return
        deadline = time.time() + timeout
        index = 0
        while True:
            with condition:
                pending = self._events.get(job_id, [])
                while index < len(pending):
                    yield pending[index]
                    index += 1
                job = self.get(job_id)
                if job is not None and job.state.is_terminal:
                    return
                remaining = deadline - time.time()
                if remaining <= 0:
                    return
                condition.wait(timeout=min(1.0, remaining))

    def wake(self, job_id: str) -> None:
        """Release anything waiting on this job, used when it finishes."""
        condition = self._conditions.get(job_id)
        if condition is not None:
            with condition:
                condition.notify_all()

    # -- retention ---------------------------------------------------------

    def sweep(self, retention_seconds: float = DEFAULT_RETENTION_SECONDS) -> int:
        """Delete jobs and their files once they are older than the retention.

        Returns the number removed. Called on a timer and opportunistically on
        upload, so an instance nobody is watching still cleans up after itself.
        """
        import shutil

        cutoff = time.time() - retention_seconds
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id FROM jobs WHERE created_at < ?", (cutoff,)
            ).fetchall()
            identifiers = [row["id"] for row in rows]
            if identifiers:
                connection.executemany(
                    "DELETE FROM jobs WHERE id = ?", [(value,) for value in identifiers]
                )

        for job_id in identifiers:
            shutil.rmtree(self.workspace / job_id, ignore_errors=True)
            self._events.pop(job_id, None)
            self._conditions.pop(job_id, None)
        return len(identifiers)


class JobRunner:
    """Executes jobs on a bounded pool."""

    def __init__(
        self,
        store: JobStore,
        workers: int = DEFAULT_WORKERS,
        queue_limit: int = DEFAULT_QUEUE_LIMIT,
    ) -> None:
        self.store = store
        self.queue_limit = queue_limit
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="remediate")

    def submit(self, job: Job, work: Callable[[Job], dict[str, Any]]) -> Future[None]:
        if self.store.pending_count() > self.queue_limit:
            raise QueueFull(
                f"{self.queue_limit} jobs are already queued or running; try again shortly"
            )
        return self._pool.submit(self._run, job, work)

    def _run(self, job: Job, work: Callable[[Job], dict[str, Any]]) -> None:
        self.store.update(job.id, state=JobState.RUNNING)
        try:
            result = work(job)
            self.store.update(job.id, state=JobState.SUCCEEDED, result=result)
            self.store.record_event(
                job.id, ProgressEvent(stage=Stage.DONE, message="Remediation finished")
            )
        except Exception as exc:
            self.store.update(job.id, state=JobState.FAILED, error=str(exc))
            self.store.record_event(
                job.id, ProgressEvent(stage=Stage.FAILED, message=f"Remediation failed: {exc}")
            )
        finally:
            self.store.wake(job.id)

    def shutdown(self, wait: bool = True) -> None:
        self._pool.shutdown(wait=wait)


__all__ = [
    "DEFAULT_QUEUE_LIMIT",
    "DEFAULT_RETENTION_SECONDS",
    "DEFAULT_WORKERS",
    "Job",
    "JobRunner",
    "JobState",
    "JobStore",
    "QueueFull",
]
