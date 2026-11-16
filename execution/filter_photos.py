# execution/filter_photos.py
import os
import json
import numpy as np
import torch
import open_clip
from PIL import Image
from tqdm import tqdm

IMAGE_DIR = "data/raw/images"
LOG_PATH = "data/processed/photo_filter_log.json"
DEVICE = "cpu"
INFERENCE_BATCH_SIZE = 32  # Process 32 images at once in a single vector pass

# Zero-shot classification labels
LABELS = {
    "product": "a product studio photo of a t-shirt or clothing item on a plain background",
    "size_chart": "a size chart, measurement guide, size table, or text infographic showing dimensions",
    "banner": "a promotional banner, brand poster, logo, or marketing advertisement with text",
    "lifestyle": "a lifestyle photo of a model posing outdoors, street photography, or a background scene",
    "hang_tag": "a close-up photo of a clothing hang tag, swing tag, price label, paper card tag, or cardboard label"
}

def load_filter_log():
    if os.path.exists(LOG_PATH):
        try:
            with open(LOG_PATH, "r") as f:
                log = json.load(f)
            print(f"Loaded existing filter log containing {len(log)} classified photos.")
            return log
        except Exception as e:
            print(f"Error loading filter log ({e}). Starting fresh.")
    return {}

def save_filter_log(log):
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    with open(LOG_PATH, "w") as f:
        json.dump(log, f, indent=2)

def main():
    if not os.path.exists(IMAGE_DIR) or not os.listdir(IMAGE_DIR):
        print(f"Error: No images found in {IMAGE_DIR}. Run download_images.py first.")
        return

    # 1. Load existing progress
    log = load_filter_log()
    
    # 2. Get list of local photos
    all_photos = [
        os.path.join(IMAGE_DIR, f) 
        for f in os.listdir(IMAGE_DIR) 
        if f.lower().endswith(('.jpg', '.jpeg', '.png'))
    ]
    unclassified_photos = [p for p in all_photos if p not in log]
    total_unclassified = len(unclassified_photos)
    
    if total_unclassified == 0:
        print("All photos have already been classified.")
        show_spot_check_results(log)
        return
        
    print(f"Loading Marqo-FashionSigLIP for zero-shot photo filtering...")
    model, _, preprocess = open_clip.create_model_and_transforms('hf-hub:Marqo/marqo-fashionSigLIP')
    tokenizer = open_clip.get_tokenizer('hf-hub:Marqo/marqo-fashionSigLIP')
    model = model.to(DEVICE)
    model.eval()
    
    # 3. Precompute text label embeddings
    print("Precomputing text label embeddings...")
    label_keys = list(LABELS.keys())
    label_texts = list(LABELS.values())
    
    with torch.no_grad():
        tokens = tokenizer(label_texts).to(DEVICE)
        text_features = model.encode_text(tokens)
        text_features /= text_features.norm(dim=-1, keepdim=True)
        
    print(f"Classifying {total_unclassified} photos using batched inference (batch size: {INFERENCE_BATCH_SIZE})...")
    
    # 4. Process in batches of INFERENCE_BATCH_SIZE
    for start_idx in tqdm(range(0, total_unclassified, INFERENCE_BATCH_SIZE), desc="Classifying"):
        batch_paths = unclassified_photos[start_idx:start_idx + INFERENCE_BATCH_SIZE]
        
        tensors = []
        valid_paths = []
        
        # Load and preprocess batch images
        for img_path in batch_paths:
            try:
                img = Image.open(img_path).convert("RGB")
                tensor = preprocess(img)
                tensors.append(tensor)
                valid_paths.append(img_path)
            except Exception as e:
                # Mark as failed immediately
                log[img_path] = {
                    "keep": False,
                    "label": "failed",
                    "error": str(e)
                }
        
        if not tensors:
            continue
            
        try:
            # Stack all batch tensors together into a single tensor block
            stacked_tensor = torch.stack(tensors).to(DEVICE)
            
            with torch.no_grad():
                # Forward pass for the entire batch
                img_features = model.encode_image(stacked_tensor)
                img_features /= img_features.norm(dim=-1, keepdim=True)
                
                # Matrix multiplication to calculate similarities for the entire batch at once
                # Shape: (batch_size, num_classes)
                similarities_batch = (img_features @ text_features.T).cpu().numpy()
                
            batch_dropped = []
            
            # Map predictions back to each file path
            for i, img_path in enumerate(valid_paths):
                similarities = similarities_batch[i]
                best_idx = int(np.argmax(similarities))
                best_label = label_keys[best_idx]
                score = float(similarities[best_idx])
                
                # Keep both product and lifestyle photos (exclude size charts, banners, and hang tags)
                keep = (best_label not in ("size_chart", "banner", "hang_tag"))
                
                res = {
                    "keep": keep,
                    "label": best_label,
                    "score": score
                }
                log[img_path] = res
                
                if not keep:
                    batch_dropped.append((img_path, res))
                    
            # Print any drops in the current batch for visibility
            if batch_dropped:
                print(f"\n  --> Photos dropped in batch:")
                for path, res in batch_dropped:
                    print(f"      - {os.path.basename(path)} -> [{res['label'].upper()}] (score: {res['score']:.4f})")
                    
        except Exception as e:
            # If batch forward pass fails, fallback to sequential for this batch
            print(f"\nBatch failed with error: {e}. Falling back to sequential mode for this batch.")
            for img_path in valid_paths:
                try:
                    img = Image.open(img_path).convert("RGB")
                    tensor = preprocess(img).unsqueeze(0).to(DEVICE)
                    with torch.no_grad():
                        img_features = model.encode_image(tensor)
                        img_features /= img_features.norm(dim=-1, keepdim=True)
                        similarities = (img_features @ text_features.T).squeeze().cpu().numpy()
                    
                    best_idx = int(np.argmax(similarities))
                    best_label = label_keys[best_idx]
                    score = float(similarities[best_idx])
                    keep = (best_label not in ("size_chart", "banner", "hang_tag"))
                    
                    log[img_path] = {"keep": keep, "label": best_label, "score": score}
                except Exception as ex:
                    log[img_path] = {"keep": False, "label": "failed", "error": str(ex)}
                    
        # Save progress incrementally after every batch is completed
        save_filter_log(log)
        
    print("\nPhoto classification complete. Results logged to:", LOG_PATH)
    show_spot_check_results(log)

def show_spot_check_results(log):
    """Outputs a list of filtered-out (dropped) files for manual spot checking."""
    dropped = [path for path, result in log.items() if not result["keep"]]
    print(f"\nTotal photos dropped/filtered out: {len(dropped)} of {len(log)}")
    if dropped:
        print("\n--- Manual Spot-Check: Top 25 Dropped Photo Results ---")
        for i, path in enumerate(dropped[:25], 1):
            res = log[path]
            label = res.get("label", "unknown")
            score = res.get("score", 0.0)
            print(f"  {i:2d}. {os.path.basename(path)} -> [{label.upper()}] (score: {score:.4f})")

if __name__ == "__main__":
    main()
