"""Reading encodings out of embedded font programs.

Many documents, and nearly every document produced by TeX, embed symbolic
fonts that carry no /Encoding entry in the PDF font dictionary at all. The
mapping from character code to glyph exists only inside the font program. A
tool that ignores it has no choice but to guess, and guessing is how an en dash
becomes an opening brace.
"""

from __future__ import annotations

import contextlib
import io
import re

import pikepdf

#: Type 1 fonts declare their built-in encoding in the cleartext portion of the
#: program, before the eexec-encrypted section, as a sequence of
#: "dup <code> /<glyphname> put" entries. Reading it needs no decryption.
_TYPE1_ENCODING_ENTRY = re.compile(rb"dup\s+(\d{1,3})\s*/([A-Za-z0-9._]+)\s+put")

#: The alternative form, naming a predefined encoding instead of listing entries.
_TYPE1_NAMED_ENCODING = re.compile(rb"/Encoding\s+(\w+Encoding)\s+def")


def type1_builtin_encoding(program: bytes, clear_length: int | None = None) -> dict[int, str]:
    """Extract the built-in encoding from a Type 1 font program.

    Args:
        program: The raw font program, as stored in /FontFile.
        clear_length: Value of /Length1, the size of the cleartext portion.
            When absent the whole program is scanned, which is harmless because
            the encrypted portion does not match the entry pattern.

    Returns:
        ``{character code: glyph name}``, empty when nothing could be read.
    """
    section = program[:clear_length] if clear_length else program

    named = _TYPE1_NAMED_ENCODING.search(section)
    if named:
        from .encodings import encoding_table

        return encoding_table(named.group(1).decode("ascii", errors="replace"))

    table: dict[int, str] = {}
    for raw_code, raw_name in _TYPE1_ENCODING_ENTRY.findall(section):
        try:
            code = int(raw_code)
        except ValueError:  # pragma: no cover - pattern guarantees digits
            continue
        if 0 <= code <= 255:
            table[code] = raw_name.decode("ascii", errors="replace")
    return table


def truetype_cmap(program: bytes) -> dict[int, str]:
    """Extract a code to text mapping from a TrueType or OpenType program.

    Returns ``{character code: text}``. The character map is inverted: it maps
    Unicode to glyph identifiers, and what is needed here is the reverse.
    """
    try:
        from fontTools.ttLib import TTFont
    except ImportError:  # pragma: no cover - fonttools is a hard dependency
        return {}

    try:
        font = TTFont(io.BytesIO(program), fontNumber=0, lazy=True)
    except Exception:
        return {}

    try:
        table = font.getBestCmap()
    except Exception:
        return {}
    finally:
        with contextlib.suppress(Exception):  # pragma: no cover - defensive
            font.close()

    if not table:
        return {}
    # A symbolic TrueType font commonly maps codes into the 0xF000 private use
    # block. Both the plain code and the offset code are recorded so whichever
    # the content stream uses resolves.
    mapping: dict[int, str] = {}
    for code_point, _glyph in table.items():
        if 0xF000 <= code_point <= 0xF0FF:
            mapping.setdefault(code_point - 0xF000, chr(code_point - 0xF000))
        if code_point <= 0xFFFF:
            mapping.setdefault(code_point, chr(code_point))
    return mapping


def cff_glyph_order(program: bytes) -> dict[int, str]:
    """Extract the encoding of a bare CFF program, as found in /FontFile3."""
    try:
        from fontTools.cffLib import CFFFontSet
    except ImportError:  # pragma: no cover - fonttools is a hard dependency
        return {}

    try:
        font_set = CFFFontSet()
        font_set.decompile(io.BytesIO(program), None)
        if not font_set.fontNames:
            return {}
        top = font_set[font_set.fontNames[0]]
    except Exception:
        return {}

    encoding = getattr(top, "Encoding", None)
    if not encoding:
        return {}

    table: dict[int, str] = {}
    try:
        for code, glyph_name in enumerate(encoding):
            if isinstance(glyph_name, str) and glyph_name != ".notdef":
                table[code] = glyph_name
    except TypeError:
        return {}
    return table


def extract_builtin_encoding(font: pikepdf.Object) -> dict[int, str]:
    """Read the built-in encoding of whichever program a font descriptor holds.

    Returns ``{character code: glyph name}`` for Type 1 and CFF programs. A
    TrueType program returns text rather than glyph names, which the caller
    distinguishes by asking :func:`extract_builtin_unicode` instead.
    """
    descriptor = font.get("/FontDescriptor")
    if descriptor is None:
        return {}

    program = descriptor.get("/FontFile")
    if program is not None and hasattr(program, "read_bytes"):
        try:
            clear_length = int(program.get("/Length1", 0)) or None
            return type1_builtin_encoding(bytes(program.read_bytes()), clear_length)
        except Exception:
            return {}

    program = descriptor.get("/FontFile3")
    if program is not None and hasattr(program, "read_bytes"):
        try:
            return cff_glyph_order(bytes(program.read_bytes()))
        except Exception:
            return {}

    return {}


def extract_builtin_unicode(font: pikepdf.Object) -> dict[int, str]:
    """Read a direct code to text mapping from a TrueType program."""
    descriptor = font.get("/FontDescriptor")
    if descriptor is None:
        return {}
    program = descriptor.get("/FontFile2")
    if program is None or not hasattr(program, "read_bytes"):
        return {}
    try:
        return truetype_cmap(bytes(program.read_bytes()))
    except Exception:
        return {}


def find_system_truetype_font() -> bytes | None:
    """Find a standard TrueType font program file on the OS to embed when missing."""
    from pathlib import Path

    candidates = [
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
        "C:\\Windows\\Fonts\\arial.ttf",
    ]
    for path in candidates:
        if Path(path).exists():
            try:

                data = Path(path).read_bytes()
                if (
                    data.startswith(b"\x00\x01\x00\x00")
                    or data.startswith(b"OTTO")
                    or data.startswith(b"ttcf")
                ):
                    return data
            except Exception:
                continue
    return None


def ensure_font_embedded(pdf: pikepdf.Pdf, font_obj: pikepdf.Object) -> bool:
    """Ensure font_obj has an embedded font program (/FontFile, /FontFile2, or /FontFile3)."""
    descriptor = font_obj.get("/FontDescriptor")
    if descriptor is None:
        base_font = font_obj.get("/BaseFont", pikepdf.Name("/Helvetica"))
        descriptor = pikepdf.Dictionary(
            Type=pikepdf.Name("/FontDescriptor"),
            FontName=base_font,
            Flags=32,
            FontBBox=[-166, -225, 1000, 905],
            ItalicAngle=0,
            Ascent=905,
            Descent=-211,
            CapHeight=718,
            StemV=80,
        )
        font_obj["/FontDescriptor"] = pdf.make_indirect(descriptor)

    if any(k in descriptor for k in ("/FontFile", "/FontFile2", "/FontFile3")):
        return True

    font_bytes = find_system_truetype_font()
    if not font_bytes:
        return False

    font_stream = pikepdf.Stream(pdf, font_bytes)
    font_stream["/Length1"] = len(font_bytes)
    descriptor["/FontFile2"] = pdf.make_indirect(font_stream)
    return True


__all__ = [
    "cff_glyph_order",
    "ensure_font_embedded",
    "extract_builtin_encoding",
    "extract_builtin_unicode",
    "find_system_truetype_font",
    "truetype_cmap",
    "type1_builtin_encoding",
]

