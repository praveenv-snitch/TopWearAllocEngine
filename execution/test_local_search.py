# execution/test_local_search.py
import os
import numpy as np
import pandas as pd
import json

CLEAN_SKU_PATH = "data/processed/sku_clean.csv"
EMBEDDINGS_PATH = "data/embeddings/visual_embeddings.npy"

def is_colorway_sibling(query_sku_group, candidate_sku_group):
    if not query_sku_group or not candidate_sku_group:
        return False
    q_parts = str(query_sku_group).split("-")
    c_parts = str(candidate_sku_group).split("-")
    if len(q_parts) < 2 or len(c_parts) < 2:
        return False
    return (q_parts[0] == c_parts[0]) and (query_sku_group != candidate_sku_group)

def run_simulation(target_group="4MST2242-03"):
    print("Loading visual embeddings...")
    embeddings = np.load(EMBEDDINGS_PATH, allow_pickle=True).tolist()
    
    print("Loading clean SKU metadata...")
    df = pd.read_csv(CLEAN_SKU_PATH)
    df["ID"] = df["ID"].astype(str)
    
    # 1. Fetch query SKU
    query_row = df[df["SKU_GROUP"] == target_group]
    if query_row.empty:
        print(f"Query SKU {target_group} not found!")
        return
    query_row = query_row.iloc[0]
    query_sku_id = str(query_row["ID"])
    
    # Get attributes
    query_collar = str(query_row.get("COLLAR_NEW", "unknown")).lower()
    query_fit_normalized = str(query_row.get("FIT_NORMALIZED", "unknown")).lower()
    query_material = str(query_row.get("MATERIAL_NEW", "unknown")).lower()
    query_category = str(query_row.get("CATEGORY", "T-Shirts"))
    query_sku_group = str(query_row.get("SKU_GROUP", ""))
    
    print(f"\nQuery SKU: {query_sku_group} | Category: {query_category}")
    print(f"Collar: {query_collar} | Fit: {query_fit_normalized} | Material: {query_material}")
    
    # Get query vectors
    query_vectors = [item["embedding"] for item in embeddings if str(item["sku_id"]) == query_sku_id]
    print(f"Query SKU has {len(query_vectors)} photos embedded.")
    
    # Map all embeddings
    sku_embeddings_map = {}
    for item in embeddings:
        sid = str(item["sku_id"])
        if sid not in sku_embeddings_map:
            sku_embeddings_map[sid] = []
        sku_embeddings_map[sid].append(item["embedding"])
        
    # Calibrate floor
    # We will use the sibling floor calculation directly
    style_to_skus = {}
    sku_to_group = {}
    for _, row in df.iterrows():
        sid = str(row["ID"])
        sg = str(row.get("SKU_GROUP", ""))
        sku_to_group[sid] = sg
        if sg and "-" in sg:
            style = sg.split("-")[0]
            if style not in style_to_skus:
                style_to_skus[style] = []
            style_to_skus[style].append(sid)
            
    sibling_pairs = []
    for style, skus in style_to_skus.items():
        if len(skus) < 2:
            continue
        for i in range(len(skus)):
            for j in range(i + 1, len(skus)):
                s1, s2 = skus[i], skus[j]
                if sku_to_group.get(s1) != sku_to_group.get(s2):
                    sibling_pairs.append((s1, s2))
                    
    scores = []
    soft_attrs = ["SLEEVE_TYPE", "CLOSURE", "POCKET", "STYLE", "FABRIC_WEIGHT", "COMPOSITION", "OCCASSION_NEW", "FIT"]
    meta_map = df.set_index("ID").to_dict("index")
    
    print(f"Calibrating score floor from {len(sibling_pairs)} sibling pairs...")
    for s1, s2 in sibling_pairs[:200]: # Sample 200 to keep it fast
        vecs1 = sku_embeddings_map.get(s1)
        vecs2 = sku_embeddings_map.get(s2)
        if not vecs1 or not vecs2:
            continue
        sims = [np.dot(v1, v2)/(np.linalg.norm(v1)*np.linalg.norm(v2)) for v1 in vecs1 for v2 in vecs2]
        avg_sim = np.mean(sims)
        
        row1, row2 = meta_map.get(s1, {}), meta_map.get(s2, {})
        matched = sum(1 for attr in soft_attrs if str(row1.get(attr, "unknown")).lower() == str(row2.get(attr, "unknown")).lower() and str(row1.get(attr, "unknown")).lower() != "unknown")
        soft_boost = matched / len(soft_attrs)
        scores.append(avg_sim * 1.0 * (1.0 + soft_boost))
        
    score_floor = float(np.percentile(scores, 10.0)) if scores else 0.40
    print(f"Calibrated Score Floor: {score_floor:.4f}")
    
    # Track accepted and evaluated candidates
    accepted_skus = {}
    evaluated_sku_ids = set()
    multipliers = {1: 1.0, 2: 0.8, 3: 0.6, 4: 0.4}
    tier_tags = {1: "collar+fit+material", 2: "collar+fit", 3: "collar", 4: "category"}
    
    # Simulate cascade
    for level in [1, 2, 3, 4]:
        # Filter candidates from DataFrame
        if level == 1:
            candidates = df[
                (df["ID"] != query_sku_id) &
                (df["CATEGORY"] == query_category) &
                (df["STATUS_ELIGIBLE"].astype(str).str.lower() == "true") &
                (df["COLLAR_NEW"] == query_collar) &
                (df["FIT_NORMALIZED"] == query_fit_normalized) &
                (df["MATERIAL_NEW"] == query_material)
            ]
        elif level == 2:
            candidates = df[
                (df["ID"] != query_sku_id) &
                (df["CATEGORY"] == query_category) &
                (df["STATUS_ELIGIBLE"].astype(str).str.lower() == "true") &
                (df["COLLAR_NEW"] == query_collar) &
                (df["FIT_NORMALIZED"] == query_fit_normalized)
            ]
        elif level == 3:
            candidates = df[
                (df["ID"] != query_sku_id) &
                (df["CATEGORY"] == query_category) &
                (df["STATUS_ELIGIBLE"].astype(str).str.lower() == "true") &
                (df["COLLAR_NEW"] == query_collar)
            ]
        else:
            candidates = df[
                (df["ID"] != query_sku_id) &
                (df["CATEGORY"] == query_category) &
                (df["STATUS_ELIGIBLE"].astype(str).str.lower() == "true")
            ]
            
        candidate_ids = set(candidates["ID"].tolist())
        new_sku_ids = candidate_ids - evaluated_sku_ids
        evaluated_sku_ids.update(new_sku_ids)
        
        if not new_sku_ids:
            continue
            
        print(f"Level {level} ({tier_tags[level]}) exposed {len(new_sku_ids)} new candidate SKUs...")
        
        for cand_id in new_sku_ids:
            cand_vecs = sku_embeddings_map.get(cand_id)
            if not cand_vecs:
                continue
                
            sims = []
            for qv in query_vectors:
                for cv in cand_vecs:
                    sims.append(np.dot(qv, cv)/(np.linalg.norm(qv)*np.linalg.norm(cv)))
            avg_sim = float(np.mean(sims))
            
            cand_row = meta_map.get(cand_id, {})
            
            # soft boost
            matched_soft = []
            for attr in soft_attrs:
                q_val = str(query_row.get(attr, "unknown")).lower()
                c_val = str(cand_row.get(attr, "unknown")).lower()
                if q_val != "unknown" and q_val == c_val:
                    matched_soft.append(attr)
            soft_boost = len(matched_soft) / len(soft_attrs)
            
            mult = multipliers[level]
            final_score = avg_sim * mult * (1.0 + soft_boost)
            
            # Gating floor
            # Wait, let's see if we adjust floor by level multiplier
            level_floor = score_floor * mult
            if final_score >= level_floor:
                cand_sku_group = str(cand_row.get("SKU_GROUP", ""))
                match_type = "Obvious" if is_colorway_sibling(query_sku_group, cand_sku_group) else "Other"
                
                accepted_skus[cand_id] = {
                    "CANDIDATE_SKU_GROUP": cand_sku_group,
                    "CANDIDATE_PRODUCT_NAME": cand_row.get("PRODUCT_NAME", "Unknown"),
                    "FINAL_SCORE": final_score,
                    "VISUAL_SIMILARITY": avg_sim,
                    "TIER_CONFIDENCE_MULTIPLIER": mult,
                    "SOFT_MATCH_BOOST": 1.0 + soft_boost,
                    "TIGHTEST_TIER_TAG": tier_tags[level],
                    "MATCH_TYPE": match_type
                }
                
        if len(accepted_skus) >= 10:
            print(f"Stopped at Level {level}: Found {len(accepted_skus)} candidates.")
            break
            
    print(f"\nSimulation complete! Total accepted matches: {len(accepted_skus)}")
    top_matches = sorted(accepted_skus.values(), key=lambda x: -x["FINAL_SCORE"])[:10]
    for idx, m in enumerate(top_matches, 1):
        print(f"{idx}. {m['CANDIDATE_SKU_GROUP']} - {m['CANDIDATE_PRODUCT_NAME']} | Score: {m['FINAL_SCORE']:.4f} | Sim: {m['VISUAL_SIMILARITY']:.4f} | Tier: {m['TIGHTEST_TIER_TAG']} | Type: {m['MATCH_TYPE']}")

if __name__ == "__main__":
    run_simulation()
