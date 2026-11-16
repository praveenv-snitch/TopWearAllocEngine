# execution/download_images.py
import os
import pandas as pd
import requests
from PIL import Image
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm

IMAGE_DIR = "data/raw/images"
MAX_THREADS = 16  # Adjust based on your internet connection

def ensure_image_directory():
    os.makedirs(IMAGE_DIR, exist_ok=True)

def get_target_resolution():
    """Checks the model's preprocessor to get the actual expected input resolution, defaulting to 224."""
    print("Checking Marqo-FashionSigLIP expected input resolution from open_clip...")
    try:
        import open_clip
        # This will download the model config/weights if not cached already
        _, _, preprocess = open_clip.create_model_and_transforms('hf-hub:Marqo/marqo-fashionSigLIP')
        
        # Traverse transforms to find Resize/ResizeKeepRatio size parameter
        for t in preprocess.transforms:
            if hasattr(t, "size"):
                size = t.size
                if isinstance(size, (list, tuple)):
                    target_size = size[0]
                elif isinstance(size, int):
                    target_size = size
                else:
                    continue
                print(f"Detected model input resolution: {target_size}x{target_size}")
                return target_size
                
        print("Could not inspect size from preprocess transforms. Defaulting to 224.")
        return 224
    except Exception as e:
        print(f"Could not load model configuration ({e}). Defaulting to 224.")
        return 224

def download_and_resize_image(url, output_path, target_size):
    """Downloads, converts to RGB, resizes to target_size x target_size, and saves as compressed JPEG (quality=90)."""
    if os.path.exists(output_path):
        return "skipped"
    
    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        
        # Load image
        img = Image.open(BytesIO(response.content))
        img = img.convert("RGB")
        
        # Resize to target resolution
        img = img.resize((target_size, target_size), Image.Resampling.LANCZOS)
        
        # Save as compressed JPEG with quality=90
        img.save(output_path, "JPEG", quality=90)
        return "success"
    except Exception as e:
        return f"failed: {str(e)}"

def process_sku_images(row):
    """Generates download tasks for a single SKU."""
    sku_id = str(row["ID"])
    tasks = []
    
    # We check columns IMAGE_1 through IMAGE_10
    for idx in range(1, 11):
        col_name = f"IMAGE_{idx}"
        if col_name in row and pd.notna(row[col_name]):
            url = str(row[col_name]).strip()
            if url.startswith("http"):
                filename = f"{sku_id}_{idx}.jpg"
                output_path = os.path.join(IMAGE_DIR, filename)
                tasks.append((url, output_path))
    return tasks

def main():
    ensure_image_directory()
    
    csv_path = "data/raw/sku_master.csv"
    if not os.path.exists(csv_path):
        print(f"Error: {csv_path} does not exist. Run pull_data.py first.")
        return
        
    print("Loading SKU master...")
    df = pd.read_csv(csv_path)
    
    # Check open_clip preprocess transforms for Marqo-FashionSigLIP
    target_size = get_target_resolution()
    
    print("Preparing image download queue...")
    all_tasks = []
    for _, row in df.iterrows():
        all_tasks.extend(process_sku_images(row))
        
    total_tasks = len(all_tasks)
    print(f"Total images queue: {total_tasks}")
    
    success_count = 0
    skipped_count = 0
    failed_count = 0
    failed_log = []
    
    print(f"Starting concurrent downloads using {MAX_THREADS} threads...")
    with ThreadPoolExecutor(max_workers=MAX_THREADS) as executor:
        # Submit all tasks
        future_to_task = {
            executor.submit(download_and_resize_image, url, path, target_size): (url, path) 
            for url, path in all_tasks
        }
        
        # Monitor progress
        for future in tqdm(as_completed(future_to_task), total=total_tasks, desc="Downloading"):
            url, path = future_to_task[future]
            try:
                result = future.result()
                if result == "success":
                    success_count += 1
                elif result == "skipped":
                    skipped_count += 1
                else:
                    failed_count += 1
                    failed_log.append(f"{path}: {result} (URL: {url})")
            except Exception as e:
                failed_count += 1
                failed_log.append(f"{path}: Exception {str(e)} (URL: {url})")
                
    print("\n--- Download Summary ---")
    print(f"Successfully downloaded & resized: {success_count}")
    print(f"Skipped (already existed): {skipped_count}")
    print(f"Failed: {failed_count}")
    
    if failed_log:
        log_path = "logs/failed_image_downloads.txt"
        os.makedirs("logs", exist_ok=True)
        with open(log_path, "w") as f:
            f.write("\n".join(failed_log))
        print(f"Failed downloads logged to {log_path}")

if __name__ == "__main__":
    main()
