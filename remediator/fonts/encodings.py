"""Simple font encodings: character code to glyph name.

The four predefined encodings are derived from ``pdfminer.latin_enc``, which
carries the Adobe table of ``(glyph name, standard, mac, win, pdf)`` codes.
Deriving them beats transcribing four tables of 256 entries by hand, and beats
approximating them with Python codecs: ``StandardEncoding`` is not Latin-1, and
treating it as Latin-1 silently mistranslates quotes, dashes and fractions.
"""

from __future__ import annotations

from collections.abc import Iterable
from functools import cache

from pdfminer.latin_enc import ENCODING

#: Names accepted in a font dictionary's /Encoding or /BaseEncoding entry.
PREDEFINED_ENCODINGS = ("StandardEncoding", "WinAnsiEncoding", "MacRomanEncoding", "PDFDocEncoding")

_COLUMN = {
    "StandardEncoding": 1,
    "MacRomanEncoding": 2,
    "WinAnsiEncoding": 3,
    "PDFDocEncoding": 4,
}


@cache
def encoding_table(name: str) -> dict[int, str]:
    """Return ``{character code: glyph name}`` for a predefined encoding.

    An unknown name yields an empty table rather than raising, so a document
    naming a nonexistent encoding degrades to the other resolution steps
    instead of aborting the run.
    """
    column = _COLUMN.get(name.lstrip("/"))
    if column is None:
        return {}
    table: dict[int, str] = {}
    for row in ENCODING:
        glyph_name = row[0]
        code = row[column]
        if code is not None:
            table[int(code)] = str(glyph_name)
    return table


def apply_differences(base: dict[int, str], differences: Iterable[object]) -> dict[int, str]:
    """Overlay a PDF /Differences array onto a base encoding table.

    The array alternates a starting code with the glyph names that follow it,
    as described in ISO 32000-1 9.6.6.1. A malformed entry is skipped rather
    than aborting, because a partially recovered encoding is still far better
    than none.
    """
    table = dict(base)
    current = 0
    for item in differences:
        text = str(item)
        if text.startswith("/"):
            table[current] = text[1:]
            current += 1
            continue
        try:
            current = int(text)
        except ValueError:
            # A malformed entry loses the position of everything after it, so
            # the remaining names are skipped rather than assigned to codes
            # that would be wrong.
            continue
    return table


__all__ = ["PREDEFINED_ENCODINGS", "apply_differences", "encoding_table"]
