"""The default provider, which declines to describe and says so."""

from __future__ import annotations

import re

from .base import AltTextResult, FigureContext

#: A caption line usually begins with a label of this shape.
_CAPTION_PREFIX = re.compile(
    r"^\s*(figure|fig\.?|table|chart|plate|scheme|equation|eq\.?)\s*[\d.]*\s*[:.)-]?\s+",
    re.IGNORECASE,
)


class NeedsReviewProvider:
    """Marks every figure as requiring a human description.

    Two things it will do, because both are evidence rather than invention:

    It reuses a caption when the document already contains one. A caption is
    the author's own description of the figure, so promoting it is reporting
    what the document says, not guessing.

    It records the region's position and size in the notes, which gives a
    reviewer enough to find the figure without opening a tagging tool.

    What it will not do is emit "Image" or "Figure 1" as a description. That
    satisfies a conformance checker while telling a reader nothing, and it
    conceals the work that still has to happen.
    """

    name = "needs-review"

    def describe(self, figure: FigureContext) -> AltTextResult:
        caption = self._caption(figure)
        if caption:
            return AltTextResult(
                text=caption,
                confidence=0.5,
                needs_human_review=True,
                provider=self.name,
                notes=(
                    "Taken from the caption in the document. A caption names a "
                    "figure; it may not describe what the figure shows."
                ),
            )

        x0, top, x1, bottom = figure.bbox
        return AltTextResult(
            text=None,
            confidence=0.0,
            needs_human_review=True,
            provider=self.name,
            notes=(
                f"No description available. {figure.kind} region on page "
                f"{figure.page_index + 1}, {x1 - x0:.0f} by {bottom - top:.0f} points "
                f"at ({x0:.0f}, {top:.0f})."
            ),
        )

    @staticmethod
    def _caption(figure: FigureContext) -> str | None:
        candidate = (figure.caption or "").strip()
        if not candidate:
            for line in figure.nearby_text.splitlines():
                if _CAPTION_PREFIX.match(line):
                    candidate = line.strip()
                    break
        if not candidate:
            return None
        # A bare label such as "Figure 3." is not a description.
        without_label = _CAPTION_PREFIX.sub("", candidate).strip()
        if len(without_label) < 8:
            return None
        return candidate


__all__ = ["NeedsReviewProvider"]
