# execution/build_vector_store.py
import os
import json
import numpy as np
import pandas as pd
# pyrefly: ignore [missing-import]
import chromadb
import yaml
from tqdm import tqdm
import openpyxl
from openpyxl.styles import Font, Alignment

CLEAN_SKU_PATH = "data/processed/sku_clean.csv"
EMBEDDINGS_PATH = "data/embeddings/visual_embeddings.npy"
CHROMA_DB_PATH = "models/chroma_db"
COLLECTION_NAME = "sku_visual_embeddings"

def load_config():
    """Loads settings.yaml configuration if present."""
    config_path = "config/settings.yaml"
    if os.path.exists(config_path):
        try:
            with open(config_path) as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            print(f"Warning: Failed to load config from {config_path}: {e}")
    return {}

def load_data():
    """Loads visual embeddings and clean metadata."""
    if not os.path.exists(CLEAN_SKU_PATH):
        raise FileNotFoundError(f"Clean SKU metadata not found at {CLEAN_SKU_PATH}. Please run clean_attributes.py first.")
    if not os.path.exists(EMBEDDINGS_PATH):
        raise FileNotFoundError(f"Visual embeddings not found at {EMBEDDINGS_PATH}. Please run build_visual_index.py first.")
        
    print("Loading visual embeddings...")
    embeddings = np.load(EMBEDDINGS_PATH, allow_pickle=True).tolist()
    
    print("Loading clean SKU metadata...")
    df = pd.read_csv(CLEAN_SKU_PATH)
    df["ID"] = df["ID"].astype(str)
    
    return embeddings, df

def clean_metadata_row(row):
    """Ensures metadata values are Chroma-compatible (strings, numbers, no NaNs)."""
    meta = {}
    # Key columns to index for filtering and display metadata
    cols_to_extract = {
        "ID": "sku_id",
        "SKU_GROUP": "sku_group",
        "PRODUCT_NAME": "product_name",
        "CATEGORY": "category",
        "STATUS": "status",
        "STATUS_ELIGIBLE": "status_eligible",
        "FINAL_LIVE_DATE": "final_live_date",
        "COLOR": "color",
        "FIT": "fit",
        "FIT_NORMALIZED": "fit_normalized",
        "MATERIAL_NEW": "material",
        "COLLAR_NEW": "collar",
        "SLEEVE_TYPE": "sleeve_type",
        "CLOSURE": "closure",
        "POCKET": "pocket",
        "STYLE": "style",
        "FABRIC_WEIGHT": "fabric_weight",
        "COMPOSITION": "composition",
        "OCCASSION_NEW": "occasion",
        "DESIGNS": "designs",
        "PRINT_DESIGN": "print_design",
        "MRP_BUCKET": "mrp_bucket",
        "GP": "gp",
        "IMAGE_1": "image_1",
        "IMAGE_2": "image_2"
    }
    
    for csv_col, meta_key in cols_to_extract.items():
        val = row.get(csv_col)
        if pd.isna(val):
            meta[meta_key] = "unknown"
        else:
            if isinstance(val, bool) or str(val).lower() in ["true", "false"]:
                meta[meta_key] = "true" if (str(val).lower() == "true") else "false"
            elif isinstance(val, (int, float)):
                meta[meta_key] = float(val)
            else:
                meta[meta_key] = str(val)
            
    return meta

def build_vector_store():
    embeddings, df = load_data()
    
    # Map SKU metadata by ID for fast lookup
    meta_lookup = {}
    for _, row in df.iterrows():
        sku_id = row["ID"]
        meta_lookup[sku_id] = clean_metadata_row(row)
        
    print("Initializing Chroma Persistent Client...")
    client = chromadb.PersistentClient(path=CHROMA_DB_PATH)
    
    # Configure collection to use cosine space
    print(f"Creating collection '{COLLECTION_NAME}' (using Cosine distance)...")
    collection = client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"}
    )
    
    # Check if there are already items in the collection
    existing_count = collection.count()
    if existing_count > 0:
        print(f"Collection already contains {existing_count} items. We will recreate it to index clean data.")
        client.delete_collection(COLLECTION_NAME)
        collection = client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"}
        )
        
    # Prepare batch data
    ids = []
    vectors = []
    metadatas = []
    
    print(f"Processing {len(embeddings)} image vectors for ingestion...")
    for idx, item in enumerate(embeddings):
        sku_id = str(item["sku_id"])
        img_path = item["image_path"]
        vector = item["embedding"]
        
        # Unique ID for each photo is its path
        ids.append(img_path)
        vectors.append(vector.tolist())
        
        # Link attributes metadata
        meta = meta_lookup.get(sku_id, {"sku_id": sku_id}).copy()
        meta["image_path"] = img_path
        metadatas.append(meta)
        
    # Batch add to Chroma
    batch_size = 500
    total_items = len(ids)
    print(f"Inserting into Chroma in batches of {batch_size}...")
    
    for i in tqdm(range(0, total_items, batch_size), desc="Ingesting to Chroma"):
        end_idx = min(i + batch_size, total_items)
        collection.add(
            ids=ids[i:end_idx],
            embeddings=vectors[i:end_idx],
            metadatas=metadatas[i:end_idx]
        )
        
    print(f"Chroma indexing complete! Total items in collection: {collection.count()}")

