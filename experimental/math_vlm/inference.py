#!/usr/bin/env python3
import os
import argparse
from PIL import Image
import torch
from transformers import BlipProcessor, BlipForConditionalGeneration

def run_inference(image_path, model_path, device):
    if not os.path.exists(image_path):
        raise FileNotFoundError(f"Image not found: {image_path}")
        
    print(f"[INFERENCE] Loading model and processor from: {model_path}...")
    try:
        processor = BlipProcessor.from_pretrained(model_path)
        model = BlipForConditionalGeneration.from_pretrained(model_path)
    except Exception as e:
        print(f"[INFERENCE] Error loading model from {model_path}: {e}")
        print("[INFERENCE] Falling back to pre-trained 'Salesforce/blip-image-captioning-base'...")
        processor = BlipProcessor.from_pretrained("Salesforce/blip-image-captioning-base")
        model = BlipForConditionalGeneration.from_pretrained("Salesforce/blip-image-captioning-base")
        
    model.to(device)
    model.eval()
    
    # Load and preprocess image
    image = Image.open(image_path).convert("RGB")
    print(f"[INFERENCE] Processing image: {image_path}...")
    
    # BLIP model requires pixel values. We do not provide conditional text during inference.
    inputs = processor(images=image, return_tensors="pt").to(device)
    
    # Generate text description
    print("[INFERENCE] Running model generation...")
    with torch.no_grad():
        out = model.generate(
            **inputs, 
            max_new_tokens=40,
            num_beams=3,
            early_stopping=True
        )
        
    description = processor.decode(out[0], skip_special_tokens=True)
    
    print("\n" + "=" * 60)
    print(f"IMAGE:  {os.path.basename(image_path)}")
    print(f"SPOKEN: {description}")
    print("=" * 60 + "\n")
    
    return description

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run spoken math VLM inference on a math expression image.")
    parser.add_argument("--image", type=str, required=True, help="Path to the math expression image crop")
    
    # Default model path
    default_model_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fine_tuned_blip")
    parser.add_argument("--model", type=str, default=default_model_path, 
                        help="Path to the model directory (defaults to fine_tuned_blip)")
    
    # Auto-detect device
    default_device = "cpu"
    if torch.backends.mps.is_available():
        default_device = "mps"
    elif torch.cuda.is_available():
        default_device = "cuda"
        
    parser.add_argument("--device", type=str, default=default_device, help="Device (cpu, mps, cuda)")
    
    args = parser.parse_args()
    run_inference(args.image, args.model, args.device)
