# execution/build_visual_index.py
import os
import json
import numpy as np
# pyrefly: ignore [missing-import]
import torch
# pyrefly: ignore [missing-import]
import open_clip
import pandas as pd
# pyrefly: ignore [missing-import]
from PIL import Image
from tqdm import tqdm

CLEAN_SKU_PATH = "data/processed/sku_clean.csv"
EMBEDDINGS_DIR = "data/embeddings"
INDEX_PATH = os.path.join(EMBEDDINGS_DIR, "visual_embeddings.npy")
SKU_BATCH_SIZE = 100  # Number of SKUs to process per batch loop
INFERENCE_BATCH_SIZE = 32  # Number of images to run in a single vector pass
DEVICE = "cpu"

def load_existing_index():
    """Loads existing index if it exists, returning a list of dicts and a set of processed SKU IDs."""
    if os.path.exists(INDEX_PATH):
        try:
            data = np.load(INDEX_PATH, allow_pickle=True).tolist()
            processed_ids = {item["sku_id"] for item in data}
            print(f"Loaded existing index containing {len(data)} image vectors from {len(processed_ids)} SKUs.")
            return data, processed_ids
        except Exception as e:
            print(f"Error loading index file ({e}). Starting fresh.")
    return [], set()

def deduplicate_embeddings(new_vectors, threshold=0.98):
    """Filters out vectors that are near-identical (similarity > threshold) to already accepted ones for the SKU."""
    surviving = []
    for vec in new_vectors:
        is_duplicate = False
        for accepted_vec in surviving:
            # since vectors are normalized, dot product is exactly cosine similarity
            sim = np.dot(vec, accepted_vec)
            if sim > threshold:
                is_duplicate = True
                break
        if not is_duplicate:
            surviving.append(vec)
    return surviving

def run_sanity_check(index_data, num_checks=3):
    """Picks random SKUs and finds their top-5 visually similar neighbors across the catalog."""
    print(f"\n--- Running Visual Similarity Sanity Check ({num_checks} SKUs) ---")
    sku_ids = list(set(item["sku_id"] for item in index_data))
    if len(sku_ids) < 2:
        print("Not enough SKUs in the index to perform similarity search.")
        return

    # Select target SKUs for the check
    np.random.seed(42)  # For reproducible spot-checks
    targets = np.random.choice(sku_ids, min(num_checks, len(sku_ids)), replace=False)

    # Load SKU metadata to print names
    meta_df = pd.read_csv(CLEAN_SKU_PATH)
    meta_df["ID"] = meta_df["ID"].astype(str)
    meta_map = meta_df.set_index("ID")["PRODUCT_NAME"].to_dict()

    for target_sku in targets:
        target_name = meta_map.get(target_sku, "Unknown SKU")
        print(f"\nTarget SKU: {target_sku} - {target_name}")

        # Get all image vectors for target SKU
        target_vectors = [item["embedding"] for item in index_data if item["sku_id"] == target_sku]
        if not target_vectors:
            continue

        # Group other SKU vectors
        other_skus = {}
        for item in index_data:
            other_id = item["sku_id"]
            if other_id == target_sku:
                continue  # Leave-one-out: exclude self
            if other_id not in other_skus:
                other_skus[other_id] = []
            other_skus[other_id].append(item["embedding"])

        # Compute average cosine similarity for each candidate SKU
        scores = []
        for other_id, other_vectors in other_skus.items():
            pairwise_sims = []
            for tv in target_vectors:
                for ov in other_vectors:
                    pairwise_sims.append(np.dot(tv, ov))
            
            # Distance metric: average similarity across all photo combinations
            avg_score = np.mean(pairwise_sims)
            scores.append((other_id, avg_score))

        # Sort matches by average similarity descending
        top_matches = sorted(scores, key=lambda x: -x[1])[:5]
        print("  Top 5 Visual Matches:")
        for rank, (match_id, score) in enumerate(top_matches, 1):
            match_name = meta_map.get(match_id, "Unknown SKU")
            print(f"    {rank}. {match_id} (Score: {score:.4f}) - {match_name}")