def is_colorway_sibling(query_sku_group, candidate_sku_group):
    """Checks if query and candidate are colorway siblings (same style prefix, different colorway)."""
    if not query_sku_group or not candidate_sku_group:
        return False
    q_parts = str(query_sku_group).split("-")
    c_parts = str(candidate_sku_group).split("-")
    if len(q_parts) < 2 or len(c_parts) < 2:
        return False
    return (q_parts[0] == c_parts[0]) and (query_sku_group != candidate_sku_group)

def calibrate_score_floor(all_embeddings, df, percentile=10.0):
    """
    Dynamically calibrates the score floor based on the distribution of blended scores
    among known colorway-sibling pairs in the dataset.
    """
    print("Calibrating blended-score floor from colorway-sibling SKU pairs...")
    
    style_to_skus = {}
    sku_to_group = {}
    for _, row in df.iterrows():
        sku_id = str(row["ID"])
        sku_group = str(row.get("SKU_GROUP", ""))
        sku_to_group[sku_id] = sku_group
        
        if not sku_group or "-" not in sku_group:
            continue
        style_code = sku_group.split("-")[0]
        if style_code not in style_to_skus:
            style_to_skus[style_code] = []
        style_to_skus[style_code].append(sku_id)
        
    sku_embeddings = {}
    for item in all_embeddings:
        sid = str(item["sku_id"])
        if sid not in sku_embeddings:
            sku_embeddings[sid] = []
        sku_embeddings[sid].append(item["embedding"])
        
    sibling_pairs = []
    for style_code, skus in style_to_skus.items():
        if len(skus) < 2:
            continue
        for i in range(len(skus)):
            for j in range(i + 1, len(skus)):
                sku1, sku2 = skus[i], skus[j]
                if sku_to_group.get(sku1) != sku_to_group.get(sku2):
                    sibling_pairs.append((sku1, sku2))
                    
    if not sibling_pairs:
        print("Warning: No colorway-sibling SKU pairs found. Using default floor of 0.40.")
        return 0.40
        
    print(f"Found {len(sibling_pairs)} colorway-sibling pairs. Computing blended scores...")
    
    cfg = load_config()
    damping = cfg.get("similarity_search", {}).get("soft_boost_damping", 0.20)
    print(f"Using soft boost damping factor: {damping:.2f}")
    
    scores = []
    meta_map = df.set_index("ID").to_dict("index")
    soft_attrs = ["SLEEVE_TYPE", "CLOSURE", "POCKET", "STYLE", "FABRIC_WEIGHT", "COMPOSITION", "OCCASSION_NEW", "FIT"]
    
    for sku1, sku2 in sibling_pairs:
        vecs1 = sku_embeddings.get(sku1)
        vecs2 = sku_embeddings.get(sku2)
        if not vecs1 or not vecs2:
            continue
            
        sims = []
        for v1 in vecs1:
            for v2 in vecs2:
                norm1 = np.linalg.norm(v1)
                norm2 = np.linalg.norm(v2)
                if norm1 > 0 and norm2 > 0:
                    sims.append(np.dot(v1, v2) / (norm1 * norm2))
        if not sims:
            continue
        avg_sim = np.mean(sims)
        
        row1 = meta_map.get(sku1, {})
        row2 = meta_map.get(sku2, {})
        matched_count = 0
        for attr in soft_attrs:
            v1 = str(row1.get(attr, "unknown")).lower()
            v2 = str(row2.get(attr, "unknown")).lower()
            if v1 != "unknown" and v1 == v2:
                matched_count += 1
                
        soft_boost = matched_count / len(soft_attrs)
        blended_score = avg_sim * 1.0 * (1.0 + damping * soft_boost)
        scores.append(blended_score)
        
    if not scores:
        print("Warning: Failed to compute blended scores for any sibling pairs. Using default floor of 0.40.")
        return 0.40
        
    floor = float(np.percentile(scores, percentile))
    print(f"Blended scores: min={np.min(scores):.4f}, max={np.max(scores):.4f}, mean={np.mean(scores):.4f}")
    print(f"Calibrated score floor ({percentile}th percentile): {floor:.4f}")
    return floor

