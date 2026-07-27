#!/usr/bin/env python3
import os
import json
import argparse
from PIL import Image
import torch
from torch.utils.data import Dataset, DataLoader
from transformers import BlipProcessor, BlipForConditionalGeneration

class MathSpokenDataset(Dataset):
    """
    Dataset to load math expression PNGs and their spoken English descriptions.
    """
    def __init__(self, dataset_dir, processor):
        self.dataset_dir = dataset_dir
        self.processor = processor
        
        metadata_path = os.path.join(dataset_dir, "metadata.json")
        if not os.path.exists(metadata_path):
            raise FileNotFoundError(f"Metadata file not found: {metadata_path}. Run prepare_dataset.py first.")
            
        with open(metadata_path, "r") as f:
            self.metadata = json.load(f)
            
    def __len__(self):
        return len(self.metadata)
        
    def __getitem__(self, idx):
        item = self.metadata[idx]
        image_path = os.path.join(self.dataset_dir, item["image"])
        image = Image.open(image_path).convert("RGB")
        spoken = item["spoken"]
        
        # Tokenize spoken math and preprocess the image
        encoding = self.processor(
            images=image, 
            text=spoken, 
            padding="max_length", 
            max_length=32, 
            return_tensors="pt"
        )
        
        # Remove batch dimension added by return_tensors="pt"
        encoding = {k: v.squeeze(0) for k, v in encoding.items()}
        
        # In PyTorch CrossEntropyLoss, we should ignore padding tokens.
        # Hugging Face models calculate loss internally when we pass `labels`.
        # The labels should match target tokens, with pad tokens replaced by -100.
        encoding["labels"] = encoding["input_ids"].clone()
        encoding["labels"][encoding["labels"] == self.processor.tokenizer.pad_token_id] = -100
        
        return encoding

def train(args):
    print(f"[TRAIN] Device: {args.device}")
    
    # Initialize processor and pre-trained VLM
    print("[TRAIN] Loading BLIP processor and model...")
    processor = BlipProcessor.from_pretrained("Salesforce/blip-image-captioning-base")
    model = BlipForConditionalGeneration.from_pretrained("Salesforce/blip-image-captioning-base")
    
    if args.freeze_vision:
        print("[TRAIN] Freezing vision model parameters to save memory...")
        for param in model.vision_model.parameters():
            param.requires_grad = False
            
    model.to(args.device)
    
    # Load dataset
    print(f"[TRAIN] Loading dataset from {args.dataset_dir}...")
    dataset = MathSpokenDataset(args.dataset_dir, processor)
    dataloader = DataLoader(dataset, batch_size=args.batch_size, shuffle=True)
    
    # Set up optimizer
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr)
    
    print(f"[TRAIN] Starting training for {args.epochs} epochs...")
    model.train()
    
    for epoch in range(args.epochs):
        epoch_loss = 0.0
        for batch_idx, batch in enumerate(dataloader):
            optimizer.zero_grad()
            
            input_ids = batch["input_ids"].to(args.device)
            pixel_values = batch["pixel_values"].to(args.device)
            labels = batch["labels"].to(args.device)
            
            # Forward pass
            outputs = model(
                input_ids=input_ids,
                pixel_values=pixel_values,
                labels=labels
            )
            
            loss = outputs.loss
            loss.backward()
            optimizer.step()
            
            epoch_loss += loss.item()
            
        avg_loss = epoch_loss / len(dataloader)
        print(f"Epoch {epoch + 1}/{args.epochs} - Loss: {avg_loss:.4f}")
        
    # Save the fine-tuned model and processor
    os.makedirs(args.output_dir, exist_ok=True)
    print(f"[TRAIN] Saving fine-tuned model to {args.output_dir}...")
    model.save_pretrained(args.output_dir)
    processor.save_pretrained(args.output_dir)
    print("[TRAIN] Saving complete!")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fine-tune BLIP on math expressions.")
    parser.add_argument("--dataset_dir", type=str, default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "dataset"),
                        help="Path to the dataset directory containing metadata.json and images/")
    parser.add_argument("--output_dir", type=str, default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "fine_tuned_blip"),
                        help="Directory to save the fine-tuned model weights")
    parser.add_argument("--epochs", type=int, default=10, help="Number of training epochs")
    parser.add_argument("--batch_size", type=int, default=2, help="Batch size (lowered to prevent memory issues)")
    parser.add_argument("--lr", type=float, default=5e-5, help="Learning rate")
    parser.add_argument("--no_freeze_vision", dest="freeze_vision", action="store_false",
                        help="Do not freeze vision encoder parameters (keeps vision model trainable)")
    parser.set_defaults(freeze_vision=True)
    
    # Auto-detect hardware acceleration
    default_device = "cpu"
    if torch.backends.mps.is_available():
        default_device = "mps"
    elif torch.cuda.is_available():
        default_device = "cuda"
        
    parser.add_argument("--device", type=str, default=default_device, help="Device to run training on (cpu, mps, cuda)")
    
    args = parser.parse_args()
    train(args)
