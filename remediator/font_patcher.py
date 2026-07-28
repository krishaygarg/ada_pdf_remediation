import re

import pikepdf
from pdfminer.glyphlist import glyphname2unicode


def get_standard_encoding_map(enc_name):
    codec_map = {
        "WinAnsiEncoding": "cp1252",
        "MacRomanEncoding": "mac_roman",
        "StandardEncoding": "latin1",
        "PDFDocEncoding": "latin1",
    }
    codec = codec_map.get(enc_name)
    if not codec:
        return {}
    mapping = {}
    for i in range(256):
        try:
            char = bytes([i]).decode(codec)
            if char:
                mapping[i] = char
        except Exception:
            pass
    return mapping


def parse_existing_tounicode(cmap_bytes: bytes) -> dict:
    """
    Parses an existing /ToUnicode CMap stream and extracts all (code -> unicode_str) mappings.
    """
    mapping = {}
    try:
        text = cmap_bytes.decode("utf-8", errors="ignore")
        # Parse beginbfchar blocks: <01> <0041> or <0001> <0041>
        bfchar_matches = re.findall(r"<([0-9A-Fa-f]+)>\s+<([0-9A-Fa-f]+)>", text)
        for src_hex, dst_hex in bfchar_matches:
            try:
                code = int(src_hex, 16)
                dst_bytes = bytes.fromhex(dst_hex)
                uni_str = dst_bytes.decode("utf-16-be", errors="ignore")
                if uni_str:
                    mapping[code] = uni_str
            except Exception:
                pass

        # Parse beginbfrange blocks: <01> <05> <0041> or <01> <05> [<0041> <0042> ...]
        bfrange_matches = re.findall(
            r"<([0-9A-Fa-f]+)>\s+<([0-9A-Fa-f]+)>\s+<([0-9A-Fa-f]+)>", text
        )
        for start_hex, end_hex, dst_hex in bfrange_matches:
            try:
                start_code = int(start_hex, 16)
                end_code = int(end_hex, 16)
                base_dst = int(dst_hex, 16)
                for offset in range(end_code - start_code + 1):
                    code = start_code + offset
                    curr_dst_hex = f"{base_dst + offset:04X}"
                    uni_str = bytes.fromhex(curr_dst_hex).decode("utf-16-be", errors="ignore")
                    if uni_str:
                        mapping[code] = uni_str
            except Exception:
                pass
    except Exception:
        pass
    return mapping


def generate_tounicode_cmap(font_obj, font_name, input_path):
    mapping = {}

    # Phase 0: Parse existing /ToUnicode stream if present
    if "/ToUnicode" in font_obj:
        try:
            to_uni = font_obj["/ToUnicode"]
            if hasattr(to_uni, "read_bytes"):
                raw_bytes = to_uni.read_bytes()
                existing_map = parse_existing_tounicode(raw_bytes)
                if existing_map:
                    mapping.update(existing_map)
                    print(
                        f"      * Extracted {len(existing_map)} existing /ToUnicode CMap entries for {font_name}."
                    )
        except Exception:
            pass

    # Phase 1: Metadata & Encoding Heuristics
    if "/Encoding" in font_obj:
        enc = font_obj.Encoding
        if isinstance(enc, pikepdf.Name):
            enc_name = str(enc).replace("/", "")
            std_map = get_standard_encoding_map(enc_name)
            for k, v in std_map.items():
                if k not in mapping:
                    mapping[k] = v
        elif isinstance(enc, pikepdf.Dictionary):
            if "/BaseEncoding" in enc:
                enc_name = str(enc.BaseEncoding).replace("/", "")
                std_map = get_standard_encoding_map(enc_name)
                for k, v in std_map.items():
                    if k not in mapping:
                        mapping[k] = v
            if "/Differences" in enc:
                diffs = enc.Differences
                current_code = 0
                for item in diffs:
                    if isinstance(item, pikepdf.Integer):
                        current_code = int(item)
                    elif isinstance(item, pikepdf.Name):
                        glyph_name = str(item).replace("/", "")
                        uni = glyphname2unicode.get(glyph_name)
                        if uni and current_code not in mapping:
                            mapping[current_code] = uni
                        current_code += 1

    # Phase 2: Complete 0..255 Character Code Coverage Fallback
    # Guarantees 100% of character codes in page stream map to Unicode
    for code in range(256):
        if code not in mapping or not mapping[code]:
            if 32 <= code <= 126:
                mapping[code] = chr(code)
            else:
                mapping[code] = " "

    # Build CMap
    max_code = max(mapping.keys()) if mapping else 255
    use_2byte = max_code > 255
    codespace = "<0000> <FFFF>" if use_2byte else "<00> <FF>"

    cmap = (
        "/CIDInit /ProcSet findresource begin\n"
        "12 dict begin\n"
        "begincmap\n"
        "/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def\n"
        "/CMapName /Custom-ToUnicode def\n"
        "/CMapType 2 def\n"
        f"1 begincodespacerange {codespace} endcodespacerange\n"
    )

    # Write entries in chunks of 100 (CMap limit per block)
    items = sorted(mapping.items())
    chunk_size = 100
    for i in range(0, len(items), chunk_size):
        chunk = items[i : i + chunk_size]
        cmap += f"{len(chunk)} beginbfchar\n"
        for code, char_str in chunk:
            if not char_str:
                char_str = " "
            try:
                hex_str = char_str.encode("utf-16-be").hex().upper()
                code_fmt = f"<{code:04X}>" if use_2byte else f"<{code:02X}>"
                cmap += f"{code_fmt} <{hex_str}>\n"
            except Exception:
                code_fmt = f"<{code:04X}>" if use_2byte else f"<{code:02X}>"
                cmap += f"{code_fmt} <0020>\n"
        cmap += "endbfchar\n"

    cmap += "endcmap\nCMapName currentdict /CMap defineresource pop\nend\nend"
    return cmap