def find_similar_skus(query_sku_id, all_embeddings, meta_df, top_k=10, score_floor=None):
    """
    Finds top-K visually and attribute similar SKUs using the 4-tier cascade,
    soft boosts, and diagnostic checks.
    """
    query_sku_id = str(query_sku_id)
    query_row = meta_df[meta_df["ID"] == query_sku_id]
    if query_row.empty:
        query_row = meta_df[meta_df["SKU_GROUP"] == query_sku_id]
        if query_row.empty:
            print(f"Error: Query SKU {query_sku_id} not found in catalog metadata.")
            return [], None
    query_row = query_row.iloc[0]
    query_sku_id = str(query_row["ID"])
    
    # 1. Fetch query vectors in memory
    query_vectors = [item["embedding"] for item in all_embeddings if str(item["sku_id"]) == query_sku_id]
    if not query_vectors:
        print(f"Error: No image vectors found for query SKU {query_sku_id} in embeddings.")
        return [], query_row
        
    # Get attributes for cascade
    query_collar = str(query_row.get("COLLAR_NEW", "unknown")).lower()
    query_fit_normalized = str(query_row.get("FIT_NORMALIZED", "unknown")).lower()
    query_material = str(query_row.get("MATERIAL_NEW", "unknown")).lower()
    query_sku_group = str(query_row.get("SKU_GROUP", ""))
    query_category = str(query_row.get("CATEGORY", "T-Shirts"))
    
    # Pre-map SKU embeddings in memory
    sku_embeddings_map = {}
    for item in all_embeddings:
        sid = str(item["sku_id"])
        if sid not in sku_embeddings_map:
            sku_embeddings_map[sid] = []
        sku_embeddings_map[sid].append(item["embedding"])
        
    cfg = load_config()
    sim_cfg = cfg.get("similarity_search", {})
    soft_boost_damping = sim_cfg.get("soft_boost_damping", 0.20)
    
    # Calibrate floor if not provided
    if score_floor is None:
        percentile = sim_cfg.get("calibration_percentile", 10.0)
        score_floor = calibrate_score_floor(all_embeddings, meta_df, percentile)
        
    print(f"\nSearching for similar SKUs to: {query_sku_group} (Shopify ID: {query_sku_id})")
    print(f"Calibrated Score Floor: {score_floor:.4f}")
    
    # 2. Run cascade search entirely in-memory using Pandas
    accepted_skus = {}
    evaluated_sku_ids = set()
    all_evaluated_candidates = []
    
    soft_attrs = ["SLEEVE_TYPE", "CLOSURE", "POCKET", "STYLE", "FABRIC_WEIGHT", "COMPOSITION", "OCCASSION_NEW", "FIT"]
    multipliers = {1: 1.0, 2: 0.8, 3: 0.6, 4: 0.4}
    tier_tags = {
        1: "collar+fit+material",
        2: "collar+fit",
        3: "collar",
        4: "category"
    }
    
    # Exclude query SKU, match Category and Status = eligible (Tier 0 filter)
    tier0_df = meta_df[
        (meta_df["ID"] != query_sku_id) &
        (meta_df["CATEGORY"] == query_category) &
        (meta_df["STATUS_ELIGIBLE"].astype(str).str.lower() == "true")
    ]
    
    for level in [1, 2, 3, 4]:
        # Filter candidates for this level
        if level == 1:
            level_df = tier0_df[
                (tier0_df["COLLAR_NEW"].astype(str).str.lower() == query_collar) &
                (tier0_df["FIT_NORMALIZED"].astype(str).str.lower() == query_fit_normalized) &
                (tier0_df["MATERIAL_NEW"].astype(str).str.lower() == query_material)
            ]
        elif level == 2:
            level_df = tier0_df[
                (tier0_df["COLLAR_NEW"].astype(str).str.lower() == query_collar) &
                (tier0_df["FIT_NORMALIZED"].astype(str).str.lower() == query_fit_normalized)
            ]
        elif level == 3:
            level_df = tier0_df[
                (tier0_df["COLLAR_NEW"].astype(str).str.lower() == query_collar)
            ]
        else:
            level_df = tier0_df
            
        candidate_ids = set(level_df["ID"].astype(str).tolist())
        
        # Set difference: newly exposed SKUs at this level
        new_sku_ids = candidate_ids - evaluated_sku_ids
        evaluated_sku_ids.update(new_sku_ids)
        
        if not new_sku_ids:
            continue
            
        # Score every newly exposed candidate SKU in the bucket
        for cand_id in new_sku_ids:
            cand_vecs = sku_embeddings_map.get(cand_id)
            if not cand_vecs:
                continue
                
            # Pairwise visual similarity
            sims = []
            for qv in query_vectors:
                for cv in cand_vecs:
                    norm_q = np.linalg.norm(qv)
                    norm_c = np.linalg.norm(cv)
                    if norm_q > 0 and norm_c > 0:
                        sims.append(np.dot(qv, cv) / (norm_q * norm_c))
            if not sims:
                continue
            avg_sim = float(np.mean(sims))
            
            # Fetch metadata row from meta_df
            cand_rows = meta_df[meta_df["ID"] == cand_id]
            if cand_rows.empty:
                continue
            cand_row = cand_rows.iloc[0]
            
            # Soft boosts (proportion of matched attributes)
            matched_soft_filters = []
            for attr in soft_attrs:
                q_val = str(query_row.get(attr, "unknown")).lower()
                c_val = str(cand_row.get(attr, "unknown")).lower()
                if q_val != "unknown" and q_val == c_val:
                    matched_soft_filters.append(attr)
                    
            soft_boost = len(matched_soft_filters) / len(soft_attrs)
            
            mult = multipliers[level]
            unmultiplied_score = avg_sim * (1.0 + soft_boost_damping * soft_boost)
            final_score = unmultiplied_score
            
            cand_sku_group = str(cand_row.get("SKU_GROUP", ""))
            match_type = "Obvious" if is_colorway_sibling(query_sku_group, cand_sku_group) else "Other"
            
            # Tier 3 prints agreement diagnostics
            q_designs = str(query_row.get("DESIGNS", "unknown")).lower()
            c_designs = str(cand_row.get("DESIGNS", "unknown")).lower()
            q_print = str(query_row.get("PRINT_DESIGN", "unknown")).lower()
            c_print = str(cand_row.get("PRINT_DESIGN", "unknown")).lower()
            designs_match = (q_designs != "unknown") and (q_designs == c_designs)
            print_match = (q_print != "unknown") and (q_print == c_print)
            tier_3_diag = f"DESIGNS_match={designs_match}, PRINT_DESIGN_match={print_match}"
            
            passed_criteria = (unmultiplied_score >= score_floor * mult) and (avg_sim >= 0.60)
            
            eval_record = {
                # Query SKU details in each row for flat Excel export
                "QUERY_SKU_GROUP": query_sku_group,
                "QUERY_PRODUCT_NAME": str(query_row.get("PRODUCT_NAME", "Unknown")),
                "QUERY_IMAGE_LINK_1": str(query_row.get("IMAGE_1", "")),
                "QUERY_IMAGE_LINK_2": str(query_row.get("IMAGE_2", "")),
                "QUERY_COLLAR": str(query_row.get("COLLAR_NEW", "unknown")),
                "QUERY_FIT": str(query_row.get("FIT", "unknown")),
                "QUERY_FIT_NORMALIZED": str(query_row.get("FIT_NORMALIZED", "unknown")),
                "QUERY_MATERIAL": str(query_row.get("MATERIAL_NEW", "unknown")),
                "QUERY_SLEEVE_TYPE": str(query_row.get("SLEEVE_TYPE", "unknown")),
                "QUERY_CLOSURE": str(query_row.get("CLOSURE", "unknown")),
                "QUERY_POCKET": str(query_row.get("POCKET", "unknown")),
                "QUERY_STYLE": str(query_row.get("STYLE", "unknown")),
                "QUERY_FABRIC_WEIGHT": str(query_row.get("FABRIC_WEIGHT", "unknown")),
                "QUERY_COMPOSITION": str(query_row.get("COMPOSITION", "unknown")),
                "QUERY_OCCASION": str(query_row.get("OCCASSION_NEW", "unknown")),
                "QUERY_DESIGNS": str(query_row.get("DESIGNS", "unknown")),
                "QUERY_PRINT_DESIGN": str(query_row.get("PRINT_DESIGN", "unknown")),

                # Candidate SKU details
                "CANDIDATE_SKU_GROUP": cand_sku_group,
                "CANDIDATE_PRODUCT_NAME": str(cand_row.get("PRODUCT_NAME", "Unknown")),
                "CANDIDATE_IMAGE_LINK_1": str(cand_row.get("IMAGE_1", "")),
                "CANDIDATE_IMAGE_LINK_2": str(cand_row.get("IMAGE_2", "")),
                "CANDIDATE_COLLAR": str(cand_row.get("COLLAR_NEW", "unknown")),
                "CANDIDATE_FIT": str(cand_row.get("FIT", "unknown")),
                "CANDIDATE_FIT_NORMALIZED": str(cand_row.get("FIT_NORMALIZED", "unknown")),
                "CANDIDATE_MATERIAL": str(cand_row.get("MATERIAL_NEW", "unknown")),
                "CANDIDATE_SLEEVE_TYPE": str(cand_row.get("SLEEVE_TYPE", "unknown")),
                "CANDIDATE_CLOSURE": str(cand_row.get("CLOSURE", "unknown")),
                "CANDIDATE_POCKET": str(cand_row.get("POCKET", "unknown")),
                "CANDIDATE_STYLE": str(cand_row.get("STYLE", "unknown")),
                "CANDIDATE_FABRIC_WEIGHT": str(cand_row.get("FABRIC_WEIGHT", "unknown")),
                "CANDIDATE_COMPOSITION": str(cand_row.get("COMPOSITION", "unknown")),
                "CANDIDATE_OCCASION": str(cand_row.get("OCCASSION_NEW", "unknown")),
                "CANDIDATE_DESIGNS": str(cand_row.get("DESIGNS", "unknown")),
                "CANDIDATE_PRINT_DESIGN": str(cand_row.get("PRINT_DESIGN", "unknown")),

                # Scoring and metadata
                "FINAL_SCORE": final_score,
                "VISUAL_SIMILARITY": avg_sim,
                "TIER_CONFIDENCE_MULTIPLIER": mult,
                "SOFT_MATCH_BOOST": 1.0 + soft_boost_damping * soft_boost,
                "TIGHTEST_TIER_TAG": tier_tags[level],
                "SOFT_FILTERS_MATCHED": matched_soft_filters,
                "TIER_3_DIAGNOSTIC": tier_3_diag,
                "MRP_BUCKET": str(cand_row.get("MRP_BUCKET", "unknown")),
                "COLOR": str(cand_row.get("COLOR", "unknown")),
                "GP": float(cand_row.get("GP", 0.0)),
                "MATCH_TYPE": match_type,
                "PASSED_FLOOR": passed_criteria
            }
            all_evaluated_candidates.append(eval_record)
            
            if passed_criteria:
                accepted_skus[cand_id] = eval_record
                
        # Log level candidates count and proceed to evaluate all tiers exhaustively
        print(f"Level {level}: found {len(accepted_skus)} candidates clearing the floor so far.")
            
    # Save history to logs
    os.makedirs("logs", exist_ok=True)
    log_path = "logs/full_retrieval_log.json"
    try:
        with open(log_path, "w") as f:
            json.dump({
                "query_sku_id": query_sku_id,
                "query_sku_group": query_sku_group,
                "calibrated_floor": score_floor,
                "evaluated_candidates": all_evaluated_candidates
            }, f, indent=2)
    except Exception as e:
        print(f"Warning: Failed to log candidates: {e}")
        
    sorted_accepted = sorted(accepted_skus.values(), key=lambda x: (-x["VISUAL_SIMILARITY"], -x["FINAL_SCORE"]))
    top_matches = sorted_accepted[:top_k]
    return top_matches, query_row

