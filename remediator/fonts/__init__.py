"""Font encoding recovery.

Turning a character code into the text it represents is the difference between
a document a screen reader can read and one it cannot. This package recovers
that mapping from whatever the document provides, in order of authority, and
declines to guess when nothing does.
"""

from __future__ import annotations

from .glyphnames import normalise_for_text_extraction, resolve_glyph_name
from .recovery import RecoveredMapping, Source, recover_mapping
from .tounicode import build_tounicode_cmap, parse_tounicode_cmap

__all__ = [
    "RecoveredMapping",
    "Source",
    "build_tounicode_cmap",
    "normalise_for_text_extraction",
    "parse_tounicode_cmap",
    "recover_mapping",
    "resolve_glyph_name",
]
