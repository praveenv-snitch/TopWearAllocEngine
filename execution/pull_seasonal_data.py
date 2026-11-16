# execution/pull_seasonal_data.py
import os
import sys
import pandas as pd

# Add the execution directory to path to import snowflake_client
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from snowflake_client import run_query

def pull_data():
    os.makedirs("data/raw", exist_ok=True)
    
    print("Executing Query 1: Daily units sold for T-Shirts...")
    query_units = """
        SELECT ORDER_DATE AS sale_date, SUM(SUBORDER_QUANTITY) AS total_units
        FROM snitch_db.maplemonk.image_search_sales_history
        WHERE CATEGORY_CLASS = 'T-Shirts'
          AND ORDER_DATE >= '2023-07-15'
        GROUP BY ORDER_DATE
        ORDER BY ORDER_DATE
    """
    try:
        df_units = run_query(query_units)
        units_path = "data/raw/daily_units.csv"
        df_units.to_csv(units_path, index=False)
        print(f"Saved daily units to {units_path} ({len(df_units)} rows)")
    except Exception as e:
        print(f"Error querying daily units: {e}")
        
    print("\nExecuting Query 2: Daily active stores...")
    query_stores = """
        SELECT sh.ORDER_DATE AS sale_date, COUNT(DISTINCT sh.BRANCH_CODE) AS active_stores
        FROM snitch_db.maplemonk.image_search_sales_history sh
        WHERE sh.ORDER_DATE >= '2023-07-15'
        GROUP BY sh.ORDER_DATE
        ORDER BY sh.ORDER_DATE
    """
    try:
        df_stores = run_query(query_stores)
        stores_path = "data/raw/daily_active_stores.csv"
        df_stores.to_csv(stores_path, index=False)
        print(f"Saved daily active stores to {stores_path} ({len(df_stores)} rows)")
    except Exception as e:
        print(f"Error querying active stores: {e}")

if __name__ == "__main__":
    pull_data()
