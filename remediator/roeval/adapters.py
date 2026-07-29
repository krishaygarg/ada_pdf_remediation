"""Strategies the harness can run.

Each adapter is deliberately thin. It converts between the harness types and
whatever the underlying function expects, and nothing else. The ordering logic
lives in :mod:`remediator.reading_order`, which belongs to the research track
described in ``docs/planning/layout_reading_order_proposal.md``.

Until those functions are implemented they return their input unchanged, so
every adapter below scores identically to the baseline. That is the intended
state: the harness runs, reports honestly that nothing has improved on stream
order yet, and starts distinguishing the strategies the moment one of them
does something.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .strategy import PageElement, as_strategy, register

if TYPE_CHECKING:  # pragma: no cover - imported for annotations only
    from collections.abc import Callable, Sequence


def _stream_order(
    elements: Sequence[PageElement], page_image_path: str | None = None
) -> list[PageElement]:
    """Return the elements exactly as the content stream produced them.

    This is what the pipeline does today, and it is the baseline every other
    strategy has to beat. Without it in the table there is nothing to compare
    an improvement against, and a small gain over nothing looks impressive.
    """
    del page_image_path
    return list(elements)


def _to_dicts(elements: Sequence[PageElement]) -> list[dict[str, Any]]:
    """Convert to the dictionary schema the research functions accept."""
    return [
        {
            "id": element.id,
            "type": element.type,
            "text": element.text,
            "bbox": list(element.bbox),
            "mcids": list(element.mcids),
        }
        for element in elements
    ]


def _from_dicts(
    ordered: Sequence[dict[str, Any]], originals: Sequence[PageElement]
) -> list[PageElement]:
    """Map an ordered list of dictionaries back onto the original elements.

    Matching by identifier rather than trusting the returned dictionaries means
    a strategy cannot accidentally alter an element's geometry or text while
    reordering it.
    """
    by_id = {element.id: element for element in originals}
    result: list[PageElement] = []
    for entry in ordered:
        identifier = entry.get("id")
        if not isinstance(identifier, int):
            continue
        element = by_id.get(identifier)
        if element is not None:
            result.append(element)
    # Anything the strategy dropped is appended in its original order, so a
    # partial implementation degrades rather than losing content. The harness
    # still reports the discrepancy through validate_ordering.
    seen = {element.id for element in result}
    result.extend(element for element in originals if element.id not in seen)
    return result


def _wrap_research(function_name: str) -> Callable[..., list[PageElement]]:
    """Build an adapter around one of the research entry points."""

    def run(
        elements: Sequence[PageElement], page_image_path: str | None = None
    ) -> list[PageElement]:
        from .. import reading_order

        function = getattr(reading_order, function_name)
        if function_name == "zero_shot_vlm_align":
            ordered = function(page_image_path or "", _to_dicts(elements))
        else:
            ordered = function(_to_dicts(elements))
        return _from_dicts(ordered or [], elements)

    return run


def register_all() -> None:
    """Register the built-in strategies. Called once by the registry."""
    register(
        as_strategy(
            "stream-order",
            "The order the content stream produced, which is what the pipeline "
            "does today. The baseline every other strategy has to beat.",
            _stream_order,
        ),
        replace=True,
    )
    for name, description in (
        (
            "xy-cut",
            "Recursive XY-cut over the whitespace projection profile. "
            "Implemented by remediator.reading_order.heuristic_xy_cut.",
        ),
        (
            "llm-perplexity",
            "Flow sorting by the transition perplexity between adjacent blocks. "
            "Implemented by remediator.reading_order.unsupervised_llm_sort.",
        ),
        (
            "vlm-align",
            "Alignment of a visual transcription back onto the coordinates. "
            "Implemented by remediator.reading_order.zero_shot_vlm_align.",
        ),
    ):
        function_name = {
            "xy-cut": "heuristic_xy_cut",
            "llm-perplexity": "unsupervised_llm_sort",
            "vlm-align": "zero_shot_vlm_align",
        }[name]
        register(
            as_strategy(name, description, _wrap_research(function_name)),
            replace=True,
        )


__all__ = ["register_all"]
