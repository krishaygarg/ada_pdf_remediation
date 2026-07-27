#!/usr/bin/env python3
"""
CLI entry point for running the PDF accessibility remediation pipeline.
"""

import sys
import argparse
from remediator import remediate_single_pdf


def main():
    parser = argparse.ArgumentParser(
        description="Remediate a PDF document to make it WCAG & PDF/UA-1 accessible."
    )
    parser.add_argument(
        "input_pdf",
        help="Path to the input un-accessible PDF file"
    )
    parser.add_argument(
        "output_pdf",
        help="Destination path for the remediated accessible PDF file"
    )

    args = parser.parse_args()
    try:
        remediate_single_pdf(args.input_pdf, args.output_pdf)
    except Exception as e:
        print(f"\033[91mRemediation failed: {e}\033[0m", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
