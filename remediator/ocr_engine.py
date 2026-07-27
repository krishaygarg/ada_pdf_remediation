#!/usr/bin/env python3
"""
OCR Engine Module for Scanned PDFs.
Extracts word bounding boxes using PyTesseract and constructs invisible text layer content streams.
"""

import io
import pikepdf
import pytesseract
from pdf2image import convert_from_path
from PIL import Image

from .config import LOCAL_TMP


def generate_ocr_text_ops(pdf_path: str, page_idx: int, page_width: float, page_height: float, start_mcid: int, pdf_doc, document_elem):
    """
    Runs Tesseract OCR on a scanned page image and returns (ocr_ops, page_struct_elems, next_mcid).
    Injects text in invisible rendering mode (3 Tr) so text is 100% highlightable, searchable, and accessible.
    """
    ocr_ops = []
    page_struct_elems = []
    mcid = start_mcid

    try:
        # Render single page at 200 DPI for high-accuracy OCR
        images = convert_from_path(pdf_path, dpi=200, first_page=page_idx + 1, last_page=page_idx + 1, output_folder=LOCAL_TMP)
        if not images:
            return ocr_ops, page_struct_elems, mcid
            
        page_img = images[0]
        img_w, img_h = page_img.size
        scale_x = page_width / img_w if img_w > 0 else 1.0
        scale_y = page_height / img_h if img_h > 0 else 1.0

        # Run PyTesseract OCR to extract word coordinates
        ocr_data = pytesseract.image_to_data(page_img, output_type=pytesseract.Output.DICT)
        
        n_boxes = len(ocr_data['text'])
        words = []
        
        for i in range(n_boxes):
            word_str = str(ocr_data['text'][i]).strip()
            conf = int(ocr_data['conf'][i]) if 'conf' in ocr_data and str(ocr_data['conf'][i]).lstrip('-').isdigit() else 0
            
            if word_str and conf > 20:
                left = float(ocr_data['left'][i]) * scale_x
                top = float(ocr_data['top'][i]) * scale_y
                w = float(ocr_data['width'][i]) * scale_x
                h = float(ocr_data['height'][i]) * scale_y
                
                # Convert top-left coordinates to PDF bottom-left coordinates
                pdf_x = left
                pdf_y = page_height - top - h
                
                words.append({
                    'text': word_str,
                    'x': pdf_x,
                    'y': pdf_y,
                    'font_size': max(8.0, h)
                })

        if not words:
            return ocr_ops, page_struct_elems, mcid

        # Set text rendering mode to 3 Tr (Invisible text for accessibility & text selection)
        ocr_ops.append(([], pikepdf.Operator("BT")))
        ocr_ops.append(([pikepdf.Integer(3)], pikepdf.Operator("Tr")))
        ocr_ops.append(([pikepdf.Name("/Helvetica"), pikepdf.Integer(12)], pikepdf.Operator("Tf")))

        for word in words:
            word_text = word['text']
            font_size = word['font_size']
            x = word['x']
            y = word['y']

            # Wrap in structural marked content /P << /MCID mcid >> BDC ... EMC
            ocr_ops.append(([pikepdf.Name("/P"), pikepdf.Dictionary(MCID=mcid)], pikepdf.Operator("BDC")))
            ocr_ops.append(([pikepdf.Name("/Helvetica"), font_size], pikepdf.Operator("Tf")))
            ocr_ops.append(([1.0, 0.0, 0.0, 1.0, x, y], pikepdf.Operator("Tm")))
            ocr_ops.append(([pikepdf.String(word_text)], pikepdf.Operator("Tj")))
            ocr_ops.append(([], pikepdf.Operator("EMC")))

            # Create structural P element
            p_elem = pdf_doc.make_indirect(pikepdf.Dictionary(
                Type=pikepdf.Name("/StructElem"),
                S=pikepdf.Name("/P"),
                P=document_elem,
                K=pikepdf.Integer(mcid)
            ))
            document_elem.K.append(p_elem)
            page_struct_elems.append(p_elem)
            mcid += 1

        ocr_ops.append(([], pikepdf.Operator("ET")))

    except Exception as e:
        print(f"[REMEDIATOR-OCR] Note during OCR layer generation: {e}")

    return ocr_ops, page_struct_elems, mcid