def print_tiered_search_results(query_row, top_matches):
    """Formats and prints search results in query SKU header block and candidate rows format."""
    print("====================================================================================================")
    print("QUERY SKU DETAILS:")
    print(f"  SKU_GROUP: {query_row.get('SKU_GROUP', 'Unknown')}")
    print(f"  PRODUCT_NAME: {query_row.get('PRODUCT_NAME', 'Unknown')}")
    
    attrs = ["COLLAR_NEW", "FIT", "FIT_NORMALIZED", "MATERIAL_NEW", "SLEEVE_TYPE", "CLOSURE", "POCKET", "STYLE", "FABRIC_WEIGHT", "COMPOSITION", "OCCASSION_NEW", "DESIGNS", "PRINT_DESIGN"]
    attr_strs = []
    for a in attrs:
        attr_strs.append(f"{a}={query_row.get(a, 'unknown')}")
    print(f"  ATTRIBUTES: {' | '.join(attr_strs)}")
    print("====================================================================================================")
    
    print(f"{'#':<3} | {'CAND_SKU_GROUP':<15} | {'PRODUCT_NAME':<35} | {'SCORE':<7} | {'VIS_SIM':<7} | {'TIER_MULT':<9} | {'BOOST':<7} | {'TIER':<20} | {'MATCH_TYPE':<10}")
    print("-" * 140)
    for idx, m in enumerate(top_matches, 1):
        name = m['CANDIDATE_PRODUCT_NAME']
        if len(name) > 35:
            name = name[:32] + "..."
        print(f"{idx:<3} | {m['CANDIDATE_SKU_GROUP']:<15} | {name:<35} | {m['FINAL_SCORE']:.4f} | {m['VISUAL_SIMILARITY']:.4f} | {m['TIER_CONFIDENCE_MULTIPLIER']:.2f} | {m['SOFT_MATCH_BOOST']:.4f} | {m['TIGHTEST_TIER_TAG']:<20} | {m['MATCH_TYPE']:<10}")
        print(f"    Shopify Image Links: {m['CANDIDATE_IMAGE_LINK_1']} | {m['CANDIDATE_IMAGE_LINK_2']}")
        print(f"    Soft Matches: {m['SOFT_FILTERS_MATCHED']}")
        print(f"    Diagnostic: {m['TIER_3_DIAGNOSTIC']} | MRP Bucket: {m['MRP_BUCKET']} | Color: {m['COLOR']} | GP: {m['GP']:.2f}")
        print("-" * 140)

