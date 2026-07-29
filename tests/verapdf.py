"""Thin wrapper around the veraPDF command line validator.

veraPDF is the reference open source implementation of PDF/UA validation. The
project's own auditor is fast and runs in process, but it is written by the
same people who write the remediation code, so it cannot be the only evidence
that output conforms. Checking against an independent implementation is what
makes a compliance claim mean something.

The binary is optional. Tests that use it skip when it is absent so that a
contributor without a Java runtime can still work on the project.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RuleFailure:
    """One validation rule that the document did not satisfy."""

    clause: str
    test_number: int
    description: str
    failed_checks: int

    @property
    def identifier(self) -> str:
        return f"{self.clause}-{self.test_number}"

    def __str__(self) -> str:
        return f"{self.identifier} ({self.failed_checks} failed): {self.description}"


@dataclass(frozen=True)
class ValidationResult:
    compliant: bool
    passed_rules: int
    failed_rules: int
    failed_checks: int
    failures: tuple[RuleFailure, ...]

    def describe(self) -> str:
        if self.compliant:
            return f"compliant, {self.passed_rules} rules passed"
        lines = [f"not compliant: {self.failed_rules} rules, {self.failed_checks} checks"]
        lines.extend(f"  {failure}" for failure in self.failures)
        return "\n".join(lines)


def find_verapdf() -> str | None:
    """Locate the veraPDF executable, preferring an explicit override.

    ``VERAPDF_CLI`` takes precedence so a contributor can point at an
    installation that is not on ``PATH``.
    """
    override = os.environ.get("VERAPDF_CLI")
    if override and Path(override).is_file() and os.access(override, os.X_OK):
        return override
    return shutil.which("verapdf")


def available() -> bool:
    return find_verapdf() is not None


def validate(pdf_path: Path | str, flavour: str = "ua1") -> ValidationResult:
    """Validate ``pdf_path`` against a veraPDF flavour such as ``ua1``.

    Raises:
        RuntimeError: If veraPDF is unavailable or produced unreadable output.
    """
    executable = find_verapdf()
    if executable is None:
        raise RuntimeError("veraPDF is not installed; guard the call with available()")

    completed = subprocess.run(
        [executable, "-f", flavour, "--format", "json", str(pdf_path)],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    # veraPDF exits non-zero when a document fails validation, which is a
    # result rather than an error, so the return code is not checked here.
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:  # pragma: no cover - defensive
        raise RuntimeError(
            f"veraPDF produced unreadable output (exit {completed.returncode}): "
            f"{completed.stdout[:400]}{completed.stderr[:400]}"
        ) from exc

    jobs = payload.get("report", {}).get("jobs", [])
    if not jobs:  # pragma: no cover - defensive
        raise RuntimeError("veraPDF returned no validation jobs")

    result = jobs[0].get("validationResult")
    if isinstance(result, list):
        if not result:  # pragma: no cover - defensive
            raise RuntimeError("veraPDF returned an empty validation result")
        result = result[0]

    details = result.get("details", {})
    failures = tuple(
        RuleFailure(
            clause=str(summary.get("clause")),
            test_number=int(summary.get("testNumber", 0)),
            description=str(summary.get("description", "")),
            failed_checks=int(summary.get("failedChecks", 0)),
        )
        for summary in details.get("ruleSummaries", [])
        if summary.get("failedChecks")
    )
    return ValidationResult(
        compliant=bool(result.get("compliant")),
        passed_rules=int(details.get("passedRules", 0)),
        failed_rules=int(details.get("failedRules", 0)),
        failed_checks=int(details.get("failedChecks", 0)),
        failures=failures,
    )
