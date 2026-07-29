"""Report output formats.

Each format serves a different consumer: text for a person at a terminal, JSON
for the API and the web interface, SARIF so findings annotate a pull request
diff, and JUnit so a CI run shows which conformance rules failed alongside the
unit tests.
"""

from __future__ import annotations

from ..model import Report
from .structured import to_dict, to_json, to_junit, to_sarif
from .text import render as to_text

FORMATS = ("text", "json", "sarif", "junit")


def render(report: Report, fmt: str = "text") -> str:
    """Render ``report`` in the named format."""
    if fmt == "text":
        return to_text(report)
    if fmt == "json":
        return to_json(report)
    if fmt == "sarif":
        return to_sarif(report)
    if fmt == "junit":
        return to_junit(report)
    raise ValueError(f"unknown report format {fmt!r}; expected one of {', '.join(FORMATS)}")


__all__ = ["FORMATS", "render", "to_dict", "to_json", "to_junit", "to_sarif", "to_text"]
