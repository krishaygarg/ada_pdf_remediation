"""Alternate text providers for figures.

This package defines the interface and the honest default. It deliberately does
not implement a description model: that is the subject of
``docs/planning/alt_text_research_spec.md`` and belongs to the research track.
What is provided here is the seam that work plugs into, so an implementation
can be dropped in without touching the pipeline.

The default provider does not invent descriptions. It marks each figure as
needing a human, which the audit then reports. A placeholder that reads
"Image" satisfies a conformance checker and tells a reader nothing, and it is
worse than an honest gap because it hides the work still to be done.
"""

from __future__ import annotations

from .base import (
    OTHER_MARKER,
    TARGET_MARKER,
    AltTextProvider,
    AltTextResult,
    FigureContext,
    PageSpan,
)
from .registry import available_providers, get_provider, register_provider
from .review import NeedsReviewProvider

__all__ = [
    "OTHER_MARKER",
    "TARGET_MARKER",
    "AltTextProvider",
    "AltTextResult",
    "FigureContext",
    "NeedsReviewProvider",
    "PageSpan",
    "available_providers",
    "get_provider",
    "register_provider",
]
