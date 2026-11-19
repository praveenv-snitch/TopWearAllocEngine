"""Snowflake connection (key-pair for GitHub Actions / Colab, OAuth token inside a Snowflake workspace) + SQL loader."""
import base64
import os
from pathlib import Path

import snowflake.connector

from engine import config as C

SQL_DIR = Path(__file__).parent / "sql"


def connect():
    if os.environ.get("SNOW_PRIVATE_KEY"):
        from cryptography.hazmat.primitives import serialization
        raw = os.environ["SNOW_PRIVATE_KEY"]
        pw = os.environ.get("SNOW_KEY_PASSPHRASE") or None
        pem = raw.encode() if "-----BEGIN" in raw else base64.b64decode(raw)
        pkey = serialization.load_pem_private_key(pem, password=pw.encode() if pw else None)
        pkb = pkey.private_bytes(encoding=serialization.Encoding.DER,
                                 format=serialization.PrivateFormat.PKCS8,
                                 encryption_algorithm=serialization.NoEncryption())
        return snowflake.connector.connect(
            user=C.SNOW_USER, account=C.SNOW_ACCOUNT, private_key=pkb,
            warehouse=C.SNOW_WH, database=C.SNOW_DB, schema=C.SNOW_SCHEMA,
            **({"role": C.SNOW_ROLE} if C.SNOW_ROLE else {}))
    tok_path = os.environ.get("SNOWFLAKE_TOKEN_FILE_PATH", "/snowflake/session/token")
    if not os.path.exists(tok_path):
        raise SystemExit("Snowflake creds missing: set SNOW_USER + SNOW_PRIVATE_KEY (env vars / GitHub secrets)")
    return snowflake.connector.connect(
        host=os.environ.get("SNOWFLAKE_HOST"), account=os.environ.get("SNOWFLAKE_ACCOUNT"),
        authenticator="oauth", token=open(tok_path).read().strip(),
        warehouse=C.SNOW_WH, database=C.SNOW_DB, schema=C.SNOW_SCHEMA,
        **({"role": os.environ["SNOWFLAKE_ROLE"]} if os.environ.get("SNOWFLAKE_ROLE") else {}))


def sql(name):
    """engine/sql/<name>.sql with the shared exclusion / category fragments filled in."""
    return (SQL_DIR / f"{name}.sql").read_text().format(**C.SQL_PARAMS)


def fetch_all(names):
    """Run every named dataset on one connection -> {name: DataFrame}."""
    out = {}
    ctx = connect()
    try:
        cur = ctx.cursor()
        for n in names:
            cur.execute(sql(n))
            out[n] = cur.fetch_pandas_all()
            print("  %-12s %7d rows" % (n, len(out[n])))
    finally:
        ctx.close()
    return out
