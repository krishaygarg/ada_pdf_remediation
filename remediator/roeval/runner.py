"""Running strategies over a benchmark and reporting the result.

Scoring calls ``remediator.reading_order.calculate_evaluation_metrics``, which
is Phase 2 of the research specification and is not implemented here. Until it
is, every strategy scores zero and the leaderboard says so explicitly rather
than displaying a column of zeros as though they meant something.

That is deliberate. The harness is inert by design: it exists so that the
moment someone implements a metric and an algorithm, they get a comparison
against a real baseline without building any of this first.

Wall time and peak memory are measured here rather than left to the metric,
because the specification sets a compute budget alongside the accuracy target
and a strategy that wins on ordering while needing eight gigabytes has not met
the brief.
"""

from __future__ import annotations

import json
import statistics
import time
import tracemalloc
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from .dataset import BenchmarkPage
from .strategy import PageElement, get, validate_ordering

if TYPE_CHECKING:  # pragma: no cover - imported for annotations only
    from collections.abc import Sequence


@dataclass
class PageResult:
    """What one strategy did with one page."""

    page_id: str
    metrics: dict[str, float]
    seconds: float
    peak_bytes: int
    exact_match: bool
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


@dataclass
class StrategyResult:
    """A strategy's performance across the whole benchmark."""

    strategy: str
    description: str
    pages: list[PageResult] = field(default_factory=list)

    @property
    def failures(self) -> list[PageResult]:
        return [page for page in self.pages if not page.ok]

    @property
    def exact_matches(self) -> int:
        return sum(1 for page in self.pages if page.exact_match)

    @property
    def total_seconds(self) -> float:
        return sum(page.seconds for page in self.pages)

    @property
    def peak_bytes(self) -> int:
        return max((page.peak_bytes for page in self.pages), default=0)

    def mean(self, metric: str) -> float:
        values = [page.metrics.get(metric, 0.0) for page in self.pages if page.ok]
        return statistics.fmean(values) if values else 0.0

    def metric_names(self) -> list[str]:
        names: list[str] = []
        for page in self.pages:
            for key in page.metrics:
                if key not in names:
                    names.append(key)
        return names


def _score(predicted: Sequence[PageElement], reference: Sequence[PageElement]) -> dict[str, float]:
    """Score a prediction using the project's evaluation metrics.

    The metrics themselves are Phase 2 of the research specification. This only
    calls them and coerces the result to floats.
    """
    from ..reading_order import calculate_evaluation_metrics

    raw = calculate_evaluation_metrics(
        [{"id": element.id, "text": element.text} for element in predicted],
        [{"id": element.id, "text": element.text} for element in reference],
    )
    scores: dict[str, float] = {}
    for key, value in (raw or {}).items():
        try:
            scores[str(key)] = float(value)
        except (TypeError, ValueError):
            continue
    return scores


def run_strategy(name: str, pages: Sequence[BenchmarkPage]) -> StrategyResult:
    """Run one strategy over every page of a benchmark."""
    strategy = get(name)
    result = StrategyResult(strategy=name, description=getattr(strategy, "description", ""))

    for page in pages:
        tracemalloc.start()
        started = time.perf_counter()
        error: str | None = None
        predicted: list[PageElement] = list(page.elements)
        try:
            predicted = strategy.sort(page.elements, page.page_image)
            validate_ordering(page.elements, predicted)
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
        seconds = time.perf_counter() - started
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        reference = page.reference_elements
        result.pages.append(
            PageResult(
                page_id=page.id,
                metrics={} if error else _score(predicted, reference),
                seconds=seconds,
                peak_bytes=peak,
                exact_match=(
                    not error
                    and [element.id for element in predicted]
                    == [element.id for element in reference]
                ),
                error=error,
            )
        )
    return result


def run_benchmark(names: Sequence[str], pages: Sequence[BenchmarkPage]) -> list[StrategyResult]:
    return [run_strategy(name, pages) for name in names]


def metrics_are_implemented(results: Sequence[StrategyResult]) -> bool:
    """Whether the evaluation metrics return anything other than zero.

    Used to decide whether the leaderboard is meaningful yet. A table of zeros
    presented without comment reads as a result rather than as an absence.
    """
    return any(
        value != 0.0
        for result in results
        for page in result.pages
        for value in page.metrics.values()
    )


def to_markdown(results: Sequence[StrategyResult], page_count: int) -> str:
    """Render a leaderboard, honest about what it does and does not know."""
    if not results:
        return "No strategies were run."

    metrics = sorted({name for result in results for name in result.metric_names()})
    header = [
        "Strategy",
        "Exact order",
        *[m.replace("_", " ") for m in metrics],
        "Time",
        "Peak memory",
    ]
    rows = [f"| {' | '.join(header)} |", f"|{'---|' * len(header)}"]

    ordered = sorted(
        results,
        key=lambda r: (-r.exact_matches, -sum(r.mean(m) for m in metrics), r.total_seconds),
    )
    for result in ordered:
        cells = [
            f"`{result.strategy}`",
            f"{result.exact_matches}/{page_count}",
            *[f"{result.mean(metric):.4f}" for metric in metrics],
            f"{result.total_seconds * 1000:.0f} ms",
            f"{result.peak_bytes / 1024:.0f} KiB",
        ]
        rows.append(f"| {' | '.join(cells)} |")

    lines = [f"### Reading order benchmark, {page_count} page(s)", "", *rows]

    if not metrics_are_implemented(results):
        lines += [
            "",
            "> Every metric reads zero because "
            "`remediator.reading_order.calculate_evaluation_metrics` still returns "
            "zeros. That is Phase 2 of the research specification. The exact order "
            "column is computed here and is meaningful now.",
        ]

    failing = [(r.strategy, page) for r in results for page in r.failures]
    if failing:
        lines += ["", "**Strategies that errored**", ""]
        lines += [f"- `{name}` on `{page.page_id}`: {page.error}" for name, page in failing[:10]]

    return "\n".join(lines)


def to_json(results: Sequence[StrategyResult], page_count: int) -> str:
    payload: dict[str, Any] = {
        "pages": page_count,
        "metricsImplemented": metrics_are_implemented(results),
        "strategies": [
            {
                "name": result.strategy,
                "description": result.description,
                "exactMatches": result.exact_matches,
                "totalSeconds": round(result.total_seconds, 6),
                "peakBytes": result.peak_bytes,
                "metrics": {name: result.mean(name) for name in result.metric_names()},
                "errors": [{"page": page.page_id, "error": page.error} for page in result.failures],
            }
            for result in results
        ],
    }
    return json.dumps(payload, indent=2)


__all__ = [
    "PageResult",
    "StrategyResult",
    "metrics_are_implemented",
    "run_benchmark",
    "run_strategy",
    "to_json",
    "to_markdown",
]
