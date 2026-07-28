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

from .alttext import AltTextProvider, FigureContext, get_provider
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


def detect_image_figures(
    image_placements: Sequence[tuple[str, Box]],
    *,
    page_width: float,
    page_height: float,
    min_area_ratio: float = 0.0009,
) -> list[DetectedFigure]:
    """Select image placements large enough to carry meaning.

    Very small images are bullets, rules, spacers and tracking pixels. Tagging
    each as a figure fills the reading order with elements a reader must skip,
    which is its own accessibility problem.
    """
    threshold = page_width * page_height * min_area_ratio
    figures = [
        DetectedFigure(bbox=box, kind="image", xobject_name=name)
        for name, box in image_placements
        if box.area >= threshold
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


def describe_figures(
    figures: Sequence[DetectedFigure],
    *,
    page_index: int,
    page_width: float,
    page_height: float,
    page_text: str = "",
    provider: AltTextProvider | None = None,
) -> list[tuple[DetectedFigure, str | None, bool]]:
    """Ask a provider to describe each figure.

    Returns ``(figure, description, needs_human_review)`` triples. A description
    of ``None`` means the provider declined, which is recorded honestly rather
    than replaced with a placeholder.
    """
    engine = provider or get_provider()
    described = []
    for figure in figures:
        context = FigureContext(
            page_index=page_index,
            bbox=(figure.bbox.x0, figure.bbox.top, figure.bbox.x1, figure.bbox.bottom),
            page_width=page_width,
            page_height=page_height,
            nearby_text=page_text,
            kind=figure.kind,
        )
        result = engine.describe(context)
        described.append(
            (figure, result.text if result.usable else None, result.needs_human_review)
        )
    return described


__all__ = [
    "DetectedFigure",
    "build_figure_element",
    "describe_figures",
    "detect_image_figures",
    "detect_vector_figures",
]
