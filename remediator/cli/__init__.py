"""Command line entry points for the remediator package.

These live inside the installed package so that the console scripts declared
in ``pyproject.toml`` resolve after a regular (non-editable) installation.
"""

from __future__ import annotations

__all__ = ["compliance", "remediate"]
