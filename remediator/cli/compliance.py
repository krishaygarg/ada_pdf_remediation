"""``check-compliance`` console script."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

DEFAULT_TARGET = "samples/physics/physics.pdf"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="check-compliance",
        description=(
            "Audit a PDF against PDF/UA-1 (ISO 14289-1) using the Matterhorn "
            "Protocol failure conditions. Runs locally by default; remote "
            "auditing uploads the file to a third party and must be requested."
        ),
    )
    parser.add_argument(
        "pdf_path",
        nargs="?",
        default=DEFAULT_TARGET,
        help=f"PDF to audit (default: {DEFAULT_TARGET})",
    )
    parser.add_argument(
        "-f",
        "--format",
        choices=("text", "json", "sarif", "junit"),
        default="text",
        help="Report format. sarif annotates a pull request diff on GitHub.",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Write the report to a file instead of standard output",
    )
    parser.add_argument(
        "--only",
        metavar="ID",
        action="append",
        help=("Restrict the audit to a condition (13-004) or a whole checkpoint (13). Repeatable."),
    )
    parser.add_argument(
        "--skip",
        metavar="ID",
        action="append",
        help="Skip a condition or checkpoint. Repeatable.",
    )
    parser.add_argument(
        "--contrast",
        action="store_true",
        help=(
            "Also measure text contrast (Matterhorn checkpoint 04). This renders "
            "every page, so it is slower than the rest of the audit and is off "
            "by default."
        ),
    )
    parser.add_argument(
        "--warnings-as-errors",
        action="store_true",
        help="Exit non-zero when the audit reports warnings as well as errors",
    )
    parser.add_argument(
        "--list-rules",
        action="store_true",
        help="Print the implemented rules and exit",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Suppress the report body and print only the verdict",
    )
    parser.add_argument("--json", action="store_true", help="Shorthand for --format json")

    remote = parser.add_argument_group("remote auditing")
    remote.add_argument(
        "--remote",
        action="store_true",
        help=(
            "Audit with the axesCheck service instead of the local engine. "
            "This uploads the document to check.axes4.com and requires "
            "--consent-upload."
        ),
    )
    remote.add_argument(
        "--consent-upload",
        action="store_true",
        help="Confirm that uploading the document to a third party is acceptable",
    )
    parser.add_argument(
        "--local",
        action="store_true",
        help="Deprecated no-op retained for compatibility; local is the default",
    )
    return parser


def _emit(payload: dict[str, Any], as_json: bool, message: str) -> None:
    print(json.dumps(payload, indent=2) if as_json else message)


def _list_rules() -> int:
    from ..audit import coverage_summary, rule_catalogue

    current = None
    for metadata in rule_catalogue():
        if metadata.checkpoint != current:
            current = metadata.checkpoint
            print(f"\nCheckpoint {current} - {metadata.checkpoint_name}")
        clause = f"  ISO {metadata.clause}" if metadata.clause else ""
        wcag = f"  WCAG {', '.join(metadata.wcag)}" if metadata.wcag else ""
        print(f"  {metadata.condition}  {metadata.summary}{clause}{wcag}")

    summary = coverage_summary()
    print(
        f"\n{summary['implemented_conditions']} conditions implemented across "
        f"{summary['implemented_checkpoints']} of {summary['protocol_checkpoints']} "
        "Matterhorn checkpoints."
    )
    print(
        f"The protocol defines {summary['protocol_conditions']} failure conditions, "
        f"{summary['protocol_software_conditions']} of them determinable by software."
    )
    return 0


def _run_remote(args: argparse.Namespace) -> int:
    from ..axescheck import audit_pdf_axescheck

    if not args.quiet and args.format == "text":
        print(f"Uploading {args.pdf_path} to check.axes4.com ...")

    result = audit_pdf_axescheck(args.pdf_path)
    if args.format == "json":
        print(json.dumps(result, indent=2))
        return 0 if result.get("success") else 1

    if not result.get("success"):
        print(f"Remote audit failed: {result.get('error')}", file=sys.stderr)
        return 1

    body = result.get("report", {}).get("body", {})
    info = body.get("documentInformation", {})
    scores: dict[str, tuple[Any, int]] = {}
    for report in body.get("reports", []):
        errors = report.get("report", {}).get("value", {}).get("errorCount", 0)
        scores[str(report.get("type"))] = (report.get("uaIndex"), errors)

    print("=" * 78)
    print(f" axesCheck report: {Path(args.pdf_path).name}")
    print("=" * 78)
    print(f" Pages     : {info.get('pageCount')}")
    print(f" Title     : {info.get('title')}")
    print(f" Language  : {info.get('language')}")
    print(f" Tagged    : {'yes' if info.get('isTagged') else 'no'}")
    print("-" * 78)
    for name, (index, errors) in scores.items():
        print(f" {name:<16} score={index} errors={errors}")
    print("=" * 78)
    print(
        " A passing score is not by itself proof of accessibility. Run the local\n"
        " audit as well: it checks character mapping quality, which this service\n"
        " does not."
    )
    return 0 if all(errors == 0 for _, errors in scores.values()) else 1


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.json:
        args.format = "json"

    if args.list_rules:
        return _list_rules()

    if not Path(args.pdf_path).exists():
        _emit(
            {"success": False, "error": f"File not found: {args.pdf_path}"},
            args.format == "json",
            f"Error: file not found: {args.pdf_path}",
        )
        return 2

    if args.remote:
        if not args.consent_upload:
            _emit(
                {
                    "success": False,
                    "error": "--remote requires --consent-upload",
                    "detail": (
                        "Remote auditing transmits the document to check.axes4.com, "
                        "a third-party service. Pass --consent-upload to proceed."
                    ),
                },
                args.format == "json",
                (
                    "Refusing to upload without consent.\n"
                    "  --remote sends the document to check.axes4.com, a third-party\n"
                    "  service. Re-run with --consent-upload if that is acceptable,\n"
                    "  or drop --remote to audit locally."
                ),
            )
            return 2
        return _run_remote(args)

    from ..audit import audit_document
    from ..audit.reporters import render

    include = list(args.only) if args.only else None
    if args.contrast and include is None:
        from ..audit.registry import EXPENSIVE_CHECKPOINTS, registered_rules

        include = sorted(
            {condition.split("-", 1)[0] for condition in registered_rules()} | EXPENSIVE_CHECKPOINTS
        )
    elif args.contrast:
        include = [*(include or []), "04"]

    report = audit_document(args.pdf_path, include=include, exclude=args.skip)

    if args.quiet and args.format == "text":
        verdict = "conformant" if report.conformant else "not conformant"
        print(
            f"{Path(args.pdf_path).name}: {verdict} "
            f"({len(report.errors)} errors, {len(report.warnings)} warnings)"
        )
    else:
        rendered = render(report, args.format)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(rendered, encoding="utf-8")
            if args.format == "text":
                print(f"Report written to {args.output}")
        else:
            print(rendered)

    if not report.conformant:
        return 1
    if args.warnings_as_errors and report.warnings:
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover - module executed as a script
    raise SystemExit(main())
