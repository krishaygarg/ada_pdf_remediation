"""Data model for conformance findings.

The vocabulary follows the Matterhorn Protocol 1.1, which organises PDF/UA-1
testing into 31 checkpoints containing 136 failure conditions. Of those, 87 are
determinable by software, 47 require human judgement, and 2 have no defined
test. A finding produced here always names the condition it came from, so a
report can be traced back to the clause that motivates it rather than to an
opinion held by this codebase.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field, replace
from typing import Any


class Severity(enum.Enum):
    """How much weight a finding carries.

    ``ERROR`` means the document does not conform. ``WARNING`` marks something
    that conforms but is very likely to obstruct a reader, such as a figure
    whose alternate text merely repeats its file name. ``REVIEW`` marks a
    condition software cannot settle, which a person has to look at.
    """

    ERROR = "error"
    WARNING = "warning"
    REVIEW = "review"

    @property
    def sarif_level(self) -> str:
        return {"error": "error", "warning": "warning", "review": "note"}[self.value]


class Determination(enum.Enum):
    """Whether the Matterhorn Protocol treats a condition as machine testable."""

    SOFTWARE = "software"
    HUMAN = "human"


class RemediationStatus(enum.Enum):
    """What a repair attempt did about a finding.

    Tracked separately from :class:`Severity`, which says how bad a finding is.
    The two answer different questions and collapsing them loses the one that
    matters: a finding nobody tried to fix and a finding somebody tried and
    failed to fix look identical in a report that only records severity, and
    they call for opposite next actions.

    ``NOT_ATTEMPTED`` is the default, so a rule that grows a repair later does
    not silently reclassify every finding it has already produced. ``FAILED``
    exists to be reported rather than retried in silence: a repair that cannot
    complete is evidence about the document, and swallowing it is how a tool
    ends up claiming to have fixed something it did not touch.

    ``NEEDS_PERSON`` is the honest terminus for the 47 conditions the protocol
    assigns to human judgement, and for anything automation could technically
    change but should not decide, such as what a figure means.
    """

    NOT_ATTEMPTED = "not_attempted"
    REMEDIATED = "remediated"
    FAILED = "failed"
    NEEDS_PERSON = "needs_person"

    @property
    def resolved(self) -> bool:
        """Whether the underlying problem is actually gone."""
        return self is RemediationStatus.REMEDIATED

    @property
    def needs_action(self) -> bool:
        """Whether somebody still has to do something about this."""
        return self is not RemediationStatus.REMEDIATED


@dataclass(frozen=True, slots=True)
class Location:
    """Where in the document a finding applies.

    Every field is optional because conditions differ in how precisely they can
    be attributed: a missing document language belongs to the catalogue, while a
    figure without alternate text belongs to one structure element on one page.
    """

    page: int | None = None
    object_number: int | None = None
    struct_path: str | None = None
    bbox: tuple[float, float, float, float] | None = None

    def describe(self) -> str:
        parts: list[str] = []
        if self.page is not None:
            parts.append(f"page {self.page + 1}")
        if self.struct_path:
            parts.append(self.struct_path)
        if self.object_number is not None:
            parts.append(f"object {self.object_number}")
        return ", ".join(parts) if parts else "document"


@dataclass(frozen=True, slots=True)
class Finding:
    """A single conformance problem detected in a document."""

    condition: str
    """Matterhorn failure condition, for example ``13-004``."""

    message: str
    """What is wrong, in terms a reader of the report can act on."""

    severity: Severity = Severity.ERROR
    location: Location = field(default_factory=Location)
    remedy: str | None = None
    """How to fix it, when there is a concrete answer."""

    context: dict[str, Any] = field(default_factory=dict)

    remediation: RemediationStatus = RemediationStatus.NOT_ATTEMPTED
    """What a repair attempt did about this, if one ran."""

    remediation_detail: str | None = None
    """Why a repair failed, or what it changed. Required reading when it failed."""

    @property
    def checkpoint(self) -> str:
        return self.condition.split("-", 1)[0]

    def as_remediated(self, detail: str | None = None) -> Finding:
        """This finding, marked as repaired."""
        return replace(self, remediation=RemediationStatus.REMEDIATED, remediation_detail=detail)

    def as_failed(self, detail: str) -> Finding:
        """This finding, marked as a repair that was attempted and did not work.

        ``detail`` is not optional. A failed repair with no reason recorded is
        indistinguishable from one nobody has looked at, which defeats the
        purpose of separating the two.
        """
        return replace(self, remediation=RemediationStatus.FAILED, remediation_detail=detail)

    def as_needing_a_person(self, detail: str | None = None) -> Finding:
        """This finding, marked as something automation should not decide."""
        return replace(self, remediation=RemediationStatus.NEEDS_PERSON, remediation_detail=detail)


@dataclass(frozen=True, slots=True)
class RuleMetadata:
    """Static description of a conformance rule."""

    condition: str
    checkpoint_name: str
    summary: str
    clause: str | None = None
    """Clause of ISO 14289-1 the condition derives from."""

    wcag: tuple[str, ...] = ()
    """Related WCAG 2.1 success criteria, for cross-referencing."""

    determination: Determination = Determination.SOFTWARE
    default_severity: Severity = Severity.ERROR

    @property
    def checkpoint(self) -> str:
        return self.condition.split("-", 1)[0]


@dataclass
class Report:
    """The outcome of auditing one document."""

    document: str
    findings: list[Finding] = field(default_factory=list)
    rules_run: int = 0
    rules_errored: dict[str, str] = field(default_factory=dict)
    """Rules that raised, mapped to the error text.

    A rule that crashes is recorded rather than swallowed. Reporting a document
    as clean because the check failed to run is the worst possible outcome for
    an accessibility tool.
    """

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.severity is Severity.ERROR]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.severity is Severity.WARNING]

    @property
    def reviews(self) -> list[Finding]:
        return [f for f in self.findings if f.severity is Severity.REVIEW]

    @property
    def remediated(self) -> list[Finding]:
        """Findings a repair actually cleared."""
        return [f for f in self.findings if f.remediation.resolved]

    @property
    def failed_remediations(self) -> list[Finding]:
        """Findings a repair tried and could not clear.

        Reported separately from the untouched ones because they are the
        interesting set: the document resisted a fix that was expected to work.
        """
        return [f for f in self.findings if f.remediation is RemediationStatus.FAILED]

    @property
    def outstanding(self) -> list[Finding]:
        """Everything still requiring somebody's attention."""
        return [f for f in self.findings if f.remediation.needs_action]

    def remediation_summary(self) -> dict[str, int]:
        """Count of findings by repair status, for a report header.

        Every status appears, including the zeroes. A summary that omits
        ``failed`` when the count is zero cannot be distinguished from one
        produced before the field existed.
        """
        counts = dict.fromkeys((status.value for status in RemediationStatus), 0)
        for finding in self.findings:
            counts[finding.remediation.value] += 1
        return counts

    @property
    def conformant(self) -> bool:
        """True when nothing blocks conformance and every rule actually ran.

        Repair status deliberately does not enter into this. Conformance is a
        property of the document as it now stands, and a finding marked
        remediated is one that should no longer be reported as an error at all.
        A remediated error that still counts against conformance means the
        repair did not work and the status is wrong.
        """
        return not self.errors and not self.rules_errored

    def by_checkpoint(self) -> dict[str, list[Finding]]:
        grouped: dict[str, list[Finding]] = {}
        for finding in self.findings:
            grouped.setdefault(finding.checkpoint, []).append(finding)
        return dict(sorted(grouped.items()))


__all__ = [
    "Determination",
    "Finding",
    "Location",
    "RemediationStatus",
    "Report",
    "RuleMetadata",
    "Severity",
]
