#!/usr/bin/env python3
"""
CLI entry point for running PDF accessibility compliance checks.
"""

import sys
import argparse
from remediator.compliance import run_compliance_check


def main():
    parser = argparse.ArgumentParser(
        description="Audit a PDF for WCAG 2.1 & PDF/UA-1 accessibility compliance."
    )
    parser.add_argument(
        "pdf_path",
        nargs="?",
        default="samples/test_sample/remediated_test_sample.pdf",
        help="Path to the target PDF document to check (default: samples/test_sample/remediated_test_sample.pdf)"
    )
    parser.add_argument(
        "-q", "--quiet",
        action="store_true",
        help="Suppress detailed console report output"
    )

    args = parser.parse_args()
    success = run_compliance_check(args.pdf_path, verbose=not args.quiet)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
