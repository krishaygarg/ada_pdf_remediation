"""Resolution of glyph names to the text they represent.

Order matters. The Adobe Glyph List is authoritative where it applies; the
algorithmic conventions (``uni0041``, ``u1F600``) are next; then producer
specific patterns. A name that resolves to nothing returns ``None`` rather than
a placeholder, because a wrong character is worse than a missing one: a reader
can tell that something is absent, but cannot tell that ``{`` was meant to be
an en dash.
"""

from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

from pdfminer.glyphlist import glyphname2unicode

_UNI_PATTERN = re.compile(r"^uni([0-9A-Fa-f]{4})((?:[0-9A-Fa-f]{4})*)$")
_U_PATTERN = re.compile(r"^u([0-9A-Fa-f]{4,6})$")
_INDEXED_PATTERN = re.compile(r"^(?:g|cid|glyph|index|G)(\d+)$")

#: Names used by TeX's Computer Modern and related families that the Adobe
#: Glyph List does not carry. Values are the text a reader should receive.
#: Combining marks are given their Unicode combining code point so the text
#: still composes correctly when extracted.
TEX_SUPPLEMENT: dict[str, str] = {
    "vector": "⃗",  # combining right arrow above
    "arrowvert": "∣",
    "arrowdblvert": "∥",
    "braceex": "⎪",
    "bracketleftex": "⎢",
    "bracketrightex": "⎥",
    "parenleftex": "⎜",
    "parenrightex": "⎟",
    "circumflexbig": "̂",
    "tildebig": "̃",
    "epsilon1": "ε",
    "phi1": "ϕ",
    "rho1": "ϱ",
    "theta1": "ϑ",
    "pi1": "ϖ",
    "sigma1": "ς",
    "kappa1": "ϰ",
    "dotlessj": "ȷ",
    "lscript": "ℓ",
    "star": "⋆",
    "negationslash": "̸",
    "hatwide": "̂",
    "tildewide": "̃",
    "braceleftbig": "{",
    "bracerightbig": "}",
}

#: Ligature glyphs decomposed into the letters they stand for. Extracting "ffi"
#: rather than U+FB03 keeps the text searchable, which is the behaviour a reader
#: expects when they search for "office".
LIGATURES: dict[str, str] = {
    "ff": "ff",
    "fi": "fi",
    "fl": "fl",
    "ffi": "ffi",
    "ffl": "ffl",
    "ft": "ft",
    "st": "st",
    "IJ": "IJ",
    "ij": "ij",
}


@lru_cache(maxsize=8192)
def resolve_glyph_name(name: str) -> str | None:
    """Return the text a glyph name stands for, or ``None`` if unknown.

    Args:
        name: A PostScript glyph name, with or without a leading slash.
    """
    if not name:
        return None
    name = name.lstrip("/")

    # A suffix after a period marks a stylistic variant of the base glyph, as
    # in "a.sc" for small capital a. The base name carries the meaning.
    base = name.split(".", 1)[0] or name

    if base in LIGATURES:
        return LIGATURES[base]

    mapped = glyphname2unicode.get(base)
    if mapped:
        return mapped

    if base in TEX_SUPPLEMENT:
        return TEX_SUPPLEMENT[base]

    match = _UNI_PATTERN.match(base)
    if match:
        codes = [match.group(1), *re.findall(r"[0-9A-Fa-f]{4}", match.group(2) or "")]
        try:
            return "".join(chr(int(code, 16)) for code in codes)
        except ValueError:  # pragma: no cover - pattern guarantees valid hex
            return None

    match = _U_PATTERN.match(base)
    if match:
        try:
            value = int(match.group(1), 16)
        except ValueError:  # pragma: no cover - pattern guarantees valid hex
            return None
        if 0 <= value <= 0x10FFFF and not (0xD800 <= value <= 0xDFFF):
            return chr(value)
        return None

    # Names such as g42 or cid1234 identify a glyph by index within the font.
    # The index says nothing about meaning, so refusing is the honest answer.
    if _INDEXED_PATTERN.match(base):
        return None

    # A composite name joined by underscores, as produced by some subsetters
    # for ligatures: f_f_i.
    if "_" in base:
        parts = [resolve_glyph_name(part) for part in base.split("_")]
        if all(parts):
            return "".join(part for part in parts if part)

    return None


def normalise_for_text_extraction(value: str) -> str:
    """Decompose presentation forms so extracted text stays searchable.

    U+FB01 LATIN SMALL LIGATURE FI renders identically to "fi" but does not
    match a search for "fi". Compatibility decomposition resolves that, while
    leaving ordinary characters untouched.
    """
    if not value:
        return value
    decomposed = unicodedata.normalize("NFKC", value)
    if any(0xFB00 <= ord(character) <= 0xFB4F for character in decomposed):
        decomposed = unicodedata.normalize("NFKD", decomposed)
    return decomposed


__all__ = [
    "LIGATURES",
    "TEX_SUPPLEMENT",
    "normalise_for_text_extraction",
    "resolve_glyph_name",
]
