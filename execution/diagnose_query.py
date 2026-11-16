# execution/diagnose_query.py
import os
import numpy as np
import pandas as pd

CLEAN_SKU_PATH = "data/processed/sku_clean.csv"
EMBEDDINGS_PATH = "data/embeddings/visual_embeddings.npy"

def diagnose():
    print("Loading visual embeddings...")
    embeddings = np.load(EMBEDDINGS_PATH, allow_pickle=True).tolist()
    
    print("Loading clean SKU metadata...")
    df = pd.read_csv(CLEAN_SKU_PATH)
    df["ID"] = df["ID"].astype(str)
    
    # Let's inspect the query SKU 4MST2081-01
    target_group = "4MST2081-01"
    query_row = df[df["SKU_GROUP"] == target_group]
    if query_row.empty:
        print(f"Query SKU {target_group} not found in catalog!")
        return
    query_row = query_row.iloc[0]
    query_sku_id = str(query_row["ID"])
    
    print(f"\nQuery SKU ID: {query_sku_id}")
    print(f"CATEGORY: {query_row.get('CATEGORY')}")
    print(f"COLLAR_NEW: {query_row.get('COLLAR_NEW')}")
    print(f"FIT_NORMALIZED: {query_row.get('FIT_NORMALIZED')}")
    print(f"MATERIAL_NEW: {query_row.get('MATERIAL_NEW')}")
    print(f"STATUS_ELIGIBLE: {query_row.get('STATUS_ELIGIBLE')}")
    
    # Check if there are any other SKUs matching Level 1 filters
    collar = str(query_row.get("COLLAR_NEW")).lower()
    fit_norm = str(query_row.get("FIT_NORMALIZED")).lower()
    mat = str(query_row.get("MATERIAL_NEW")).lower()
    cat = str(query_row.get("CATEGORY"))
    
    print("\nChecking database matches for Level 1 filters in DataFrame:")
    l1_matches = df[
        (df["ID"] != query_sku_id) &
        (df["CATEGORY"] == cat) &
        (df["STATUS_ELIGIBLE"].astype(str).str.lower() == "true") &
        (df["COLLAR_NEW"] == collar) &
        (df["FIT_NORMALIZED"] == fit_norm) &
        (df["MATERIAL_NEW"] == mat)
    ]
    print(f"Found {len(l1_matches)} other SKUs matching Level 1 in cleaned metadata.")
    if len(l1_matches) > 0:
        print(f"Sample matches: {l1_matches['SKU_GROUP'].head(5).tolist()}")
        
    print("\nChecking database matches for Level 4 filters (category + status) in DataFrame:")
    l4_matches = df[
        (df["ID"] != query_sku_id) &
        (df["CATEGORY"] == cat) &
        (df["STATUS_ELIGIBLE"].astype(str).str.lower() == "true")
    ]
    print(f"Found {len(l4_matches)} other SKUs matching Category & Status in cleaned metadata.")
    
    # Check how many photos are embedded in the index
    indexed_sku_ids = set(str(item["sku_id"]) for item in embeddings)
    print(f"\nUnique SKUs in visual embeddings: {len(indexed_sku_ids)}")
    
    # Is the query SKU's photos embedded?
    query_vectors = [item["embedding"] for item in embeddings if str(item["sku_id"]) == query_sku_id]
    print(f"Query SKU vectors in embeddings file: {len(query_vectors)}")
    
    # Are L1 matches embedded?
    l1_embedded = [sid for sid in l1_matches["ID"] if sid in indexed_sku_ids]
    print(f"Of the {len(l1_matches)} L1 matches, {len(l1_embedded)} are in visual embeddings.")

if __name__ == "__main__":
    diagnose()
