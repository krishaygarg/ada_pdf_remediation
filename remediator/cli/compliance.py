"""``check-compliance`` console script."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

DEFAULT_TARGET = "samples/physics/remediated_physics.pdf"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="check-compliance",
        description=(
            "Audit a PDF for WCAG 2.1 and PDF/UA-1 accessibility compliance via "
            "axesCheck and local checks."
        ),
    )
    parser.add_argument(
        "pdf_path",
        nargs="?",
        default=DEFAULT_TARGET,
        help=f"Path to the target PDF document to check (default: {DEFAULT_TARGET})",
    )
    parser.add_argument("--json", action="store_true", help="Output raw MCP JSON response format")
    parser.add_argument(
        "--local",
        action="store_true",
        help="Force local Matterhorn / PDF/UA-1 check instead of remote axesCheck API",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Suppress detailed console report output",
    )
    return parser


def _print_remote_report(pdf_path: str, report: dict) -> int:
    body = report.get("body", {})
    info = body.get("documentInformation", {})
    scores: dict[str, tuple[object, int]] = {}
    for entry in body.get("reports", []):
        errors = entry.get("report", {}).get("value", {}).get("errorCount", 0)
        scores[str(entry.get("type"))] = (entry.get("uaIndex"), errors)

    print("=" * 78)
    print(f" axesCheck accessibility report: {Path(pdf_path).name}")
    print("=" * 78)
    print(f" Pages     : {info.get('pageCount')}")
    print(f" Title     : {info.get('title')}")
    print(f" Language  : {info.get('language')}")
    print(f" Tagged    : {'yes' if info.get('isTagged') else 'no'}")
    print("-" * 78)
    for name, (index, errors) in scores.items():
        print(f" {name:<16} score={index} errors={errors}")
    print("=" * 78)
    return 0 if all(errors == 0 for _, errors in scores.values()) else 1


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if not Path(args.pdf_path).exists():
        message = f"File not found: {args.pdf_path}"
        print(
            json.dumps({"success": False, "error": message}) if args.json else f"Error: {message}"
        )
        return 2

    from ..compliance import run_compliance_check

    if args.local:
        return 0 if run_compliance_check(args.pdf_path, verbose=not args.quiet) else 1

    from ..axescheck import audit_pdf_axescheck

    if not args.quiet and not args.json:
        print(f"Submitting {args.pdf_path} to axesCheck API...")

    remote = audit_pdf_axescheck(args.pdf_path)
    if remote.get("success"):
        if args.json:
            print(json.dumps(remote, indent=2))
            return 0
        return _print_remote_report(args.pdf_path, remote.get("report", {}))

    if not args.quiet and not args.json:
        print(f"\n[INFO] Remote axesCheck API unreachable: {remote.get('error')}")
        print("[INFO] Falling back to local PDF/UA-1 compliance auditor...\n")
    return 0 if run_compliance_check(args.pdf_path, verbose=not args.quiet) else 1


if __name__ == "__main__":  # pragma: no cover - module executed as a script
    raise SystemExit(main())
