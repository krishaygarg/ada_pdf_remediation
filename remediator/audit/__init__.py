"""PDF/UA-1 conformance auditing.

The audit is organised around the Matterhorn Protocol 1.1, which enumerates the
failure conditions that make a document non-conforming. Each rule names the
condition it implements, so a report points at a published clause rather than
at an opinion held by this codebase.

Coverage is partial and honest about it: :func:`coverage_summary` reports how
many conditions are implemented against how many the protocol defines.
"""

from __future__ import annotations

from .model import (
    Determination,
    Finding,
    Location,
    RemediationStatus,
    Report,
    RuleMetadata,
    Severity,
)
from .registry import audit_document, registered_rules, rule, rule_catalogue

#: Totals published in the Matterhorn Protocol 1.1.
MATTERHORN_CHECKPOINTS = 31
MATTERHORN_CONDITIONS = 136
MATTERHORN_SOFTWARE_CONDITIONS = 87
MATTERHORN_HUMAN_CONDITIONS = 47
MATTERHORN_UNTESTABLE_CONDITIONS = 2


def coverage_summary() -> dict[str, int]:
    """How much of the protocol this engine currently implements."""
    catalogue = rule_catalogue()
    checkpoints = {metadata.checkpoint for metadata in catalogue}
    return {
        "implemented_conditions": len(catalogue),
        "implemented_checkpoints": len(checkpoints),
        "protocol_conditions": MATTERHORN_CONDITIONS,
        "protocol_software_conditions": MATTERHORN_SOFTWARE_CONDITIONS,
        "protocol_checkpoints": MATTERHORN_CHECKPOINTS,
    }


__all__ = [
    "MATTERHORN_CHECKPOINTS",
    "MATTERHORN_CONDITIONS",
    "MATTERHORN_HUMAN_CONDITIONS",
    "MATTERHORN_SOFTWARE_CONDITIONS",
    "MATTERHORN_UNTESTABLE_CONDITIONS",
    "Determination",
    "Finding",
    "Location",
    "RemediationStatus",
    "Report",
    "RuleMetadata",
    "Severity",
    "audit_document",
    "coverage_summary",
    "registered_rules",
    "rule",
    "rule_catalogue",
]