def format_search_results_for_export(query_row, top_matches):
    """
    Formats query SKU and candidate SKUs side-by-side into the flat tabular layout
    with the exact columns required for Excel/CSV export.
    """
    cols = [
        "STATUS", "SKU_GROUP", "PRODUCT_NAME", "MATCH_TYPE", "FINAL_SCORE", 
        "VISUAL_SIMILARITY", "TIER_CONFIDENCE_MULTIPLIER", "SOFT_MATCH_BOOST", 
        "TIGHTEST_TIER_TAG", "SOFT_FILTERS_MATCHED", "TIER_3_DIAGNOSTIC", 
        "IMAGE_LINK_1", "IMAGE_LINK_2", "MRP_BUCKET", "COLOR", "GP", 
        "COLLAR", "FIT_NORMALIZED", "MATERIAL", "SLEEVE_TYPE", "CLOSURE", 
        "POCKET", "STYLE", "FABRIC_WEIGHT", "COMPOSITION", "OCCASION", 
        "DESIGNS", "PRINT_DESIGN", "PASSED_FLOOR"
    ]
    
    rows = []
    
    # 1. Query SKU row
    q_row = {col: "" for col in cols}
    q_row["STATUS"] = "Query"
    q_row["SKU_GROUP"] = str(query_row.get("SKU_GROUP", ""))
    q_row["PRODUCT_NAME"] = str(query_row.get("PRODUCT_NAME", ""))
    q_row["IMAGE_LINK_1"] = str(query_row.get("IMAGE_1", ""))
    q_row["IMAGE_LINK_2"] = str(query_row.get("IMAGE_2", ""))
    q_row["MRP_BUCKET"] = str(query_row.get("MRP_BUCKET", ""))
    q_row["COLOR"] = str(query_row.get("COLOR", ""))
    
    try:
        q_row["GP"] = float(query_row.get("GP", 0.0))
    except Exception:
        q_row["GP"] = 0.0
        
    q_row["COLLAR"] = str(query_row.get("COLLAR_NEW", "unknown"))
    q_row["FIT_NORMALIZED"] = str(query_row.get("FIT_NORMALIZED", "unknown"))
    q_row["MATERIAL"] = str(query_row.get("MATERIAL_NEW", "unknown"))
    q_row["SLEEVE_TYPE"] = str(query_row.get("SLEEVE_TYPE", "unknown"))
    q_row["CLOSURE"] = str(query_row.get("CLOSURE", "unknown"))
    q_row["POCKET"] = str(query_row.get("POCKET", "unknown"))
    q_row["STYLE"] = str(query_row.get("STYLE", "unknown"))
    q_row["FABRIC_WEIGHT"] = str(query_row.get("FABRIC_WEIGHT", "unknown"))
    q_row["COMPOSITION"] = str(query_row.get("COMPOSITION", "unknown"))
    q_row["OCCASION"] = str(query_row.get("OCCASSION_NEW", "unknown"))
    q_row["DESIGNS"] = str(query_row.get("DESIGNS", "unknown"))
    q_row["PRINT_DESIGN"] = str(query_row.get("PRINT_DESIGN", "unknown"))
    q_row["PASSED_FLOOR"] = "" # Empty for query
    
    rows.append(q_row)
    
    # 2. Candidate rows
    for m in top_matches:
        c_row = {}
        c_row["STATUS"] = "Candidate"
        c_row["SKU_GROUP"] = m["CANDIDATE_SKU_GROUP"]
        c_row["PRODUCT_NAME"] = m["CANDIDATE_PRODUCT_NAME"]
        c_row["MATCH_TYPE"] = m["MATCH_TYPE"]
        c_row["FINAL_SCORE"] = m["FINAL_SCORE"]
        c_row["VISUAL_SIMILARITY"] = m["VISUAL_SIMILARITY"]
        c_row["TIER_CONFIDENCE_MULTIPLIER"] = m["TIER_CONFIDENCE_MULTIPLIER"]
        c_row["SOFT_MATCH_BOOST"] = m["SOFT_MATCH_BOOST"]
        c_row["TIGHTEST_TIER_TAG"] = m["TIGHTEST_TIER_TAG"]
        
        sf = m["SOFT_FILTERS_MATCHED"]
        c_row["SOFT_FILTERS_MATCHED"] = ", ".join(sf) if isinstance(sf, list) else str(sf)
        
        c_row["TIER_3_DIAGNOSTIC"] = m["TIER_3_DIAGNOSTIC"]
        c_row["IMAGE_LINK_1"] = m["CANDIDATE_IMAGE_LINK_1"]
        c_row["IMAGE_LINK_2"] = m["CANDIDATE_IMAGE_LINK_2"]
        c_row["MRP_BUCKET"] = m["MRP_BUCKET"]
        c_row["COLOR"] = m["COLOR"]
        c_row["GP"] = m["GP"]
        c_row["COLLAR"] = m["CANDIDATE_COLLAR"]
        c_row["FIT_NORMALIZED"] = m["CANDIDATE_FIT_NORMALIZED"]
        c_row["MATERIAL"] = m["CANDIDATE_MATERIAL"]
        c_row["SLEEVE_TYPE"] = m["CANDIDATE_SLEEVE_TYPE"]
        c_row["CLOSURE"] = m["CANDIDATE_CLOSURE"]
        c_row["POCKET"] = m["CANDIDATE_POCKET"]
        c_row["STYLE"] = m["CANDIDATE_STYLE"]
        c_row["FABRIC_WEIGHT"] = m["CANDIDATE_FABRIC_WEIGHT"]
        c_row["COMPOSITION"] = m["CANDIDATE_COMPOSITION"]
        c_row["OCCASION"] = m["CANDIDATE_OCCASION"]
        c_row["DESIGNS"] = m["CANDIDATE_DESIGNS"]
        c_row["PRINT_DESIGN"] = m["CANDIDATE_PRINT_DESIGN"]
        c_row["PASSED_FLOOR"] = str(m["PASSED_FLOOR"])
        
        rows.append(c_row)
        
    # 3. Append blank row
    blank_row = {col: "" for col in cols}
    rows.append(blank_row)
    
    return rows

