"""The alternate text provider interface."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

#: Default marker for the figure being described, in :meth:`marked_page_text`.
TARGET_MARKER = "<FIGURE INTERESTED>"

#: Default marker for the other figures on the same page.
OTHER_MARKER = "<OTHER FIGURE>"


@dataclass(frozen=True, slots=True)
class PageSpan:
    """One run of page content, in reading order.

    Either a run of text or the position of a figure, never both. A page is
    modelled as a sequence of these so that a provider can see *where* in the
    text a figure sits rather than only what text is nearby.
    """

    text: str = ""
    figure_index: int | None = None
    """Set when this span is a figure rather than text."""

    @property
    def is_figure(self) -> bool:
        return self.figure_index is not None


@dataclass(frozen=True, slots=True)
class FigureContext:
    """Everything a provider is given about one figure.

    Deliberately more than an image. Surrounding text is often the single best
    predictor of a good description, because a caption usually already contains
    one, and a model that ignores it produces worse output than a caption match.

    On a page with more than one figure, nearby text alone is not enough. Two
    figures with a short paragraph between them share almost all of their
    nearby text, so a provider given only that will attach one caption to both
    and be equally confident in each. ``page_spans`` and ``figure_index`` exist
    to make that case answerable: they say which figure this is and what text
    falls before and after it, so the wrong caption is a decision rather than
    the only thing the interface allowed.
    """

    page_index: int
    bbox: tuple[float, float, float, float]
    page_width: float
    page_height: float
    image_bytes: bytes | None = None
    """A rendered crop of the region, when the caller could produce one."""

    image_format: str | None = None
    nearby_text: str = ""
    """Text immediately above and below the region, caption first if found."""

    caption: str | None = None
    kind: str = "unknown"
    """One of image, vector, table, formula or unknown, when it can be told."""

    metadata: dict[str, str] = field(default_factory=dict)

    figure_index: int | None = None
    """Which figure on the page this is, indexing into ``page_spans``.

    None when the caller could not place it. Not zero: an unplaceable figure
    that calls itself figure zero claims to be the first one on the page, which
    is wrong for every figure but the first and produces page context that
    points at a different figure's caption.
    """

    page_spans: tuple[PageSpan, ...] = ()
    """The whole page as text runs and figure positions, in reading order.

    Empty when the caller could not determine positions, in which case a
    provider has only ``nearby_text`` and should treat multi-figure pages as
    undescribable rather than guessing.

    Coordinates throughout are top-down, the order a reader meets the content,
    so the first span is the top of the page.
    """

    sibling_bboxes: tuple[tuple[float, float, float, float], ...] = ()
    """The other figure regions on this page, in the same order as the spans."""

    @property
    def page_text(self) -> str:
        """The page's text with the figures removed, in reading order."""
        return "\n".join(span.text for span in self.page_spans if not span.is_figure)

    @property
    def is_only_figure_on_page(self) -> bool:
        """True when nothing else on the page competes for the caption."""
        return not self.sibling_bboxes

    @property
    def has_page_context(self) -> bool:
        """Whether this figure's position within the page text is known."""
        return bool(self.page_spans) and self.figure_index is not None

    def marked_page_text(self, target: str = TARGET_MARKER, other: str = OTHER_MARKER) -> str:
        """The page text with this figure marked and the others distinguished.

        The convention follows the one ASUCICREPO/PDF_Accessibility arrived at
        after their crop-only version proved too weak: give the model the whole
        page, say which figure is the subject, and mark the rest so text
        belonging to a different figure can be ruled out. See
        docs/planning/alt_text_research_spec.md.

        Returns the empty string unless the position is known, which a caller
        must treat as "no page context" rather than "an empty page". Marking
        nothing is recoverable; marking the wrong figure is not, because the
        result is a confident description of a different image.
        """
        if not self.has_page_context:
            return ""
        parts = [
            (target if span.figure_index == self.figure_index else other)
            if span.is_figure
            else span.text
            for span in self.page_spans
        ]
        return "\n".join(part for part in parts if part)


@dataclass(frozen=True, slots=True)
class AltTextResult:
    """A provider's answer for one figure."""

    text: str | None
    """The description, or None when the provider declines to supply one."""

    confidence: float = 0.0
    """Between 0 and 1. Used to decide whether a human still needs to look."""

    needs_human_review: bool = True
    provider: str = "unknown"
    notes: str = ""

    @property
    def usable(self) -> bool:
        return bool(self.text and self.text.strip())


@runtime_checkable
class AltTextProvider(Protocol):
    """Produces alternate text for a figure.

    An implementation must be safe to call on a figure it cannot describe, and
    must return ``AltTextResult(text=None)`` in that case rather than inventing
    something. A wrong description is worse than a missing one: a reader can act
    on a gap but has no way to detect a confident fabrication.
    """

    name: str

    def describe(self, figure: FigureContext) -> AltTextResult:
        """Return a description for ``figure``, or decline."""


__all__ = [
    "OTHER_MARKER",
    "TARGET_MARKER",
    "AltTextProvider",
    "AltTextResult",
    "FigureContext",
    "PageSpan",
]