def main():
    if not os.path.exists(CLEAN_SKU_PATH):
        print(f"Error: Clean metadata file not found at {CLEAN_SKU_PATH}. Run clean_attributes.py first.")
        return

    df = pd.read_csv(CLEAN_SKU_PATH)
    df["ID"] = df["ID"].astype(str)
    
    # 1. Load existing index to allow resuming
    index_data, processed_ids = load_existing_index()
    
    # 2. Load photo filter log
    filter_log_path = "data/processed/photo_filter_log.json"
    filter_log = {}
    if os.path.exists(filter_log_path):
        try:
            with open(filter_log_path, "r") as f:
                filter_log = json.load(f)
            print(f"Loaded photo filter log containing {len(filter_log)} image statuses.")
        except Exception as e:
            print(f"Error loading filter log ({e}). Running without pre-filtering.")
    else:
        print("Warning: Photo filter log not found. Running index build without pre-filtering.")

    # 3. Filter out already processed SKUs
    unprocessed_df = df[~df["ID"].isin(processed_ids)].copy()
    total_to_process = len(unprocessed_df)
    
    if total_to_process == 0:
        print("All SKUs are already processed. No new embeddings to generate.")
        run_sanity_check(index_data)
        return
        
    print(f"Loading Marqo-FashionSigLIP for visual indexing...")
    model, _, preprocess = open_clip.create_model_and_transforms('hf-hub:Marqo/marqo-fashionSigLIP')
    model = model.to(DEVICE)
    model.eval()
        
    print(f"Starting batched visual index builder for {total_to_process} SKUs in batches of {SKU_BATCH_SIZE}...")
    
    os.makedirs(EMBEDDINGS_DIR, exist_ok=True)
    
    # Process SKUs in blocks
    for start_idx in range(0, total_to_process, SKU_BATCH_SIZE):
        batch_df = unprocessed_df.iloc[start_idx:start_idx + SKU_BATCH_SIZE]
        
        # We will collect all image paths that need to be embedded across this entire SKU block
        paths_to_embed = []
        sku_to_paths = {}  # Map sku_id to list of paths
        
        for _, row in batch_df.iterrows():
            sku_id = row["ID"]
            photo_paths_str = row["photo_paths_local"]
            
            if pd.isna(photo_paths_str) or photo_paths_str.strip() == "":
                continue
                
            photo_paths = photo_paths_str.split(";")
            valid_paths = []
            
            for path in photo_paths:
                # Apply pre-embedding photo filter check
                if filter_log:
                    if path in filter_log:
                        if not filter_log[path].get("keep", True):
                            continue  # Skip dropped photo (size chart, banner, swing tag)
                    else:
                        print(f"Warning: Photo {path} not found in filter log. Processing by default.")
                        
                if os.path.exists(path):
                    valid_paths.append(path)
                    paths_to_embed.append(path)
            
            if valid_paths:
                sku_to_paths[sku_id] = valid_paths

        if not paths_to_embed:
            continue

        # Embed all collected images in batches of INFERENCE_BATCH_SIZE
        path_to_embedding = {}
        
        for idx in range(0, len(paths_to_embed), INFERENCE_BATCH_SIZE):
            img_batch_paths = paths_to_embed[idx:idx + INFERENCE_BATCH_SIZE]
            tensors = []
            valid_batch_paths = []
            
            for path in img_batch_paths:
                try:
                    img = Image.open(path).convert("RGB")
                    tensor = preprocess(img)
                    tensors.append(tensor)
                    valid_batch_paths.append(path)
                except Exception as e:
                    print(f"Error loading {path} for embedding: {e}")
            
            if not tensors:
                continue
                
            try:
                stacked_tensor = torch.stack(tensors).to(DEVICE)
                with torch.no_grad():
                    img_features = model.encode_image(stacked_tensor)
                    img_features /= img_features.norm(dim=-1, keepdim=True)
                    embeddings = img_features.cpu().numpy()
                
                for i, path in enumerate(valid_batch_paths):
                    path_to_embedding[path] = embeddings[i]
            except Exception as e:
                print(f"Batch embedding failed: {e}. Retrying sequentially for this batch.")
                for path in valid_batch_paths:
                    try:
                        img = Image.open(path).convert("RGB")
                        tensor = preprocess(img).unsqueeze(0).to(DEVICE)
                        with torch.no_grad():
                            img_features = model.encode_image(tensor)
                            img_features /= img_features.norm(dim=-1, keepdim=True)
                            path_to_embedding[path] = img_features.squeeze().cpu().numpy()
                    except Exception as ex:
                        print(f"Sequential fallback failed for {path}: {ex}")

        # Assemble new index items for the SKUs in this block
        new_items = []
        for sku_id, paths in sku_to_paths.items():
            sku_vectors = []
            valid_paths = []
            
            for path in paths:
                if path in path_to_embedding:
                    sku_vectors.append(path_to_embedding[path])
                    valid_paths.append(path)
            
            if not sku_vectors:
                continue
                
            # Deduplicate self-similar photos for this SKU (cosine similarity > 0.98)
            surviving_vectors = deduplicate_embeddings(sku_vectors, threshold=0.98)
            
            # Map back to matching path indices
            for i, vector in enumerate(surviving_vectors):
                new_items.append({
                    "sku_id": sku_id,
                    "image_path": valid_paths[i],
                    "embedding": vector
                })
        
        # Append and save after this SKU block
        if new_items:
            index_data.extend(new_items)
            np.save(INDEX_PATH, index_data)
            
        progress = min(start_idx + SKU_BATCH_SIZE, total_to_process)
        print(f"Progress: {progress}/{total_to_process} SKUs processed. Index size: {len(index_data)} image vectors.")
        
    print("\nVisual index generation complete. Index saved to:", INDEX_PATH)
    run_sanity_check(index_data)

if __name__ == "__main__":
    main()
