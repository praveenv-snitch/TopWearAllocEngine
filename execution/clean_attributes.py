# execution/clean_attributes.py
import os
import pandas as pd
import numpy as np

RAW_DATA_PATH = "data/raw/sku_master.csv"
FILL_RATES_PATH = "data/raw/attribute_fill_rates.csv"
IMAGE_DIR = "data/raw/images"

PROCESSED_SKU_PATH = "data/processed/sku_clean.csv"
EMBEDDINGS_DIR = "data/embeddings"
ATTRIBUTE_VECTORS_PATH = os.path.join(EMBEDDINGS_DIR, "attribute_vectors.csv")

# Target columns to clean and encode
TAG_COLUMNS = [
    "COLOR",
    "MATERIAL_NEW",  # Fabric
    "FIT",
    "FIT_NORMALIZED", # Normalized Fit
    "OCCASSION_NEW",
    "PRINT_DESIGN",
    "SLEEVE_TYPE",
    "COLLAR_NEW",
    "DESIGNS",
    "CLOSURE",
    "POCKET",
    "MAPPING_FINAL",
    "SKU_CLASS",
    "FABRIC_WEIGHT",
    "COMPOSITION",
    "STYLE"
]

def normalize_fit(fit_str):
    """Maps granular fit values to normalized categories: oversized, slim, regular."""
    if pd.isna(fit_str) or str(fit_str).strip() == "" or str(fit_str).lower() == "nan":
        return "regular"
    fit_clean = str(fit_str).strip().lower().replace("_", " ").replace("-", " ")
    if any(x in fit_clean for x in ["cropped oversized", "box fit", "oversized", "relaxed"]):
        return "oversized"
    elif "slim" in fit_clean:
        return "slim"
    else:
        return "regular"

def is_status_eligible(row):
    """Determines candidate SKU eligibility (status == active, or draft with a live date)."""
    status = str(row.get("STATUS", "")).strip().lower()
    live_date = row.get("FINAL_LIVE_DATE")
    if status == "active":
        return "true"
    elif status == "draft" and not pd.isna(live_date) and str(live_date).strip() != "" and str(live_date).lower() != "nan":
        return "true"
    return "false"

