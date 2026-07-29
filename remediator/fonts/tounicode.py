"""Reading and writing /ToUnicode CMap streams.

Two correctness points the previous implementation missed.

The codespace range must match the width of the codes the content stream
actually uses. A composite font addressed with two-byte codes needs
``<0000> <FFFF>``; emitting ``<00> <FF>`` for it produces a map a consumer
cannot apply. The previous code computed the width after padding the mapping
out to 256 entries, which pinned it to one byte for every font.

Contiguous runs are emitted as ``bfrange`` rather than as individual
``bfchar`` entries. A full Latin text font drops from roughly 220 lines to
around 20, which matters because the stream is stored uncompressed in many
producers and is parsed on every text extraction.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: A CMap may not declare more than 100 entries in a single block.
MAX_ENTRIES_PER_BLOCK = 100


@dataclass(frozen=True)
class CodespaceRange:
    """The byte width of the codes a CMap covers."""

    byte_width: int

    @property
    def declaration(self) -> str:
        if self.byte_width == 1:
            return "<00> <FF>"
        return "<" + "0" * (self.byte_width * 2) + "> <" + "F" * (self.byte_width * 2) + ">"

    def format_code(self, code: int) -> str:
        return f"<{code:0{self.byte_width * 2}X}>"


def choose_codespace(codes: list[int], *, composite: bool) -> CodespaceRange:
    """Pick the codespace width for the codes a font uses.

    A composite (Type 0) font is addressed through a CMap that is almost always
    two bytes wide, so it takes two bytes regardless of which codes happen to
    appear in this document. A simple font takes one byte unless a code above
    255 proves otherwise.
    """
    if composite:
        return CodespaceRange(2)
    if codes and max(codes) > 0xFF:
        return CodespaceRange(2)
    return CodespaceRange(1)


def _encode_text(value: str) -> str:
    """Encode replacement text as big-endian UTF-16, as a CMap requires."""
    return value.encode("utf-16-be").hex().upper()


def _contiguous_runs(mapping: dict[int, str]) -> list[tuple[int, int, str]]:
    """Group entries into runs where both code and text increment together.

    Returns ``(first_code, last_code, first_text)`` triples. A run of length one
    is still returned; the caller decides whether it is worth a range.
    """
    runs: list[tuple[int, int, str]] = []
    for code in sorted(mapping):
        text = mapping[code]
        if runs:
            first, last, first_text = runs[-1]
            expected = last + 1
            # A run only holds where the text is a single character advancing in
            # step with the code. Multi-character replacements, such as a
            # decomposed ligature, cannot be expressed as a range.
            if (
                code == expected
                and len(text) == 1
                and len(first_text) == 1
                and ord(text) == ord(first_text) + (code - first)
            ):
                runs[-1] = (first, code, first_text)
                continue
        runs.append((code, code, text))
    return runs


def build_tounicode_cmap(
    mapping: dict[int, str],
    *,
    composite: bool = False,
    font_name: str = "Recovered",
) -> str:
    """Render ``{character code: text}`` as a /ToUnicode CMap program.

    Only codes present in ``mapping`` are emitted. Codes the font uses but that
    could not be resolved are deliberately left out: a consumer then reports
    them as unmapped, which is recoverable, whereas mapping them to a space
    silently replaces the text with whitespace.
    """
    codes = sorted(mapping)
    codespace = choose_codespace(codes, composite=composite)
    safe_name = re.sub(r"[^A-Za-z0-9]", "", font_name) or "Recovered"

    lines = [
        "/CIDInit /ProcSet findresource begin",
        "12 dict begin",
        "begincmap",
        "/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def",
        f"/CMapName /{safe_name}-UCS2 def",
        "/CMapType 2 def",
        f"1 begincodespacerange {codespace.declaration} endcodespacerange",
    ]

    runs = _contiguous_runs(mapping)
    ranges = [run for run in runs if run[1] > run[0]]
    singles = [run for run in runs if run[1] == run[0]]

    for start in range(0, len(singles), MAX_ENTRIES_PER_BLOCK):
        block = singles[start : start + MAX_ENTRIES_PER_BLOCK]
        lines.append(f"{len(block)} beginbfchar")
        for code, _last, text in block:
            lines.append(f"{codespace.format_code(code)} <{_encode_text(text)}>")
        lines.append("endbfchar")

    for start in range(0, len(ranges), MAX_ENTRIES_PER_BLOCK):
        block = ranges[start : start + MAX_ENTRIES_PER_BLOCK]
        lines.append(f"{len(block)} beginbfrange")
        for first, last, text in block:
            lines.append(
                f"{codespace.format_code(first)} {codespace.format_code(last)} "
                f"<{_encode_text(text)}>"
            )
        lines.append("endbfrange")

    lines += [
        "endcmap",
        "CMapName currentdict /CMap defineresource pop",
        "end",
        "end",
    ]
    return "\n".join(lines)


_BFCHAR_BLOCK = re.compile(rb"beginbfchar(.*?)endbfchar", re.DOTALL)
_BFRANGE_BLOCK = re.compile(rb"beginbfrange(.*?)endbfrange", re.DOTALL)
_HEX_PAIR = re.compile(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]*)>")
_HEX_TRIPLE = re.compile(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]*)>")
_HEX_ARRAY = re.compile(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*\[(.*?)\]", re.DOTALL)


def _decode_utf16(value: bytes) -> str:
    try:
        return bytes.fromhex(value.decode("ascii")).decode("utf-16-be", errors="ignore")
    except Exception:
        return ""


def parse_tounicode_cmap(data: bytes) -> dict[int, str]:
    """Parse an existing /ToUnicode CMap into ``{character code: text}``.

    Blocks are located before their entries are read. The previous
    implementation applied one regular expression for pairs and another for
    triples across the whole stream, so every ``bfrange`` triple also matched
    the pair pattern and was recorded a second time with the wrong meaning.
    """
    mapping: dict[int, str] = {}

    for block in _BFRANGE_BLOCK.findall(data):
        for raw_first, raw_last, raw_items in _HEX_ARRAY.findall(block):
            first = int(raw_first, 16)
            last = int(raw_last, 16)
            values = re.findall(rb"<([0-9A-Fa-f]*)>", raw_items)
            for offset, value in enumerate(values):
                if first + offset > last:
                    break
                text = _decode_utf16(value)
                if text:
                    mapping[first + offset] = text

        without_arrays = _HEX_ARRAY.sub(b"", block)
        for raw_first, raw_last, raw_text in _HEX_TRIPLE.findall(without_arrays):
            first = int(raw_first, 16)
            last = int(raw_last, 16)
            if last < first or last - first > 0xFFFF:
                continue
            base = _decode_utf16(raw_text)
            if not base:
                continue
            if len(base) == 1:
                start = ord(base)
                for offset in range(last - first + 1):
                    code_point = start + offset
                    if code_point <= 0x10FFFF:
                        mapping[first + offset] = chr(code_point)
            else:
                # A multi-character base cannot be incremented, so the whole
                # range maps to the same replacement text.
                for offset in range(last - first + 1):
                    mapping[first + offset] = base

    for block in _BFCHAR_BLOCK.findall(data):
        for raw_code, raw_text in _HEX_PAIR.findall(block):
            text = _decode_utf16(raw_text)
            if text:
                mapping[int(raw_code, 16)] = text

    return mapping


__all__ = [
    "MAX_ENTRIES_PER_BLOCK",
    "CodespaceRange",
    "build_tounicode_cmap",
    "choose_codespace",
    "parse_tounicode_cmap",
]
