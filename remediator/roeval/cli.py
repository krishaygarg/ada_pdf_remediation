"""``ada-ro-bench`` console script."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ada-ro-bench",
        description=(
            "Compare reading order strategies against a benchmark. See "
            "docs/planning/layout_reading_order_proposal.md for the research this supports."
        ),
    )
    parser.add_argument("dataset", nargs="?", help="Path to a JSON Lines benchmark file")
    parser.add_argument(
        "-s",
        "--strategy",
        action="append",
        help="Strategy to run. Repeatable. Defaults to all registered strategies.",
    )
    parser.add_argument(
        "-f", "--format", choices=("markdown", "json"), default="markdown", help="Output format"
    )
    parser.add_argument("-o", "--output", type=Path, help="Write to a file instead of stdout")
    parser.add_argument(
        "--list-strategies", action="store_true", help="Print the registered strategies and exit"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    from .strategy import available

    if args.list_strategies:
        for name, strategy in sorted(available().items()):
            print(f"{name}\n    {getattr(strategy, 'description', '')}\n")
        return 0

    if not args.dataset:
        print(
            "A dataset is required. Use --list-strategies to see what can be run.", file=sys.stderr
        )
        return 2

    from .dataset import DatasetError, load_dataset
    from .runner import run_benchmark, to_json, to_markdown

    try:
        pages = load_dataset(args.dataset)
    except DatasetError as exc:
        print(f"Could not read the dataset: {exc}", file=sys.stderr)
        return 2

    names = args.strategy or sorted(available())
    results = run_benchmark(names, pages)
    rendered = (
        to_markdown(results, len(pages))
        if args.format == "markdown"
        else to_json(results, len(pages))
    )

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
        print(f"Written to {args.output}")
    else:
        print(rendered)

    return 1 if any(result.failures for result in results) else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
