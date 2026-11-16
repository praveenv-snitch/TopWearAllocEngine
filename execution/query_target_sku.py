# execution/query_target_sku.py
import os
import sys
import numpy as np
import pandas as pd

# Append current directory to path for imports
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from build_vector_store import find_similar_skus, print_tiered_search_results, load_data, format_search_results_for_export, append_to_excel

def run_query():
    # Load metadata and embeddings
    try:
        embeddings, df = load_data()
    except Exception as e:
        print(f"Error loading data: {e}")
        return
        
    # Target SKU Group
    target_group = "4PL003-04"

    
    # Find metadata row for target SKU Group to resolve Shopify ID
    target_rows = df[df["SKU_GROUP"] == target_group]
    if target_rows.empty:
        print(f"Error: Target SKU_GROUP {target_group} not found in catalog.")
        return
        
    target_row = target_rows.iloc[0]
    target_sku_id = str(target_row["ID"])
    
    # Execute tiered cascade search
    top_matches, query_row = find_similar_skus(target_sku_id, embeddings, df, top_k=10)
    
    # Print formatted output
    if query_row is not None:
        print_tiered_search_results(query_row, top_matches)
        
        if top_matches:
            formatted_rows = format_search_results_for_export(query_row, top_matches)
            
            cols = [
                "STATUS", "SKU_GROUP", "PRODUCT_NAME", "MATCH_TYPE", "FINAL_SCORE", 
                "VISUAL_SIMILARITY", "TIER_CONFIDENCE_MULTIPLIER", "SOFT_MATCH_BOOST", 
                "TIGHTEST_TIER_TAG", "SOFT_FILTERS_MATCHED", "TIER_3_DIAGNOSTIC", 
                "IMAGE_LINK_1", "IMAGE_LINK_2", "MRP_BUCKET", "COLOR", "GP", 
                "COLLAR", "FIT_NORMALIZED", "MATERIAL", "SLEEVE_TYPE", "CLOSURE", 
                "POCKET", "STYLE", "FABRIC_WEIGHT", "COMPOSITION", "OCCASION", 
                "DESIGNS", "PRINT_DESIGN", "PASSED_FLOOR"
            ]
            
            output_xlsx_path = "data/processed/query_target_sku_results.xlsx"
            append_to_excel(output_xlsx_path, cols, formatted_rows)
            print(f"\n[EXCEL EXPORT] Successfully appended results to: {output_xlsx_path}")

if __name__ == "__main__":
    run_query()
