"""Detection and tagging of figures.

The README has long described figure detection with bounding boxes and
alternate text. It was not implemented: the list of regions was created empty
and never filled, and no ``/Figure`` element was ever produced. This module
supplies it.

Two kinds of region are recognised. An image XObject is unambiguous, because
the content stream names it. A cluster of vector drawing operations is a
judgement call, so it has to be large enough to be worth a reader's attention
and small enough not to be the page background.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import pikepdf

from .alttext import AltTextProvider, FigureContext, PageSpan, get_provider
from .geometry.boxes import Box, significant_regions

if TYPE_CHECKING:  # pragma: no cover - imported for annotations only
    from collections.abc import Sequence


@dataclass(frozen=True)
class DetectedFigure:
    """A region of the page that should be tagged as a figure."""

    bbox: Box
    kind: str
    """``image`` for an XObject, ``vector`` for a cluster of drawing operations."""

    xobject_name: str | None = None


#: An image smaller than this fraction of the page is a bullet, a rule, a
#: spacer or a tracking pixel. Tagging each as a figure fills the reading order
#: with elements a reader has to skip, which is its own accessibility problem.
IMAGE_AREA_THRESHOLD = 0.0009


def is_meaningful_image(
    box: Box, *, page_width: float, page_height: float, min_area_ratio: float = IMAGE_AREA_THRESHOLD
) -> bool:
    """Whether an image placement is large enough to be worth tagging."""
    return box.area >= page_width * page_height * min_area_ratio


def detect_image_figures(
    image_placements: Sequence[tuple[str, Box]],
    *,
    page_width: float,
    page_height: float,
    min_area_ratio: float = IMAGE_AREA_THRESHOLD,
) -> list[DetectedFigure]:
    """Select image placements large enough to carry meaning."""
    figures = [
        DetectedFigure(bbox=box, kind="image", xobject_name=name)
        for name, box in image_placements
        if is_meaningful_image(
            box, page_width=page_width, page_height=page_height, min_area_ratio=min_area_ratio
        )
    ]
    return sorted(figures, key=lambda figure: (figure.bbox.top, figure.bbox.x0))


def detect_vector_figures(
    path_boxes: Sequence[Box],
    *,
    page_width: float,
    page_height: float,
    exclude: Sequence[Box] = (),
) -> list[DetectedFigure]:
    """Cluster vector drawing into candidate figures.

    Regions already covered by a detected image are excluded, so a chart drawn
    on top of a background image is not reported twice.
    """
    regions = significant_regions(path_boxes, page_width=page_width, page_height=page_height)
    figures = []
    for region in regions:
        if any(covered.contains(region) for covered in exclude):
            continue
        figures.append(DetectedFigure(bbox=region, kind="vector"))
    return figures


def build_figure_element(
    pdf: pikepdf.Pdf,
    figure: DetectedFigure,
    *,
    parent: pikepdf.Object,
    page: pikepdf.Object,
    mcid: int,
    alt_text: str | None,
) -> pikepdf.Object:
    """Create a ``/Figure`` structure element for a detected region.

    ``/BBox`` goes inside an attribute dictionary owned by ``/Layout``, which is
    where ISO 32000-1 14.8.5.4.3 defines it. Placing it directly on the
    structure element, which is a common mistake, leaves it where no consumer
    looks for it.
    """
    element = pikepdf.Dictionary(
        Type=pikepdf.Name("/StructElem"),
        S=pikepdf.Name("/Figure"),
        P=parent,
        Pg=page,
        K=pikepdf.Integer(mcid),
        A=pikepdf.Dictionary(
            O=pikepdf.Name("/Layout"),
            BBox=pikepdf.Array(
                [
                    round(figure.bbox.x0, 3),
                    round(figure.bbox.top, 3),
                    round(figure.bbox.x1, 3),
                    round(figure.bbox.bottom, 3),
                ]
            ),
        ),
    )
    if alt_text:
        element["/Alt"] = pikepdf.String(alt_text)
    return pdf.make_indirect(element)


#: One entry awaiting interleaving: vertical position, a tie break placing text
#: before a figure at the same offset, the text, and the figure's index.
#: Declared at module scope rather than inside the function because
#: `from __future__ import annotations` leaves annotations unevaluated, so a
#: local alias used only in one is dead code at runtime.
_SortableItem = tuple[float, int, str, "int | None"]


def build_page_spans(
    text_lines: Sequence[tuple[str, float]],
    figures: Sequence[DetectedFigure],
) -> tuple[PageSpan, ...]:
    """Interleave text lines and figures into reading order by vertical position.

    ``text_lines`` is ``(text, top)`` pairs. Consecutive lines are merged into
    one span so a provider sees paragraphs rather than one span per line.

    Vertical position only, which is correct for a single column and wrong for
    two. Ordering a multi-column page is reading order recovery, which is the
    other research track's subject and deliberately not solved here. A provider
    that needs to know should compare span order against the page geometry
    rather than assume this is authoritative.
    """
    items: list[_SortableItem] = [(top, 0, text, None) for text, top in text_lines]
    items += [(figure.bbox.top, 1, "", index) for index, figure in enumerate(figures)]
    # Ties break towards the text, so a line level with a figure's top edge
    # reads as introducing it. The case that actually matters needs no tie
    # break: a caption sits below its image, so its top is the larger number
    # and it sorts after the figure on position alone.
    items.sort(key=lambda item: (item[0], item[1]))

    spans: list[PageSpan] = []
    pending: list[str] = []
    for _, _, text, figure_index in items:
        if figure_index is None:
            if text:
                pending.append(text)
            continue
        if pending:
            spans.append(PageSpan(text="\n".join(pending)))
            pending = []
        spans.append(PageSpan(figure_index=figure_index))
    if pending:
        spans.append(PageSpan(text="\n".join(pending)))
    return tuple(spans)


def describe_figures(
    figures: Sequence[DetectedFigure],
    *,
    page_index: int,
    page_width: float,
    page_height: float,
    page_text: str = "",
    text_lines: Sequence[tuple[str, float]] = (),
    page_figures: Sequence[DetectedFigure] | None = None,
    provider: AltTextProvider | None = None,
) -> list[tuple[DetectedFigure, str | None, bool]]:
    """Ask a provider to describe each figure.

    Returns ``(figure, description, needs_human_review)`` triples. A description
    of ``None`` means the provider declined, which is recorded honestly rather
    than replaced with a placeholder.

    ``page_figures`` is every figure on the page, which is what makes sibling
    context available when the caller describes figures one at a time. It
    defaults to ``figures``, so a caller passing a whole page gets the right
    answer without supplying it twice.
    """
    engine = provider or get_provider()
    on_page = list(page_figures) if page_figures is not None else list(figures)
    spans = build_page_spans(text_lines, on_page) if text_lines else ()

    described = []
    for figure in figures:
        index = _index_of(figure, on_page)
        siblings = tuple(
            (other.bbox.x0, other.bbox.top, other.bbox.x1, other.bbox.bottom)
            for position, other in enumerate(on_page)
            if position != index
        )
        context = FigureContext(
            page_index=page_index,
            bbox=(figure.bbox.x0, figure.bbox.top, figure.bbox.x1, figure.bbox.bottom),
            page_width=page_width,
            page_height=page_height,
            nearby_text=page_text,
            kind=figure.kind,
            figure_index=index,
            page_spans=spans,
            sibling_bboxes=siblings,
        )
        result = engine.describe(context)
        described.append(
            (figure, result.text if result.usable else None, result.needs_human_review)
        )
    return described


#: Smallest overlap, as a fraction of the smaller box, that identifies two
#: detections as the same region. Generous because the two sources of a
#: figure's geometry round differently; well below the point where adjacent
#: figures on a page could be confused for one another.
_SAME_REGION_OVERLAP = 0.5


def _index_of(figure: DetectedFigure, on_page: Sequence[DetectedFigure]) -> int | None:
    """Position of ``figure`` among the page's figures, or None if unidentifiable.

    Matched by overlap rather than equality. A caller that re-detects a region
    produces an equal figure and not the same object, and the coordinates
    frequently differ in the last decimal place because the two detections came
    through different libraries.

    Returns None rather than guessing. An earlier version returned 0 for an
    unmatched figure, which read as "this is the first figure on the page" and
    was wrong on every figure but the first: two figures both described
    themselves as figure 0 and received identical page context, which defeats
    the entire purpose of tracking the position. A caller that cannot be located
    must be told so.
    """
    best: tuple[float, int] | None = None
    for index, candidate in enumerate(on_page):
        if candidate.kind != figure.kind:
            continue
        overlap = _overlap_fraction(candidate.bbox, figure.bbox)
        if overlap >= _SAME_REGION_OVERLAP and (best is None or overlap > best[0]):
            best = (overlap, index)
    return None if best is None else best[1]


def _overlap_fraction(first: Box, second: Box) -> float:
    """Intersection area as a fraction of the smaller box's area."""
    width = min(first.x1, second.x1) - max(first.x0, second.x0)
    height = min(first.bottom, second.bottom) - max(first.top, second.top)
    if width <= 0 or height <= 0:
        return 0.0
    smaller = min(first.area, second.area)
    return (width * height) / smaller if smaller > 0 else 0.0


__all__ = [
    "IMAGE_AREA_THRESHOLD",
    "DetectedFigure",
    "build_figure_element",
    "build_page_spans",
    "describe_figures",
    "detect_image_figures",
    "detect_vector_figures",
    "is_meaningful_image",
]
