"""Human readable console report."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import IO, Any

from ..model import Report, Severity


class _Palette:
    """ANSI colours, disabled when the output is not an interactive terminal.

    Colour codes written into a redirected file or a CI log are noise, and
    NO_COLOR is the convention for turning them off deliberately.
    """

    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled

    def __call__(self, code: str, text: str) -> str:
        return f"\033[{code}m{text}\033[0m" if self.enabled else text

    def red(self, text: str) -> str:
        return self("91", text)

    def green(self, text: str) -> str:
        return self("92", text)

    def yellow(self, text: str) -> str:
        return self("93", text)

    def blue(self, text: str) -> str:
        return self("94", text)

    def dim(self, text: str) -> str:
        return self("2", text)

    def bold(self, text: str) -> str:
        return self("1", text)


def _should_colour(stream: Any) -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    return hasattr(stream, "isatty") and stream.isatty()


_LABELS = {
    Severity.ERROR: ("FAIL", "red"),
    Severity.WARNING: ("WARN", "yellow"),
    Severity.REVIEW: ("CHECK", "blue"),
}


def render(report: Report, *, stream: IO[str] | None = None, verbose: bool = True) -> str:
    """Render ``report`` as text, writing to ``stream`` when one is given."""
    target = stream if stream is not None else sys.stdout
    colour = _Palette(_should_colour(target))
    lines: list[str] = []
    width = 78

    lines.append("=" * width)
    lines.append(f" Accessibility audit: {Path(report.document).name}")
    lines.append("=" * width)

    if report.rules_errored:
        # A rule that crashed leaves a hole in the audit. Saying so up front is
        # the difference between "no problems found" and "did not finish".
        lines.append(colour.red(" Some checks did not complete:"))
        for condition, error in sorted(report.rules_errored.items()):
            lines.append(colour.red(f"   {condition}: {error}"))
        lines.append("")

    if verbose and report.findings:
        for checkpoint, findings in report.by_checkpoint().items():
            lines.append(colour.bold(f" Checkpoint {checkpoint}"))
            for finding in findings:
                label, style = _LABELS[finding.severity]
                painted = getattr(colour, style)(f"[{label}]")
                lines.append(f"   {painted} {finding.condition}  {finding.message}")
                where = finding.location.describe()
                if where != "document":
                    lines.append(colour.dim(f"          at {where}"))
                if finding.remedy:
                    lines.append(colour.dim(f"          fix: {finding.remedy}"))
            lines.append("")

    lines.append("-" * width)
    errors, warnings, reviews = len(report.errors), len(report.warnings), len(report.reviews)
    lines.append(f" Rules run   : {report.rules_run}")
    lines.append(f" Errors      : {colour.red(str(errors)) if errors else colour.green('0')}")
    lines.append(
        f" Warnings    : {colour.yellow(str(warnings)) if warnings else colour.green('0')}"
    )
    if reviews:
        lines.append(f" Needs review: {colour.blue(str(reviews))}")
    lines.append("=" * width)

    if report.conformant:
        lines.append(
            colour.green(" No conformance errors found.")
            + colour.dim(" Machine checks cannot confirm that the document reads well;")
        )
        lines.append(
            colour.dim(
                " the Matterhorn Protocol leaves 47 of its 136 conditions to human judgement."
            )
        )
    else:
        lines.append(colour.red(" The document does not conform."))
    lines.append("")

    text = "\n".join(lines)
    if stream is not None:
        stream.write(text)
    return text
