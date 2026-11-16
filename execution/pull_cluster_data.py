# execution/pull_cluster_data.py
import os
import sys
import pandas as pd

# Add the execution directory to path to import snowflake_client
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from snowflake_client import run_query

def pull_data():
    os.makedirs("data/raw", exist_ok=True)
    
    print("Executing Query 1: Daily units and active stores grouped by ZONE and CLUSTER...")
    query_cluster_demand = """
        SELECT 
            sh.ORDER_DATE AS sale_date, 
            sm.ZONE AS zone_name,
            sm.CLUSTER AS cluster_name, 
            SUM(sh.SUBORDER_QUANTITY) AS total_units,
            COUNT(DISTINCT sh.BRANCH_CODE) AS active_stores
        FROM snitch_db.maplemonk.image_search_sales_history sh
        JOIN SNITCH_DB.MAPLEMONK.IMAGE_SEARCH_STORE_MASTER sm 
            ON sh.BRANCH_CODE = sm.BRANCH_CODE
            AND sm.CATEGORY = 'T-Shirts'
        WHERE sh.CATEGORY_CLASS = 'T-Shirts'
          AND sh.ORDER_DATE >= '2023-07-15'
        GROUP BY sh.ORDER_DATE, sm.ZONE, sm.CLUSTER
        ORDER BY sh.ORDER_DATE, sm.ZONE, sm.CLUSTER
    """
    try:
        df_demand = run_query(query_cluster_demand)
        out_path = "data/raw/cluster_daily_demand.csv"
        df_demand.to_csv(out_path, index=False)
        print(f"Saved cluster daily demand data to {out_path} ({len(df_demand)} rows)")
    except Exception as e:
        print(f"Error querying cluster daily demand: {e}")
        
    print("\nExecuting Query 2: All store-to-cluster-to-zone mappings...")
    query_store_mappings = """
        SELECT DISTINCT BRANCH_CODE, CLUSTER, ZONE
        FROM SNITCH_DB.MAPLEMONK.IMAGE_SEARCH_STORE_MASTER
    """
    try:
        df_stores = run_query(query_store_mappings)
        stores_path = "data/raw/all_store_clusters.csv"
        df_stores.to_csv(stores_path, index=False)
        print(f"Saved all store-to-cluster mappings to {stores_path} ({len(df_stores)} rows)")
    except Exception as e:
        print(f"Error querying store-to-cluster mappings: {e}")

if __name__ == "__main__":
    pull_data()
