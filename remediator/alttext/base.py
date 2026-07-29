"""The alternate text provider interface."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class FigureContext:
    """Everything a provider is given about one figure.

    Deliberately more than an image. Surrounding text is often the single best
    predictor of a good description, because a caption usually already contains
    one, and a model that ignores it produces worse output than a caption match.
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


__all__ = ["AltTextProvider", "AltTextResult", "FigureContext"]
