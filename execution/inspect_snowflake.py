import os
import snowflake.connector
from dotenv import load_dotenv

# Load env variables from .env
load_dotenv()

def get_connection():
    return snowflake.connector.connect(
        user=os.getenv("SNOWFLAKE_USER"),
        password=os.getenv("SNOWFLAKE_PASSWORD"),
        account=os.getenv("SNOWFLAKE_ACCOUNT"),
        warehouse=os.getenv("SNOWFLAKE_WAREHOUSE"),
        database=os.getenv("SNOWFLAKE_DATABASE"),
        schema=os.getenv("SNOWFLAKE_SCHEMA"),
    )

def inspect_database():
    print("Connecting to Snowflake...")
    conn = get_connection()
    cursor = conn.cursor()
    try:
        # Show tables in current schema
        print("Fetching table list...")
        cursor.execute("SHOW TABLES")
        tables = cursor.fetchall()
        print("\nTables found in schema:")
        for t in tables:
            print(f"- {t[1]} (rows: {t[4]})")
        
        # We know from decisions that store master table is IMAGE_SEARCH_STORE_MASTER.
        # Let's inspect its structure.
        target_tables = ["IMAGE_SEARCH_STORE_MASTER"]
        # Find other candidate tables for SKU master and Sales Fact
        sku_candidates = [t[1] for t in tables if "SKU" in t[1].upper()]
        sales_candidates = [t[1] for t in tables if "SALE" in t[1].upper() or "FACT" in t[1].upper()]
        
        all_inspect = target_tables + sku_candidates + sales_candidates
        # De-duplicate list
        all_inspect = list(dict.fromkeys(all_inspect))
        
        for table_name in all_inspect:
            print(f"\n--- Columns in {table_name} ---")
            try:
                cursor.execute(f"DESCRIBE TABLE {table_name}")
                columns = cursor.fetchall()
                for col in columns:
                    print(f"  {col[0]}: {col[1]}")
                
                # Fetch first 3 rows as sample
                cursor.execute(f"SELECT * FROM {table_name} LIMIT 3")
                sample = cursor.fetchall()
                print(f"  Sample row count: {len(sample)}")
                if sample:
                    print(f"  Sample row 1: {sample[0]}")
            except Exception as e:
                print(f"  Error describing table: {e}")
                
    finally:
        cursor.close()
        conn.close()

if __name__ == "__main__":
    inspect_database()
