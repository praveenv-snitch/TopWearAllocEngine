# execution/snowflake_client.py
import os
import snowflake.connector
import pandas as pd
from dotenv import load_dotenv

# Load env variables from .env in the project root
load_dotenv()

def get_connection():
    """Establishes and returns a Snowflake connection using environment variables."""
    return snowflake.connector.connect(
        user=os.getenv("SNOWFLAKE_USER"),
        password=os.getenv("SNOWFLAKE_PASSWORD"),
        account=os.getenv("SNOWFLAKE_ACCOUNT"),
        warehouse=os.getenv("SNOWFLAKE_WAREHOUSE"),
        database=os.getenv("SNOWFLAKE_DATABASE"),
        schema=os.getenv("SNOWFLAKE_SCHEMA"),
    )

def run_query(query: str) -> pd.DataFrame:
    """Executes a SQL query and returns the results as a pandas DataFrame."""
    conn = get_connection()
    try:
        df = pd.read_sql(query, conn)
        return df
    finally:
        conn.close()
