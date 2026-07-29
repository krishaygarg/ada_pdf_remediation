"""Machine readable report formats: JSON, SARIF and JUnit XML.

SARIF matters most of the three. GitHub renders SARIF findings inline on a pull
request, so a conformance regression appears next to the change that caused it
rather than in a log nobody opens.
"""

from __future__ import annotations

import json
from typing import Any
from xml.etree import ElementTree as ET

from ... import __version__
from ..model import Report, Severity
from ..registry import registered_rules

SARIF_SCHEMA = "https://json.schemastore.org/sarif-2.1.0.json"
TOOL_URI = "https://github.com/krishaygarg/ada_pdf_remediation"


def to_dict(report: Report) -> dict[str, Any]:
    """Plain data representation, suitable for an API response."""
    return {
        "document": report.document,
        "conformant": report.conformant,
        "rulesRun": report.rules_run,
        "rulesErrored": report.rules_errored,
        "counts": {
            "errors": len(report.errors),
            "warnings": len(report.warnings),
            "review": len(report.reviews),
        },
        # Reported alongside the severity counts rather than folded into them.
        # A consumer needs to tell "nobody has tried to fix this" from "a fix
        # was attempted and did not work", and severity answers neither.
        "remediation": report.remediation_summary(),
        "findings": [
            {
                "condition": finding.condition,
                "checkpoint": finding.checkpoint,
                "severity": finding.severity.value,
                "message": finding.message,
                "remedy": finding.remedy,
                "location": {
                    "page": finding.location.page,
                    "objectNumber": finding.location.object_number,
                    "structPath": finding.location.struct_path,
                    "bbox": list(finding.location.bbox) if finding.location.bbox else None,
                },
                "context": finding.context,
                "remediation": finding.remediation.value,
                "remediationDetail": finding.remediation_detail,
            }
            for finding in report.findings
        ],
    }


def to_json(report: Report, *, indent: int = 2) -> str:
    return json.dumps(to_dict(report), indent=indent)


def _artifact_uri(document: str) -> str:
    """The document's name, not the path it happened to be processed at.

    A SARIF file is uploaded to GitHub and kept, so an absolute path would
    publish the layout of whatever machine ran the audit, including scratch
    directory names and, in a service deployment, the job identifier.
    """
    from pathlib import Path

    return Path(document).name or document


def to_sarif(report: Report) -> str:
    """Render as SARIF 2.1.0 so findings annotate a pull request diff."""
    catalogue = registered_rules()
    used = sorted({finding.condition for finding in report.findings})

    rules: list[dict[str, Any]] = []
    for condition in used:
        entry = catalogue.get(condition)
        if entry is None:
            rules.append({"id": condition, "name": condition})
            continue
        metadata, _ = entry
        properties: dict[str, object] = {
            "checkpoint": metadata.checkpoint,
            "checkpointName": metadata.checkpoint_name,
            "determination": metadata.determination.value,
        }
        if metadata.clause:
            properties["isoClause"] = metadata.clause
        if metadata.wcag:
            properties["wcag"] = list(metadata.wcag)
            properties["tags"] = ["accessibility", *(f"wcag-{c}" for c in metadata.wcag)]
        else:
            properties["tags"] = ["accessibility"]
        rules.append(
            {
                "id": condition,
                "name": metadata.checkpoint_name.replace(" ", ""),
                "shortDescription": {"text": metadata.summary},
                "fullDescription": {
                    "text": (
                        f"Matterhorn Protocol failure condition {condition}"
                        + (f", ISO 14289-1 clause {metadata.clause}" if metadata.clause else "")
                    )
                },
                "defaultConfiguration": {"level": metadata.default_severity.sarif_level},
                "properties": properties,
            }
        )

    results: list[dict[str, Any]] = []
    for finding in report.findings:
        region: dict[str, object] = {}
        if finding.location.page is not None:
            # SARIF has no page concept, so the page number is carried as a
            # one-based line so it still surfaces in the interface.
            region["startLine"] = finding.location.page + 1
        result: dict[str, object] = {
            "ruleId": finding.condition,
            "level": finding.severity.sarif_level,
            "message": {
                "text": finding.message
                + (f" Suggested fix: {finding.remedy}" if finding.remedy else "")
            },
            "locations": [
                {
                    "physicalLocation": {
                        "artifactLocation": {"uri": _artifact_uri(report.document)},
                        **({"region": region} if region else {}),
                    }
                }
            ],
        }
        if finding.location.struct_path:
            result["partialFingerprints"] = {
                "structPath": f"{finding.condition}:{finding.location.struct_path}"
            }
        results.append(result)

    document = {
        "$schema": SARIF_SCHEMA,
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "ADA PDF Remediator",
                        "informationUri": TOOL_URI,
                        "version": __version__,
                        "rules": rules,
                    }
                },
                "results": results,
            }
        ],
    }
    return json.dumps(document, indent=2)


def to_junit(report: Report) -> str:
    """Render as JUnit XML, one test case per rule that produced findings."""
    grouped: dict[str, list[Any]] = {}
    for finding in report.findings:
        grouped.setdefault(finding.condition, []).append(finding)

    catalogue = registered_rules()
    suite = ET.Element(
        "testsuite",
        name="pdf-ua-conformance",
        tests=str(report.rules_run),
        failures=str(len({f.condition for f in report.errors})),
        errors=str(len(report.rules_errored)),
        skipped="0",
    )

    for condition, (metadata, _) in catalogue.items():
        case = ET.SubElement(
            suite,
            "testcase",
            classname=f"checkpoint-{metadata.checkpoint}",
            name=f"{condition} {metadata.summary}",
        )
        if condition in report.rules_errored:
            error = ET.SubElement(case, "error", message="the rule did not complete")
            error.text = report.rules_errored[condition]
            continue
        findings = grouped.get(condition, [])
        blocking = [f for f in findings if f.severity is Severity.ERROR]
        if blocking:
            failure = ET.SubElement(case, "failure", message=f"{len(blocking)} occurrence(s)")
            failure.text = "\n".join(f"{f.location.describe()}: {f.message}" for f in blocking)

    return ET.tostring(suite, encoding="unicode", xml_declaration=True)
