#!/usr/bin/env python3
"""Generate the conformance rule catalogue from the registry.

Written rather than hand-maintained because a hand-maintained list of rules
drifts from the code within a release or two, and a documentation page that
disagrees with the tool is worse than none.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from remediator.audit import (
    MATTERHORN_CHECKPOINTS,
    MATTERHORN_CONDITIONS,
    MATTERHORN_HUMAN_CONDITIONS,
    MATTERHORN_SOFTWARE_CONDITIONS,
    Determination,
    coverage_summary,
    rule_catalogue,
)


def render() -> str:
    catalogue = rule_catalogue()
    summary = coverage_summary()

    lines = [
        "# Conformance rules",
        "",
        "Generated from the rule registry by `scripts/generate_rule_catalogue.py`.",
        "Do not edit by hand.",
        "",
        "## Coverage",
        "",
        f"The Matterhorn Protocol 1.1 defines **{MATTERHORN_CHECKPOINTS} checkpoints** and "
        f"**{MATTERHORN_CONDITIONS} failure conditions** for PDF/UA-1. Of those, "
        f"**{MATTERHORN_SOFTWARE_CONDITIONS}** can be determined by software, "
        f"{MATTERHORN_HUMAN_CONDITIONS} need human judgement, and 2 have no defined test.",
        "",
        f"This project implements **{summary['implemented_conditions']} conditions** across "
        f"**{summary['implemented_checkpoints']} of {MATTERHORN_CHECKPOINTS}** checkpoints.",
        "",
        (
            "Everything not listed below is unimplemented. See "
            "[CONTRIBUTING](../../CONTRIBUTING.md) for the backlog."
        ),
        "",
    ]

    grouped: dict[str, list] = {}
    for metadata in catalogue:
        grouped.setdefault(f"{metadata.checkpoint} {metadata.checkpoint_name}", []).append(metadata)

    for heading, rules in sorted(grouped.items()):
        lines += [f"## Checkpoint {heading}", ""]
        lines += [
            "| Condition | What it reports | ISO 14289-1 | WCAG | Determination |",
            "|---|---|---|---|---|",
        ]
        for rule in sorted(rules, key=lambda r: r.condition):
            wcag = ", ".join(rule.wcag) if rule.wcag else "not mapped"
            clause = rule.clause or "not stated"
            determination = (
                "software"
                if rule.determination is Determination.SOFTWARE
                else "human, automated here"
            )
            lines.append(
                f"| `{rule.condition}` | {rule.summary} | {clause} | {wcag} | {determination} |"
            )
        lines.append("")

    lines += [
        "## Severity",
        "",
        "| Level | Meaning |",
        "|---|---|",
        "| Error | The document does not conform. |",
        (
            "| Warning | It conforms, but a reader is likely to be obstructed. A figure "
            "described only as `image` is the usual case. |"
        ),
        "| Review | Software cannot settle it; a person has to look. |",
        "",
        (
            "A rule that raises is recorded rather than swallowed, and makes the report "
            "non-conformant. A check that failed to run must never look like a check that "
            "found nothing."
        ),
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "docs/reference/rules.md")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render(), encoding="utf-8")
    print(f"wrote {target}")
