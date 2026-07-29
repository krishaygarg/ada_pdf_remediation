#!/usr/bin/env python3
"""Accessibility conformance auditing.

This module is the stable entry point. The rules themselves live in
:mod:`remediator.audit`, where each one names the Matterhorn Protocol failure
condition it implements.

The previous implementation performed seven ad-hoc checks, reopened the
document once per check, and reported success whenever those seven passed. It
also looked for the PDF/UA identifier under the wrong namespace, so it
confirmed a defect in the writer instead of catching it. Anchoring every rule
to a published condition, and cross-checking the engine against an independent
validator, is what stops that class of mistake recurring.
"""

from __future__ import annotations

import sys
from pathlib import Path

from .audit import Report, audit_document
from .audit.reporters import render


def audit(pdf_path: str | Path) -> Report:
    """Audit ``pdf_path`` and return the full report."""
    return audit_document(pdf_path)


def run_compliance_check(pdf_path: str, verbose: bool = True) -> bool:
    """Audit a document and report whether it conforms.

    Retained with its original signature so existing callers keep working.
    Prefer :func:`audit` in new code, which returns the findings rather than
    collapsing them into a single boolean.

    Args:
        pdf_path: Path to the document to audit.
        verbose: Print a detailed console report.

    Returns:
        True when no error-level finding was raised and every rule completed.
    """
    if not Path(pdf_path).exists():
        if verbose:
            print(f"Error: file not found: {pdf_path}", file=sys.stderr)
        return False

    report = audit_document(pdf_path)
    if verbose:
        print(render(report, "text"))
    return report.conformant


__all__ = ["audit", "run_compliance_check"]
