"""Structured progress reporting.

The pipeline previously communicated only by printing. That is fine at a
terminal and useless to anything else, which is why the web interface animated
a fabricated sequence of steps on a timer while the real work happened
invisibly behind it.

A reporter receives typed events. The console reporter prints them, so the
command line behaves as before, and the service reporter forwards them to a
browser over server-sent events, so the interface shows what is actually
happening.
"""

from __future__ import annotations

import contextlib
import enum
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


class Stage(enum.Enum):
    """The phases of a remediation run, in the order they occur."""

    OPENING = "opening"
    ANALYSING_PAGE = "analysing-page"
    TAGGING_FIGURES = "tagging-figures"
    RECOGNISING_TEXT = "recognising-text"
    RECOVERING_FONTS = "recovering-fonts"
    BUILDING_STRUCTURE = "building-structure"
    WRITING = "writing"
    AUDITING = "auditing"
    DONE = "done"
    FAILED = "failed"

    @property
    def label(self) -> str:
        return {
            "opening": "Reading the document",
            "analysing-page": "Analysing pages",
            "tagging-figures": "Tagging figures",
            "recognising-text": "Recognising scanned text",
            "recovering-fonts": "Recovering character mappings",
            "building-structure": "Building the structure tree",
            "writing": "Writing the result",
            "auditing": "Auditing conformance",
            "done": "Finished",
            "failed": "Failed",
        }[self.value]


@dataclass(frozen=True)
class ProgressEvent:
    """One thing that happened during a run."""

    stage: Stage
    message: str
    current: int | None = None
    total: int | None = None
    detail: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    @property
    def fraction(self) -> float | None:
        """Completion within the stage, when it is countable."""
        if self.current is None or not self.total:
            return None
        return max(0.0, min(1.0, self.current / self.total))

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage.value,
            "label": self.stage.label,
            "message": self.message,
            "current": self.current,
            "total": self.total,
            "fraction": self.fraction,
            "detail": self.detail,
            "timestamp": self.timestamp,
        }


@runtime_checkable
class ProgressReporter(Protocol):
    """Receives progress events. Implementations must not raise."""

    def __call__(self, event: ProgressEvent) -> None:
        """Handle one progress event."""


class NullReporter:
    """Discards events, for callers that want the pipeline silent."""

    def __call__(self, event: ProgressEvent) -> None:  # noqa: ARG002 - protocol shape
        return None


class ConsoleReporter:
    """Prints events, reproducing the previous command line output."""

    def __init__(self, stream: Any = None) -> None:
        self._stream = stream if stream is not None else sys.stdout

    def __call__(self, event: ProgressEvent) -> None:
        if event.current is not None and event.total:
            prefix = f"[{event.current}/{event.total}]"
        else:
            prefix = "[REMEDIATOR]"
        print(f"{prefix} {event.message}", file=self._stream)


class CollectingReporter:
    """Keeps every event, for tests and for replaying a finished job."""

    def __init__(self) -> None:
        self.events: list[ProgressEvent] = []

    def __call__(self, event: ProgressEvent) -> None:
        self.events.append(event)

    def stages(self) -> list[Stage]:
        return [event.stage for event in self.events]


def emit(
    reporter: ProgressReporter | None,
    stage: Stage,
    message: str,
    *,
    current: int | None = None,
    total: int | None = None,
    **detail: Any,
) -> None:
    """Send an event, tolerating a reporter that misbehaves.

    A failure in reporting must never abort a remediation run. Losing a
    progress line is a cosmetic problem; losing the document is not.
    """
    if reporter is None:
        return
    # Reporting is best effort. Losing a progress line is cosmetic; letting a
    # broken reporter abort the run would lose the document.
    with contextlib.suppress(Exception):
        reporter(
            ProgressEvent(stage=stage, message=message, current=current, total=total, detail=detail)
        )


__all__ = [
    "CollectingReporter",
    "ConsoleReporter",
    "NullReporter",
    "ProgressEvent",
    "ProgressReporter",
    "Stage",
    "emit",
]
