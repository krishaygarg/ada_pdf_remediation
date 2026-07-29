"""Reading order evaluation.

Scaffolding for the research described in
``docs/planning/layout_reading_order_proposal.md``: a strategy registry, a
benchmark dataset format, and a runner that produces a leaderboard.

It contains no ordering algorithm and no evaluation metric. Those are the
research, and they live in :mod:`remediator.reading_order`. Until they are
implemented every strategy ties with the baseline, which is the honest state
for the harness to report.
"""

from __future__ import annotations

from .dataset import BenchmarkPage, DatasetError, load_dataset, write_dataset
from .runner import StrategyResult, run_benchmark, run_strategy, to_json, to_markdown
from .strategy import (
    ENTRY_POINT_GROUP,
    PageElement,
    ReadingOrderStrategy,
    available,
    get,
    register,
    validate_ordering,
)

__all__ = [
    "ENTRY_POINT_GROUP",
    "BenchmarkPage",
    "DatasetError",
    "PageElement",
    "ReadingOrderStrategy",
    "StrategyResult",
    "available",
    "get",
    "load_dataset",
    "register",
    "run_benchmark",
    "run_strategy",
    "to_json",
    "to_markdown",
    "validate_ordering",
    "write_dataset",
]
