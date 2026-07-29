"""Recovering the character code to text mapping of a font.

Sources are consulted in order of authority. Each records where its entries
came from, so a report can say why a code resolved the way it did, and so a
later source never overwrites a more authoritative one.

The rule that shapes the whole module: a code that cannot be resolved is left
out. The previous implementation filled every unmapped code in 0..255 with
``chr(code)`` where printable and a space otherwise. On the bundled sample that
turned the en dash at code 123 into an opening brace and the increment operator
at code 1 into a space, because Computer Modern does not use ASCII positions.
Extracted text became wrong rather than incomplete, and wrong text is not
recoverable by the reader.
"""

from __future__ import annotations

import enum
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .embedded import extract_builtin_encoding, extract_builtin_unicode
from .encodings import apply_differences, encoding_table
from .glyphnames import normalise_for_text_extraction, resolve_glyph_name
from .tounicode import build_tounicode_cmap, parse_tounicode_cmap

if TYPE_CHECKING:  # pragma: no cover - imported for annotations only
    import pikepdf

#: An unreadable source is not fatal here, because a later source may still
#: resolve the code and an unresolved code is reported rather than filled. The
#: reason is logged so that "nothing to recover" and "could not read it" stay
#: distinguishable, which is the distinction this module exists to preserve.
_LOG = logging.getLogger(__name__)


class Source(enum.Enum):
    """Where a mapping entry came from, most authoritative first."""

    EXISTING_TOUNICODE = "existing /ToUnicode"
    EMBEDDED_PROGRAM = "embedded font program"
    ENCODING_DIFFERENCES = "/Encoding /Differences"
    BASE_ENCODING = "predefined base encoding"


#: Consulted in this order; an earlier source is never overwritten by a later
#: one, which ``RecoveredMapping.add`` enforces by refusing to rewrite a code.
#:
#: Derived from the enum rather than restated, because a second hand-written
#: ordering is one that can disagree with the first without anything failing.
SOURCE_PRIORITY = tuple(Source)


@dataclass
class RecoveredMapping:
    """The outcome of recovering one font's character mapping."""

    font_name: str
    composite: bool
    mapping: dict[int, str] = field(default_factory=dict)
    provenance: dict[int, Source] = field(default_factory=dict)
    unresolved_glyphs: dict[int, str] = field(default_factory=dict)
    """Codes whose glyph name was found but could not be resolved to text."""

    def add(self, code: int, text: str, source: Source) -> None:
        if not text or code in self.mapping:
            return
        self.mapping[code] = normalise_for_text_extraction(text)
        self.provenance[code] = source

    @property
    def resolved_count(self) -> int:
        return len(self.mapping)

    def counts_by_source(self) -> dict[str, int]:
        """How many codes each source resolved, most authoritative source first.

        Ordered by ``SOURCE_PRIORITY`` rather than by whichever source happened
        to resolve a code first, so two runs over the same font produce the same
        report and a reader can see at a glance how much of the mapping rests on
        the weakest source.
        """
        counts: dict[str, int] = {}
        for source in self.provenance.values():
            counts[source.value] = counts.get(source.value, 0) + 1
        return {
            source.value: counts[source.value]
            for source in SOURCE_PRIORITY
            if source.value in counts
        }

    def to_cmap(self) -> str:
        return build_tounicode_cmap(
            self.mapping, composite=self.composite, font_name=self.font_name
        )


def _is_composite(font: pikepdf.Object) -> bool:
    return str(font.get("/Subtype", "")) == "/Type0"


def _base_encoding_name(font: pikepdf.Object, composite: bool) -> str | None:
    """The predefined encoding to fall back on, if any is appropriate.

    A symbolic font must not be given a text encoding: its codes address glyphs
    that have nothing to do with Latin letters. Guessing one is the mistake that
    produced ``Sept 10{11`` from ``Sept 10-11``.
    """
    if composite:
        return None

    encoding = font.get("/Encoding")
    if encoding is not None:
        text = str(encoding)
        if text.startswith("/") and text.endswith("Encoding"):
            return text.lstrip("/")
        base = encoding.get("/BaseEncoding") if hasattr(encoding, "get") else None
        if base is not None:
            return str(base).lstrip("/")

    descriptor = font.get("/FontDescriptor")
    if descriptor is not None:
        try:
            flags = int(descriptor.get("/Flags", 0))
        except (TypeError, ValueError):
            flags = 0
        # Bit 3 (value 4) marks the font symbolic, bit 6 (value 32) nonsymbolic.
        if flags & 4 and not flags & 32:
            return None

    return "StandardEncoding"


def recover_mapping(font: pikepdf.Object, font_name: str | None = None) -> RecoveredMapping:
    """Recover as much of a font's character mapping as the document supports."""
    name = font_name or str(font.get("/BaseFont", "Unnamed")).lstrip("/")
    composite = _is_composite(font)
    result = RecoveredMapping(font_name=name, composite=composite)

    # 1. An existing map is the producer's own statement of intent.
    existing = font.get("/ToUnicode")
    if existing is not None and hasattr(existing, "read_bytes"):
        try:
            for code, text in parse_tounicode_cmap(bytes(existing.read_bytes())).items():
                # A previous run of this tool may have written spaces over the
                # whole range. Those entries carry no information and must not
                # be treated as authoritative.
                if text.strip() or text == " ":
                    if text == " ":
                        continue
                    result.add(code, text, Source.EXISTING_TOUNICODE)
        except Exception:
            _LOG.debug(
                "could not parse the existing /ToUnicode for %s; falling through to the "
                "font's own encoding",
                name,
                exc_info=True,
            )

    # 2. The embedded program, which is the only source for a symbolic font.
    descendant = font
    if composite:
        descendants = font.get("/DescendantFonts")
        if descendants is not None and len(descendants) > 0:
            descendant = descendants[0]

    for code, text in extract_builtin_unicode(descendant).items():
        result.add(code, text, Source.EMBEDDED_PROGRAM)

    for code, glyph_name in extract_builtin_encoding(descendant).items():
        resolved = resolve_glyph_name(glyph_name)
        if resolved:
            result.add(code, resolved, Source.EMBEDDED_PROGRAM)
        elif code not in result.mapping:
            result.unresolved_glyphs[code] = glyph_name

    # 3. Explicit differences declared in the PDF override any base encoding.
    encoding = font.get("/Encoding")
    if encoding is not None and hasattr(encoding, "get"):
        differences = encoding.get("/Differences")
        if differences is not None:
            for code, glyph_name in apply_differences({}, differences).items():
                resolved = resolve_glyph_name(glyph_name)
                if resolved:
                    result.add(code, resolved, Source.ENCODING_DIFFERENCES)
                elif code not in result.mapping:
                    result.unresolved_glyphs[code] = glyph_name

    # 4. A predefined encoding, only where one legitimately applies.
    base_name = _base_encoding_name(font, composite)
    if base_name:
        for code, glyph_name in encoding_table(base_name).items():
            resolved = resolve_glyph_name(glyph_name)
            if resolved:
                result.add(code, resolved, Source.BASE_ENCODING)

    for code in list(result.unresolved_glyphs):
        if code in result.mapping:
            del result.unresolved_glyphs[code]

    return result


__all__ = ["RecoveredMapping", "Source", "recover_mapping"]
