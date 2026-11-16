# execution/rca_cascade.py
import numpy as np
import pandas as pd
import chromadb

CHROMA_DB_PATH = "models/chroma_db"
COLLECTION_NAME = "sku_visual_embeddings"
CLEAN_SKU_PATH = "data/processed/sku_clean.csv"

def run_rca(target_group="4MST2423-01"):
    df = pd.read_csv(CLEAN_SKU_PATH)
    df["ID"] = df["ID"].astype(str)
    
    target_row = df[df["SKU_GROUP"] == target_group].iloc[0]
    target_sku_id = str(target_row["ID"])
    
    client = chromadb.PersistentClient(path=CHROMA_DB_PATH)
    collection = client.get_collection(name=COLLECTION_NAME)
    
    # Load visual embeddings
    embeddings = np.load("data/embeddings/visual_embeddings.npy", allow_pickle=True).tolist()
    query_vectors = [item["embedding"] for item in embeddings if str(item["sku_id"]) == target_sku_id]
    
    query_collar = str(target_row.get("COLLAR_NEW", "unknown")).lower()
    query_fit_normalized = str(target_row.get("FIT_NORMALIZED", "unknown")).lower()
    query_material = str(target_row.get("MATERIAL_NEW", "unknown")).lower()
    query_category = str(target_row.get("CATEGORY", "T-Shirts"))
    
    print(f"RCA for SKU: {target_group} (ID: {target_sku_id})")
    print(f"Collar: {query_collar} | Fit: {query_fit_normalized} | Material: {query_material} | Category: {query_category}")
    print(f"Query vectors found: {len(query_vectors)}")
    
    evaluated_sku_ids = set()
    multipliers = {1: 1.0, 2: 0.8, 3: 0.6, 4: 0.4}
    tier_tags = {1: "collar+fit+material", 2: "collar+fit", 3: "collar", 4: "category"}
    
    for level in [1, 2, 3, 4]:
        base_filters = [
            {"sku_id": {"$ne": target_sku_id}},
            {"category": query_category},
            {"status_eligible": "true"}
        ]
        if level == 1:
            base_filters.extend([
                {"collar": query_collar},
                {"fit_normalized": query_fit_normalized},
                {"material": query_material}
            ])
        elif level == 2:
            base_filters.extend([
                {"collar": query_collar},
                {"fit_normalized": query_fit_normalized}
            ])
        elif level == 3:
            base_filters.append({"collar": query_collar})
            
        where_clause = {"$and": base_filters}
            
        candidate_photos = []
        for qv in query_vectors:
            results = collection.query(
                query_embeddings=[qv.tolist()],
                n_results=200,
                where=where_clause
            )
            if results and "metadatas" in results and results["metadatas"]:
                for q_idx, meta_list in enumerate(results["metadatas"]):
                    for c_idx, meta in enumerate(meta_list):
                        candidate_photos.append(meta)
                        
        candidate_sku_ids = set(str(m["sku_id"]) for m in candidate_photos)
        
        total_retrieved = len(candidate_sku_ids)
        new_sku_ids = candidate_sku_ids - evaluated_sku_ids
        duplicate_count = total_retrieved - len(new_sku_ids)
        evaluated_sku_ids.update(new_sku_ids)
        
        print(f"\n--- Level {level} ({tier_tags[level]}) ---")
        print(f"  Chroma returned {total_retrieved} unique SKU candidates.")
        print(f"  Discarded {duplicate_count} candidates already evaluated in tighter tiers.")
        print(f"  Newly exposed candidates to score: {len(new_sku_ids)}")
        
if __name__ == "__main__":
    run_rca()
