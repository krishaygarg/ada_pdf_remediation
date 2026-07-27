#!/usr/bin/env python3
"""
Experimental script: YOLOv8 document layout detection demo.
"""

import os
import sys
from pdf2image import convert_from_path
from PIL import Image, ImageDraw, ImageFont
from ultralytics import YOLO


def main():
    print("[DEMO] Starting YOLOv8 document layout detection demo...")
    
    # 1. Paths Setup
    workspace_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    pdf_path = os.path.join(workspace_dir, "samples", "physics", "physics.pdf")
    
    # Output directory relative to workspace root
    output_dir = os.path.join(workspace_dir, "outputs")
    os.makedirs(output_dir, exist_ok=True)
    output_image_path = os.path.join(output_dir, "yolo_layout_demo.png")
    
    if not os.path.exists(pdf_path):
        print(f"[DEMO] Error: Sample PDF not found at {pdf_path}")
        sys.exit(1)
        
    print(f"[DEMO] Loading PDF and converting page 1 to image...")
    pages = convert_from_path(pdf_path, dpi=150)
    if not pages:
        print("[DEMO] Error: Failed to convert PDF to image")
        sys.exit(1)
    page_img = pages[0]
    
    # Save a temporary file for YOLO input
    temp_dir = os.path.join(workspace_dir, "tmp")
    os.makedirs(temp_dir, exist_ok=True)
    temp_img_path = os.path.join(temp_dir, "temp_page_1.png")
    page_img.save(temp_img_path)
    print(f"[DEMO] Saved page image to: {temp_img_path}")
    
    # 2. Load YOLO model
    model_id = "ashen007/document-structure-detection"
    filename = "DSD-YOLOv8-v2.pt"
    print(f"[DEMO] Downloading/Loading YOLO layout model from Hugging Face: '{model_id}/{filename}'...")
    try:
        from huggingface_hub import hf_hub_download
        model_path = hf_hub_download(repo_id=model_id, filename=filename)
        print(f"[DEMO] Model loaded from: {model_path}")
        model = YOLO(model_path)
    except Exception as e:
        print(f"[DEMO] Warning loading Hugging Face model: {e}")
        print("[DEMO] Falling back to standard yolov8n.pt...")
        model = YOLO("yolov8n.pt")
        
    # 3. Predict layout
    print("[DEMO] Running layout prediction...")
    results = model.predict(source=temp_img_path, conf=0.25)
    result = results[0]
    
    # 4. Draw detections on the image
    print("[DEMO] Processing and drawing bounding boxes...")
    draw = ImageDraw.Draw(page_img)
    
    names = result.names
    boxes = result.boxes
    
    print(f"[DEMO] Found {len(boxes)} document elements:")
    
    colors = [
        (230, 25, 75), (60, 180, 75), (255, 225, 25), (0, 130, 200), (245, 130, 48),
        (145, 30, 180), (70, 240, 240), (240, 50, 230), (210, 245, 60), (250, 190, 212),
        (0, 128, 128), (220, 190, 255), (170, 110, 40), (255, 250, 200), (128, 0, 0),
        (170, 255, 195), (128, 128, 0), (255, 215, 180), (0, 0, 128), (128, 128, 128)
    ]
    
    for box in boxes:
        coords = box.xyxy[0].tolist()
        cls_id = int(box.cls[0].item())
        conf = box.conf[0].item()
        label = names.get(cls_id, f"Class {cls_id}")
        
        print(f"  - [{label}] Conf: {conf:.2f} | BBox: {[int(x) for x in coords]}")
        
        color = colors[cls_id % len(colors)]
        draw.rectangle(coords, outline=color, width=3)
        
        text = f"{label} ({conf:.2f})"
        try:
            font = ImageFont.load_default()
            draw.text((coords[0], coords[1] - 12), text, fill=color, font=font)
        except Exception:
            draw.text((coords[0], coords[1] - 12), text, fill=color)
            
    page_img.save(output_image_path)
    print(f"[DEMO] Saved annotated layout visualization to: {output_image_path}")
    
    if os.path.exists(temp_img_path):
        os.remove(temp_img_path)
        
    print("[DEMO] Demo script completed successfully!")


if __name__ == "__main__":
    main()
