import fitz
import pytesseract
import pikepdf
from PIL import Image
from pdfminer.glyphlist import glyphname2unicode

def get_standard_encoding_map(enc_name):
    codec_map = {
        "WinAnsiEncoding": "cp1252",
        "MacRomanEncoding": "mac_roman",
        "StandardEncoding": "latin1",
        "PDFDocEncoding": "latin1"
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

def generate_tounicode_cmap(font_obj, font_name, input_path):
    mapping = {}
    has_encoding = False
    
    # Phase 1: Metadata Heuristics
    if "/Encoding" in font_obj:
        enc = font_obj.Encoding
        if isinstance(enc, pikepdf.Name):
            enc_name = str(enc).replace("/", "")
            std_map = get_standard_encoding_map(enc_name)
            if std_map:
                mapping.update(std_map)
                has_encoding = True
        elif isinstance(enc, pikepdf.Dictionary):
            if "/BaseEncoding" in enc:
                enc_name = str(enc.BaseEncoding).replace("/", "")
                std_map = get_standard_encoding_map(enc_name)
                if std_map:
                    mapping.update(std_map)
                    has_encoding = True
            if "/Differences" in enc:
                diffs = enc.Differences
                current_code = 0
                for item in diffs:
                    if isinstance(item, pikepdf.Integer):
                        current_code = int(item)
                    elif isinstance(item, pikepdf.Name):
                        glyph_name = str(item).replace("/", "")
                        uni = glyphname2unicode.get(glyph_name)
                        if uni:
                            mapping[current_code] = uni
                        current_code += 1
                has_encoding = True

    # Default basic ASCII mapping if no encoding is found
    if not mapping:
        print("      * No mapping found in Phase 1 metadata. Standard ASCII fallback set.")
        for i in range(256):
            if 32 <= i <= 126:
                mapping[i] = chr(i)
    else:
        print(f"      * Phase 1 metadata success. Mapped {len(mapping)} chars.")
                
    # Phase 2: PyTesseract OCR Fallback
    if not has_encoding:
        print("      * Phase 2 OCR Fallback triggered...")
        try:
            doc = fitz.open(input_path)
            base_font_clean = str(font_name).replace("/", "").split("+")[-1]
            visited_codes = set()
            
            for page in doc:
                text_dict = page.get_text("rawdict")
                if "blocks" not in text_dict: continue
                pix = None
                img = None
                for block in text_dict["blocks"]:
                    if "lines" not in block: continue
                    for line in block["lines"]:
                        for span in line["spans"]:
                            span_font = span["font"]
                            if base_font_clean in span_font or span_font in base_font_clean:
                                for char in span["chars"]:
                                    c_str = char["c"]
                                    c_code = ord(c_str[0]) if len(c_str) == 1 else 0
                                    if c_code in visited_codes:
                                        continue
                                    visited_codes.add(c_code)
                                    
                                    if "\ufffd" in c_str or c_code == 0 or c_code not in mapping or mapping[c_code] == "":
                                        bbox = char["bbox"]
                                        if pix is None:
                                            pix = page.get_pixmap(dpi=300)
                                            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                                        scale = 300 / 72.0
                                        cx0, cy0, cx1, cy1 = bbox
                                        cx0, cy0, cx1, cy1 = cx0 * scale, cy0 * scale, cx1 * scale, cy1 * scale
                                        pad = 3
                                        crop = img.crop((cx0 - pad, cy0 - pad, cx1 + pad, cy1 + pad))
                                        print(f"        * OCR'ing char code {c_code} with bbox {bbox}...")
                                        ocr_text = pytesseract.image_to_string(crop, config='--psm 10').strip()
                                        print(f"        * OCR result: '{ocr_text}'")
                                        if ocr_text:
                                            mapping[c_code] = ocr_text[0]
            doc.close()
        except Exception as e:
            print(f"[OCR] Error during OCR fallback for font {font_name}: {e}")

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
    
    if mapping:
        cmap += f"{len(mapping)} beginbfchar\n"
        for code, char_str in mapping.items():
            if not char_str: char_str = " "
            try:
                hex_str = char_str.encode('utf-16-be').hex().upper()
                code_fmt = f"<{code:04X}>" if use_2byte else f"<{code:02X}>"
                cmap += f"{code_fmt} <{hex_str}>\n"
            except Exception:
                code_fmt = f"<{code:04X}>" if use_2byte else f"<{code:02X}>"
                cmap += f"{code_fmt} <0020>\n"
        cmap += "endbfchar\n"
    else:
        cmap += f"1 beginbfrange {codespace} <0000> endbfrange\n"
        
    cmap += (
        "endcmap\n"
        "CMapName currentdict /CMap defineresource pop\n"
        "end end"
    )
    return cmap
