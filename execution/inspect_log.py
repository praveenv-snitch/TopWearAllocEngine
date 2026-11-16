# execution/inspect_log.py
import json

LOG_PATH = "logs/full_retrieval_log.json"

try:
    with open(LOG_PATH, "r") as f:
        data = json.load(f)
        
    print(f"Query SKU: {data.get('query_sku_group')}")
    print(f"Calibrated Floor: {data.get('score_floor')}")
    
    candidates = data.get("evaluated_candidates", [])
    print(f"Total evaluated candidates: {len(candidates)}")
    
    level_counts = {}
    passed_counts = {}
    
    for cand in candidates:
        lvl = cand.get("TIGHTEST_TIER_TAG")
        passed = cand.get("PASSED_FLOOR")
        
        level_counts[lvl] = level_counts.get(lvl, 0) + 1
        if passed:
            passed_counts[lvl] = passed_counts.get(lvl, 0) + 1
            
    print("\nCandidate counts by Level:")
    for lvl in ["collar+fit+material", "collar+fit", "collar", "category"]:
        print(f"  {lvl}:")
        print(f"    Total evaluated: {level_counts.get(lvl, 0)}")
        print(f"    Passed floor: {passed_counts.get(lvl, 0)}")
        
    print("\nTop 5 failed candidates at Level 2 (collar+fit):")
    lvl2_failed = [c for c in candidates if c.get("TIGHTEST_TIER_TAG") == "collar+fit" and not c.get("PASSED_FLOOR")]
    lvl2_failed = sorted(lvl2_failed, key=lambda x: -x["FINAL_SCORE"])
    for idx, c in enumerate(lvl2_failed[:5]):
        print(f"  {idx+1}. {c['CANDIDATE_SKU_GROUP']} - Score: {c['FINAL_SCORE']:.4f} (Vis: {c['VISUAL_SIMILARITY']:.4f}, Boost: {c['SOFT_MATCH_BOOST']:.4f})")
        
    print("\nTop 5 failed candidates at Level 3 (collar):")
    lvl3_failed = [c for c in candidates if c.get("TIGHTEST_TIER_TAG") == "collar" and not c.get("PASSED_FLOOR")]
    lvl3_failed = sorted(lvl3_failed, key=lambda x: -x["FINAL_SCORE"])
    for idx, c in enumerate(lvl3_failed[:5]):
        print(f"  {idx+1}. {c['CANDIDATE_SKU_GROUP']} - Score: {c['FINAL_SCORE']:.4f} (Vis: {c['VISUAL_SIMILARITY']:.4f}, Boost: {c['SOFT_MATCH_BOOST']:.4f})")

except Exception as e:
    print(f"Error inspecting log: {e}")