def append_to_excel(file_path, cols, new_rows):
    """
    Appends new query search result rows to an Excel workbook sheet, creating it if needed.
    Ensures exactly one blank row separates different queries and styles links to open on a single click.
    """
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    
    if os.path.exists(file_path):
        try:
            wb = openpyxl.load_workbook(file_path)
            ws = wb.active
        except Exception:
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.append(cols)
            header_font = Font(name="Calibri", size=11, bold=True)
            for col_idx in range(1, len(cols) + 1):
                cell = ws.cell(row=1, column=col_idx)
                cell.font = header_font
                cell.alignment = Alignment(horizontal="center")
    else:
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(cols)
        header_font = Font(name="Calibri", size=11, bold=True)
        for col_idx in range(1, len(cols) + 1):
            cell = ws.cell(row=1, column=col_idx)
            cell.font = header_font
            cell.alignment = Alignment(horizontal="center")
            
    # Find start row (next empty row)
    start_row = ws.max_row + 1
    
    # Check if the last row of the sheet is completely empty
    is_last_row_empty = True
    if ws.max_row > 1:
        for col_idx in range(1, len(cols) + 1):
            val = ws.cell(row=ws.max_row, column=col_idx).value
            if val is not None and str(val).strip() != "":
                is_last_row_empty = False
                break
        if not is_last_row_empty:
            # Leave one empty row between blocks
            start_row = ws.max_row + 2
        else:
            # Re-use the existing empty row at the end
            start_row = ws.max_row
            
    link_font = Font(name="Calibri", size=11, color="0563C1", underline="single")
    default_font = Font(name="Calibri", size=11)
    
    current_row = start_row
    for r_data in new_rows:
        # Check if it is a blank spacer row (we represent this as dict of empty strings)
        is_row_blank = all(str(r_data.get(col, "")).strip() == "" for col in cols)
        if is_row_blank:
            current_row += 1
            continue
            
        for col_idx, col in enumerate(cols, 1):
            val = r_data.get(col, "")
            cell = ws.cell(row=current_row, column=col_idx)
            
            # Format image links as single-click hyperlinks
            if col in ["IMAGE_LINK_1", "IMAGE_LINK_2"]:
                if val and str(val).startswith("http"):
                    cell.value = str(val)
                    cell.hyperlink = str(val)
                    cell.font = link_font
                else:
                    cell.value = str(val)
                    cell.font = default_font
            else:
                cell.value = val
                cell.font = default_font
                
            # Alignments and number formats
            if col in ["STATUS", "SKU_GROUP", "MATCH_TYPE", "TIGHTEST_TIER_TAG", "PASSED_FLOOR", "MRP_BUCKET", "COLOR"]:
                cell.alignment = Alignment(horizontal="center")
            elif col in ["FINAL_SCORE", "VISUAL_SIMILARITY", "TIER_CONFIDENCE_MULTIPLIER", "SOFT_MATCH_BOOST", "GP"]:
                cell.alignment = Alignment(horizontal="right")
                if val != "":
                    try:
                        f_val = float(val)
                        cell.value = f_val
                        if col in ["FINAL_SCORE", "VISUAL_SIMILARITY", "SOFT_MATCH_BOOST"]:
                            cell.number_format = "0.0000"
                        elif col == "TIER_CONFIDENCE_MULTIPLIER":
                            cell.number_format = "0.0"
                        elif col == "GP":
                            cell.number_format = "#,##0.00"
                    except Exception:
                        pass
            else:
                cell.alignment = Alignment(horizontal="left")
                
        current_row += 1
        
    # Auto-fit columns to prevent clipped content
    for col_cells in ws.columns:
        max_len = 0
        for cell in col_cells:
            if cell.value:
                max_len = max(max_len, len(str(cell.value)))
        col_letter = openpyxl.utils.get_column_letter(col_cells[0].column)
        ws.column_dimensions[col_letter].width = max(max_len + 3, 12)
        
    try:
        wb.save(file_path)
    finally:
        wb.close()

def run_retrieval_sanity_check(num_checks=3):
    """Sanity checks the retriever by querying a few random SKUs and printing matches."""
    print(f"\n--- Running Vector Store Similarity Search Sanity Check ({num_checks} SKUs) ---")
    
    embeddings, df = load_data()
    sku_ids = list(set(item["sku_id"] for item in embeddings))
    
    if len(sku_ids) < 2:
        print("Not enough SKUs to query.")
        return
        
    np.random.seed(42)
    targets = np.random.choice(sku_ids, min(num_checks, len(sku_ids)), replace=False)
    
    for target in targets:
        top_matches, query_row = find_similar_skus(target, embeddings, df, top_k=10)
        if query_row is not None:
            print_tiered_search_results(query_row, top_matches)

def main():
    build_vector_store()
    run_retrieval_sanity_check()

if __name__ == "__main__":
    main()
