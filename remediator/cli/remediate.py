"""``remediate-pdf`` console script."""

from __future__ import annotations

import argparse
import sys
import traceback
from collections.abc import Sequence

from ..config import configure_workspace_tmp


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="remediate-pdf",
        description="Remediate a PDF document towards PDF/UA-1 and WCAG conformance.",
    )
    parser.add_argument("input_pdf", help="Path to the source PDF file")
    parser.add_argument("output_pdf", help="Destination path for the remediated PDF")
    parser.add_argument(
        "--traceback",
        action="store_true",
        help="Print the full Python traceback when remediation fails",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    # Imported lazily so that ``--help`` works without the heavier PDF stack.
    from ..pipeline import remediate_single_pdf

    try:
        with configure_workspace_tmp():
            remediate_single_pdf(args.input_pdf, args.output_pdf)
    except Exception as exc:
        if args.traceback:
            traceback.print_exc()
        print(f"Remediation failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover - module executed as a script
    raise SystemExit(main())
