#!/usr/bin/env python3
"""
Experimental script: PDF layout bounding box annotation.
"""

import os
import sys
import fitz  # PyMuPDF
from pdf2image import convert_from_path
from ultralytics import YOLO


def main():
    print("[PDF-DRAW] Starting PDF bounding box annotation...")
    
    workspace_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    if len(sys.argv) > 1:
        pdf_path = sys.argv[1]
    else:
        pdf_path = os.path.join(workspace_dir, "samples", "physics", "physics.pdf")
        
    pdf_path = os.path.abspath(pdf_path)
    
    output_dir = os.path.join(workspace_dir, "outputs")
    os.makedirs(output_dir, exist_ok=True)
    
    filename = os.path.basename(pdf_path)
    name_w_ext = os.path.splitext(filename)[0]
    output_filename = f"{name_w_ext}_with_bboxes.pdf"
    output_pdf_path = os.path.join(output_dir, output_filename)
    
    if not os.path.exists(pdf_path):
        print(f"[PDF-DRAW] Error: PDF not found at {pdf_path}")
        sys.exit(1)
        
    print("[PDF-DRAW] Rendering PDF page 1 to image...")
    pages = convert_from_path(pdf_path, dpi=150)
    if not pages:
        print("[PDF-DRAW] Error: Failed to convert PDF page to image")
        sys.exit(1)
    page_img = pages[0]
    img_w, img_h = page_img.size
    
    temp_dir = os.path.join(workspace_dir, "tmp")
    os.makedirs(temp_dir, exist_ok=True)
    temp_img_path = os.path.join(temp_dir, "temp_yolo_draw.png")
    page_img.save(temp_img_path)
    
    # 3. Load YOLO model & Predict
    model_id = "ashen007/document-structure-detection"
    filename_pt = "DSD-YOLOv8-v2.pt"
    try:
        from huggingface_hub import hf_hub_download
        model_path = hf_hub_download(repo_id=model_id, filename=filename_pt)
    except Exception:
        model_path = "yolov8n.pt"
        
    print(f"[PDF-DRAW] Loading model: {model_path}")
    model = YOLO(model_path)
    
    print("[PDF-DRAW] Running layout prediction...")
    results = model.predict(source=temp_img_path, conf=0.15, imgsz=1280)
    result = results[0]
    
    # 4. Load the original PDF with PyMuPDF to draw vector rectangles
    print("[PDF-DRAW] Opening PDF with PyMuPDF to draw vectors...")
    doc = fitz.open(pdf_path)
    page = doc[0]  # Page 1
    page_rect = page.rect
    page_w, page_h = page_rect.width, page_rect.height
    
    colors = [
        (0.9, 0.1, 0.3), (0.2, 0.7, 0.3), (1.0, 0.88, 0.1), (0.0, 0.5, 0.78), (0.96, 0.5, 0.18),
        (0.57, 0.12, 0.7), (0.27, 0.94, 0.94), (0.94, 0.2, 0.9), (0.82, 0.96, 0.23), (0.98, 0.74, 0.83)
    ]
    
    names = result.names
    boxes = result.boxes
    
    print(f"[PDF-DRAW] Mapping {len(boxes)} visual detections back to PDF coordinates...")
    for box in boxes:
        x0_img, y0_img, x1_img, y1_img = box.xyxy[0].tolist()
        cls_id = int(box.cls[0].item())
        conf = box.conf[0].item()
        label = names.get(cls_id, f"Class {cls_id}")
        
        x0_pdf = (x0_img / img_w) * page_w
        y0_pdf = (y0_img / img_h) * page_h
        x1_pdf = (x1_img / img_w) * page_w
        y1_pdf = (y1_img / img_h) * page_h
        
        rect = fitz.Rect(x0_pdf, y0_pdf, x1_pdf, y1_pdf)
        color = colors[cls_id % len(colors)]
        
        page.draw_rect(rect, color=color, width=1.5)
        
        label_text = f"{label} ({conf:.2f})"
        page.insert_text((x0_pdf, max(10.0, y0_pdf - 3.0)), label_text, fontsize=8, color=color)
        
    doc.save(output_pdf_path)
    doc.close()
    
    if os.path.exists(temp_img_path):
        os.remove(temp_img_path)
        
    print(f"[PDF-DRAW] PDF successfully saved to: {output_pdf_path}")


if __name__ == "__main__":
    main()
