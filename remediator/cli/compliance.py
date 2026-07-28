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
            "Audit a PDF for PDF/UA-1 and WCAG 2.1 conformance. Runs locally by "
            "default; remote auditing uploads the file to a third party and must "
            "be requested explicitly."
        ),
    )
    parser.add_argument(
        "pdf_path",
        nargs="?",
        default=DEFAULT_TARGET,
        help=f"PDF to audit (default: {DEFAULT_TARGET})",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine readable JSON")
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Suppress the detailed console report",
    )
    remote = parser.add_argument_group("remote auditing")
    remote.add_argument(
        "--remote",
        action="store_true",
        help=(
            "Audit with the axesCheck service instead of the local auditor. "
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
    if as_json:
        print(json.dumps(payload, indent=2))
    else:
        print(message)


def _run_remote(args: argparse.Namespace) -> int:
    from ..axescheck import audit_pdf_axescheck

    if not args.quiet and not args.json:
        print(f"Uploading {args.pdf_path} to check.axes4.com ...")

    result = audit_pdf_axescheck(args.pdf_path)
    if args.json:
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
    return 0 if all(errors == 0 for _, errors in scores.values()) else 1


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if not Path(args.pdf_path).exists():
        _emit(
            {"success": False, "error": f"File not found: {args.pdf_path}"},
            args.json,
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
                args.json,
                (
                    "Refusing to upload without consent.\n"
                    "  --remote sends the document to check.axes4.com, a third-party\n"
                    "  service. Re-run with --consent-upload if that is acceptable,\n"
                    "  or drop --remote to audit locally."
                ),
            )
            return 2
        return _run_remote(args)

    from ..compliance import run_compliance_check

    passed = run_compliance_check(args.pdf_path, verbose=not (args.quiet or args.json))
    if args.json:
        print(json.dumps({"success": True, "compliant": passed, "mode": "local"}, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":  # pragma: no cover - module executed as a script
    raise SystemExit(main())
