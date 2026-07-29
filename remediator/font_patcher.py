"""Generation of /ToUnicode character maps.

This module is a thin adapter. The recovery logic lives in
:mod:`remediator.fonts`, where each source of encoding information is handled
separately and records what it contributed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .fonts import RecoveredMapping, recover_mapping
from .fonts.tounicode import parse_tounicode_cmap  # re-exported for callers

if TYPE_CHECKING:  # pragma: no cover - imported for annotations only
    import pikepdf


def recover_font_mapping(font_obj: pikepdf.Object, font_name: str = "") -> RecoveredMapping:
    """Recover a font's character mapping, with provenance for each entry."""
    return recover_mapping(font_obj, font_name or None)


def generate_tounicode_cmap(
    font_obj: pikepdf.Object,
    font_name: str = "",
    input_path: str | None = None,
) -> str:
    """Return a /ToUnicode CMap program for ``font_obj``.

    Retained with its original signature so existing callers keep working.
    ``input_path`` is accepted and ignored: the mapping is derived from the font
    object itself, so re-reading the source document is unnecessary.

    Only codes that could be resolved appear in the result. A code the font uses
    but that no source explains is left out, so a consumer reports it as
    unmapped instead of receiving a character that was never in the document.
    """
    del input_path
    return recover_font_mapping(font_obj, font_name).to_cmap()


__all__ = [
    "generate_tounicode_cmap",
    "parse_tounicode_cmap",
    "recover_font_mapping",
]
