"""Reading order strategies and their registry.

A strategy takes the elements found on a page and returns them in the order a
person would read them. This module defines that contract and the registry that
lets one be selected by name; it deliberately implements no ordering algorithm
beyond the identity baseline.

The algorithms are the subject of ``docs/planning/layout_reading_order_proposal.md``
and belong to the people working on that specification. What is here is the
socket they plug into, so an implementation can be benchmarked, compared and
switched on in the pipeline without touching any of this.

Two ways to register. Inside the repository, decorate a callable with
:func:`register`. From a separate distribution, declare an entry point in the
``ada_pdf_remediator.reading_order`` group, which means an experiment can live
in its own package and still be selected by name here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:  # pragma: no cover - imported for annotations only
    from collections.abc import Callable, Sequence

ENTRY_POINT_GROUP = "ada_pdf_remediator.reading_order"


@dataclass(frozen=True, slots=True)
class PageElement:
    """One element on a page, as the sorter sees it.

    The schema matches the one described in the research specification, so data
    prepared for that work can be fed straight in.
    """

    id: int
    type: str
    """A structure type such as ``P``, ``H1``, ``Figure`` or ``Table``."""

    bbox: tuple[float, float, float, float]
    """``(x0, top, x1, bottom)`` in PDF user space."""

    text: str = ""
    mcids: tuple[int, ...] = ()
    page_index: int = 0
    attributes: dict[str, Any] = field(default_factory=dict)

    @property
    def width(self) -> float:
        return self.bbox[2] - self.bbox[0]

    @property
    def height(self) -> float:
        return self.bbox[3] - self.bbox[1]

    @property
    def centre(self) -> tuple[float, float]:
        return ((self.bbox[0] + self.bbox[2]) / 2, (self.bbox[1] + self.bbox[3]) / 2)


@runtime_checkable
class ReadingOrderStrategy(Protocol):
    """Orders the elements of a page.

    An implementation must return the same elements it was given, reordered.
    Adding, dropping or altering elements would change the document rather than
    describe it, and :func:`validate_ordering` enforces that in the harness.
    """

    name: str
    description: str

    def sort(
        self, elements: Sequence[PageElement], page_image_path: str | None = None
    ) -> list[PageElement]: ...


_REGISTRY: dict[str, ReadingOrderStrategy] = {}
_ENTRY_POINTS_LOADED = False


def register(strategy: ReadingOrderStrategy, *, replace: bool = False) -> ReadingOrderStrategy:
    """Make ``strategy`` selectable by name."""
    if not getattr(strategy, "name", ""):
        raise ValueError("a strategy must declare a non-empty name")
    if strategy.name in _REGISTRY and not replace:
        raise ValueError(f"a strategy named {strategy.name!r} is already registered")
    _REGISTRY[strategy.name] = strategy
    return strategy


def _load_entry_points() -> None:
    global _ENTRY_POINTS_LOADED
    if _ENTRY_POINTS_LOADED:
        return
    _ENTRY_POINTS_LOADED = True
    from importlib.metadata import entry_points

    for entry in entry_points(group=ENTRY_POINT_GROUP):
        try:
            candidate = entry.load()
            register(candidate() if isinstance(candidate, type) else candidate, replace=True)
        except Exception:
            # A third-party strategy that fails to import is simply absent from
            # the list. It must not prevent the others from being used.
            continue


def available() -> dict[str, ReadingOrderStrategy]:
    """Every registered strategy, keyed by name."""
    _ensure_builtins()
    _load_entry_points()
    return dict(_REGISTRY)


def get(name: str) -> ReadingOrderStrategy:
    """Return a strategy by name."""
    strategies = available()
    try:
        return strategies[name]
    except KeyError:
        known = ", ".join(sorted(strategies)) or "none"
        raise LookupError(f"no reading order strategy named {name!r}; known: {known}") from None


def _ensure_builtins() -> None:
    if "stream-order" not in _REGISTRY:
        from . import adapters

        adapters.register_all()


def validate_ordering(original: Sequence[PageElement], produced: Sequence[PageElement]) -> None:
    """Check that a strategy reordered the elements rather than changing them.

    Raises:
        ValueError: If any element was added, dropped or duplicated.
    """
    if len(original) != len(produced):
        raise ValueError(
            f"the strategy returned {len(produced)} elements for an input of {len(original)}"
        )
    before = sorted(element.id for element in original)
    after = sorted(element.id for element in produced)
    if before != after:
        missing = sorted(set(before) - set(after))
        extra = sorted(set(after) - set(before))
        raise ValueError(
            f"the strategy changed the element set; missing={missing} unexpected={extra}"
        )


def as_strategy(
    name: str, description: str, function: Callable[..., list[PageElement]]
) -> ReadingOrderStrategy:
    """Wrap a plain function as a strategy object."""

    class _Wrapped:
        def __init__(self) -> None:
            self.name = name
            self.description = description

        def sort(
            self, elements: Sequence[PageElement], page_image_path: str | None = None
        ) -> list[PageElement]:
            return function(elements, page_image_path)

    return _Wrapped()


__all__ = [
    "ENTRY_POINT_GROUP",
    "PageElement",
    "ReadingOrderStrategy",
    "as_strategy",
    "available",
    "get",
    "register",
    "validate_ordering",
]
