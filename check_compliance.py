#!/usr/bin/env python3
"""
CLI entry point for running PDF accessibility compliance checks via axesCheck API / MCP tool.
"""

import sys
import json
import argparse
import os

from remediator.axescheck import audit_pdf_axescheck
from remediator.compliance import run_compliance_check


def main():
    parser = argparse.ArgumentParser(
        description="Audit a PDF for WCAG 2.1 & PDF/UA-1 accessibility compliance via axesCheck & local checks."
    )
    parser.add_argument(
        "pdf_path",
        nargs="?",
        default="samples/physics/remediated_physics.pdf",
        help="Path to the target PDF document to check (default: samples/physics/remediated_physics.pdf)"
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output raw MCP JSON response format"
    )
    parser.add_argument(
        "--local",
        action="store_true",
        help="Force local Matterhorn / PDF/UA-1 check instead of remote axesCheck API"
    )
    parser.add_argument(
        "-q", "--quiet",
        action="store_true",
        help="Suppress detailed console report output"
    )

    args = parser.parse_args()

    if not os.path.exists(args.pdf_path):
        print(json.dumps({"success": False, "error": f"File not found: {args.pdf_path}"}) if args.json else f"Error: File not found: {args.pdf_path}")
        sys.exit(1)

    if args.local:
        success = run_compliance_check(args.pdf_path, verbose=not args.quiet)
        sys.exit(0 if success else 1)

    # 1. Attempt axesCheck MCP remote audit
    if not args.quiet and not args.json:
        print(f"Submitting {args.pdf_path} to axesCheck API...")

    remote_res = audit_pdf_axescheck(args.pdf_path)

    if remote_res.get("success"):
        if args.json:
            print(json.dumps(remote_res, indent=2))
            sys.exit(0)

        report = remote_res.get("report", {})
        body = report.get("body", {})
        doc_info = body.get("documentInformation", {})
        reports = body.get("reports", [])

        ua_score = "N/A"
        wcag_score = "N/A"
        ua_errors = 0
        wcag_errors = 0

        for r in reports:
            if r.get("type") == "PDF/UA":
                ua_score = r.get("uaIndex")
                val = r.get("report", {}).get("value", {})
                ua_errors = val.get("errorCount", 0)
            elif r.get("type") == "WCAG2CheckSet":
                wcag_score = r.get("uaIndex")
                val = r.get("report", {}).get("value", {})
                wcag_errors = val.get("errorCount", 0)

        print("\n" + "=" * 80)
        print(f" OFFICIAL AXESCHECK ACCESSIBILITY AUDIT REPORT: {os.path.basename(args.pdf_path)}")
        print("=" * 80)
        print(f" Document Name      : {doc_info.get('name')}")
        print(f" Page Count         : {doc_info.get('pageCount')}")
        print(f" Document Title     : {doc_info.get('title')}")
        print(f" Document Language  : {doc_info.get('language')}")
        print(f" Tagged Status      : {'Yes' if doc_info.get('isTagged') else 'No'}")
        print("-" * 80)
        print(f" PDF/UA Compliance Score : {ua_score}% (Errors: {ua_errors})")
        print(f" WCAG 2.1 Score          : {wcag_score}% (Errors: {wcag_errors})")
        print("=" * 80)

        if str(ua_score) == "100" or ua_score == 100:
            print(" SUCCESS: Document is 100% compliant with PDF/UA-1 & WCAG standards!")
        else:
            print(f" COMPLIANCE SCORE: PDF/UA {ua_score}% | WCAG {wcag_score}%")
        print("=" * 80 + "\n")
        sys.exit(0 if (ua_errors == 0 and wcag_errors == 0) else 1)

    else:
        # Fallback to local check if axesCheck API fails or is unreachable
        if not args.quiet and not args.json:
            print(f"\n[INFO] Remote axesCheck API returned error/unreachable: {remote_res.get('error')}")
            print("[INFO] Falling back to local PDF/UA-1 compliance auditor...\n")
        success = run_compliance_check(args.pdf_path, verbose=not args.quiet)
        sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