def get_dynamic_mrp_buckets(mrp_series):
    """Returns a function to bucket MRP values dynamically based on dataset min and max MRP."""
    min_mrp = mrp_series.min()
    max_mrp = mrp_series.max()
    if pd.isna(min_mrp) or pd.isna(max_mrp):
        return lambda x: "unknown"
        
    t_low = int((min_mrp // 100) * 100 + 100)
    t_high = int(((max_mrp + 99) // 100) * 100 - 100)
    
    # 100-step increments as requested by the user
    step = 100
    
    def bucket_fn(mrp):
        if pd.isna(mrp):
            return "unknown"
        try:
            mrp = float(mrp)
        except ValueError:
            return "unknown"
            
        if mrp < t_low:
            return f"<{t_low}"
        if mrp >= t_high:
            return f"{t_high}+"
            
        bucket_idx = int((mrp - t_low) // step)
        b_start = t_low + bucket_idx * step
        b_end = b_start + step - 1
        return f"{b_start}-{b_end}"
        
    return bucket_fn

def clean_tag(val):
    """Standardizes casing, strips whitespace, normalizes spaces/dashes to underscores."""
    if pd.isna(val) or str(val).strip() == "" or str(val).lower() == "nan":
        return "unknown"
    s = str(val).strip().lower()
    s = s.replace("-", " ").replace("_", " ")
    s = " ".join(s.split())  # Normalize spacing (remove double spaces)
    s = s.replace(" ", "_")  # Convert to snake_case for clean column headers
    return s

def scan_local_images(sku_id):
    """Finds all downloaded images for a SKU and returns their relative paths as a semicolon-separated string."""
    sku_images = []
    for idx in range(1, 11):
        filename = f"{sku_id}_{idx}.jpg"
        filepath = os.path.join(IMAGE_DIR, filename)
        if os.path.exists(filepath):
            sku_images.append(filepath)
    return ";".join(sku_images)

def main():
    print("Starting attributes cleaning and validation...")
    
    # 1. Load SKU master CSV
    if not os.path.exists(RAW_DATA_PATH):
        print(f"Error: {RAW_DATA_PATH} not found. Run pull_data.py first.")
        return
        
    df = pd.read_csv(RAW_DATA_PATH)
    initial_count = len(df)
    print(f"Loaded {initial_count} SKUs from raw data.")
    
    # 2. Deduplicate SKU rows
    df = df.drop_duplicates(subset=["ID"])
    dedup_count = len(df)
    print(f"Deduplicated to {dedup_count} SKUs (removed {initial_count - dedup_count} duplicates).")
    
    # Convert ID to string to prevent numerical/string mismatch
    df["ID"] = df["ID"].astype(str)
    
    # 3. Filter by photo existence on disk
    print("Scanning data/raw/images/ for downloaded photos...")
    df["photo_paths_local"] = df["ID"].apply(scan_local_images)
    
    # Count how many photos each SKU has
    df["photo_count"] = df["photo_paths_local"].apply(lambda x: len(x.split(";")) if x else 0)
    
    # Filter to SKUs that have at least one successfully downloaded photo
    df_filtered = df[df["photo_count"] > 0].copy()
    filtered_count = len(df_filtered)
    print(f"Filtered out {dedup_count - filtered_count} SKUs with no downloaded photos.")
    print(f"Remaining SKUs with at least one photo: {filtered_count}")
    
    # Calculate FIT_NORMALIZED, STATUS_ELIGIBLE, GP, and MRP_BUCKET
    print("Computing FIT_NORMALIZED, STATUS_ELIGIBLE, GP, and MRP_BUCKET...")
    df_filtered["FIT_NORMALIZED"] = df_filtered["FIT"].apply(normalize_fit)
    df_filtered["STATUS_ELIGIBLE"] = df_filtered.apply(is_status_eligible, axis=1)
    
    mrp_col = "MRP" if "MRP" in df_filtered.columns else "ORIGINAL_PRICE"
    cogs_col = "COGS" if "COGS" in df_filtered.columns else None
    
    mrp_series = pd.to_numeric(df_filtered[mrp_col], errors='coerce').fillna(0.0)
    cogs_series = pd.to_numeric(df_filtered[cogs_col], errors='coerce').fillna(0.0) if cogs_col is not None else pd.Series(0.0, index=df_filtered.index)
    
    df_filtered["GP"] = mrp_series - cogs_series
    bucket_fn = get_dynamic_mrp_buckets(mrp_series)
    df_filtered["MRP_BUCKET"] = mrp_series.apply(bucket_fn)
    
    # 4. Flag missing attributes (HAS_MISSING_ATTRIBUTES)
    print("Flagging missing/unknown attributes...")
    # Check if any key tags are null, empty, or labeled "unknown"
    has_missing = pd.Series(False, index=df_filtered.index)
    for col in TAG_COLUMNS:
        if col in df_filtered.columns:
            # Check for NaN or empty values
            is_null = df_filtered[col].isna() | (df_filtered[col].astype(str).str.strip() == "")
            has_missing = has_missing | is_null
            
    df_filtered["HAS_MISSING_ATTRIBUTES"] = has_missing
    missing_count = df_filtered["HAS_MISSING_ATTRIBUTES"].sum()
    print(f"Flagged {missing_count} SKUs with one or more missing key attributes.")
    
    # 5. Standardize categorical attributes
    print("Standardizing attribute tags...")
    df_cleaned = df_filtered.copy()
    for col in TAG_COLUMNS:
        if col in df_cleaned.columns:
            df_cleaned[col] = df_cleaned[col].apply(clean_tag)
            
    # Save cleaned SKU Master to processed
    os.makedirs(os.path.dirname(PROCESSED_SKU_PATH), exist_ok=True)
    df_cleaned.to_csv(PROCESSED_SKU_PATH, index=False)
    print(f"Saved cleaned SKU master to {PROCESSED_SKU_PATH}")
    
    # 6. Multi-hot encode attributes
    print("Generating multi-hot encoded attribute vectors...")
    # Generate dummies for our categorical columns
    dummies = pd.get_dummies(df_cleaned[TAG_COLUMNS], prefix=TAG_COLUMNS)
    # Convert Boolean columns to 1 or 0
    dummies = dummies.astype(int)
    
    # Combine with SKU ID
    attribute_vectors = pd.concat([df_cleaned[["ID"]], dummies], axis=1)
    
    # Save attribute vectors
    os.makedirs(EMBEDDINGS_DIR, exist_ok=True)
    attribute_vectors.to_csv(ATTRIBUTE_VECTORS_PATH, index=False)
    print(f"Saved attribute vectors to {ATTRIBUTE_VECTORS_PATH} with shape {attribute_vectors.shape}.")
    
    # 7. Spot-check 5 random SKUs
    print("\n--- Spot-Checking 5 Cleaned SKUs ---")
    sample_skus = df_cleaned.sample(min(5, len(df_cleaned)))
    for _, row in sample_skus.iterrows():
        sku_id = row["ID"]
        print(f"\nSKU ID: {sku_id} ({row['PRODUCT_NAME']})")
        print(f"  Cleaned Tags: " + ", ".join([f"{col}: {row[col]}" for col in TAG_COLUMNS]))
        print(f"  Local photos: {row['photo_count']} files")
        print(f"  Has missing attributes? {row['HAS_MISSING_ATTRIBUTES']}")
        
        # Verify dummy values are 1 for those specific tags
        vector_row = attribute_vectors[attribute_vectors["ID"] == sku_id].iloc[0]
        active_dummies = [col for col in vector_row.index if col != "ID" and vector_row[col] == 1]
        print(f"  Active Encoded Columns (value=1): {active_dummies}")

if __name__ == "__main__":
    main()
