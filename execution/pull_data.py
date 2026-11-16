# execution/pull_data.py
import os
import pandas as pd
from snowflake_client import run_query

# Actual table names
SKU_MASTER_TABLE = "snitch_db.maplemonk.image_search_master"
SALES_HISTORY_TABLE = "snitch_db.maplemonk.image_search_sales_history"
STORE_MASTER_TABLE = "SNITCH_DB.MAPLEMONK.IMAGE_SEARCH_STORE_MASTER"

# Scoped pilot parameters (branch codes 63 and 25)
PILOT_STORES = ("63", "25")
CATEGORY_FILTER = "T-Shirts"

def ensure_raw_directory():
    """Ensures that the data/raw directory exists."""
    os.makedirs("data/raw", exist_ok=True)

def pull_store_master():
    """Pulls store master details for the pilot stores (branch codes 63 and 25)."""
    print("Pulling store master...")
    store_list_sql = ", ".join([f"'{s}'" for s in PILOT_STORES])
    query = f"""
        SELECT * 
        FROM {STORE_MASTER_TABLE} 
        WHERE branch_code IN ({store_list_sql})
    """
    df = run_query(query)
    out_path = "data/raw/store_master.csv"
    df.to_csv(out_path, index=False)
    print(f"Successfully saved store master to {out_path} ({len(df)} rows).")
    return df

def pull_sku_master():
    """Pulls all T-shirt SKUs with all columns."""
    print("Pulling SKU master...")
    # Using ILIKE to match variations like 'T-Shirt', 'T-Shirts', 't-shirt'
    query = f"""
        SELECT * 
        FROM {SKU_MASTER_TABLE}
        WHERE category ILIKE '%T-Shirt%'
    """
    df = run_query(query)
    out_path = "data/raw/sku_master.csv"
    df.to_csv(out_path, index=False)
    print(f"Successfully saved SKU master to {out_path} ({len(df)} rows).")
    
    # Dynamically extract and save attribute fill rates as a separate file
    extract_attribute_fill_rates(df)
    
    return df

def extract_attribute_fill_rates(sku_df):
    """Extracts columns ending in _FILL_RATE (except RISE_FILL_RATE) and saves them separately."""
    print("Extracting attribute fill rates from SKU master...")
    fill_rate_cols = [
        col for col in sku_df.columns 
        if col.upper().endswith("_FILL_RATE") and col.upper() != "RISE_FILL_RATE"
    ]
    
    if not fill_rate_cols:
        print("Warning: No *_FILL_RATE columns found in SKU master.")
        return
        
    print(f"Found fill-rate columns: {fill_rate_cols}")
    # Key by SKU_GROUP as per directive
    cols_to_extract = ["SKU_GROUP"] + fill_rate_cols
    # Filter out columns that might not exist, just in case
    cols_to_extract = [c for c in cols_to_extract if c in sku_df.columns]
    
    fill_rate_df = sku_df[cols_to_extract].drop_duplicates()
    out_path = "data/raw/attribute_fill_rates.csv"
    fill_rate_df.to_csv(out_path, index=False)
    print(f"Successfully saved attribute fill rates to {out_path} ({len(fill_rate_df)} rows).")

def pull_sales_history():
    """Pulls sales history for the Kerala pilot stores only."""
    print("Pulling sales history...")
    store_list_sql = ", ".join([f"'{s}'" for s in PILOT_STORES])
    query = f"""
        SELECT * 
        FROM {SALES_HISTORY_TABLE}
        WHERE branch_code IN ({store_list_sql})
    """
    df = run_query(query)
    out_path = "data/raw/sales_history.csv"
    df.to_csv(out_path, index=False)
    print(f"Successfully saved sales history to {out_path} ({len(df)} rows).")
    return df

if __name__ == "__main__":
    ensure_raw_directory()
    pull_store_master()
    pull_sku_master()
    pull_sales_history()
