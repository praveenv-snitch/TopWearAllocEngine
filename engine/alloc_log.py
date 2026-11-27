"""Saved allocations + store rules (merchandiser remarks).

The live copies sit in Workers KV (written by the dashboard through the Worker API, `alloc:<id>` expires 35 days after
saving, `rule:<id>` carries the rule in its metadata). Each build:
  1. reads them from KV (Cloudflare API) - or from TW_ALLOCS_FILE (JSON) in development,
  2. mirrors them into SNITCH_DB.MAPLEMONK.TW_ALLOC_LOG / TW_ALLOC_RULES (full replace, so the 35-day purge follows KV),
  3. returns daily offline sales since each allocation date (engine/sql/alloc_perf.sql) for the Saved allocations tab.
Every step is best effort: a failure prints a warning and the dashboard still builds (performance then shows "no data").
"""
import json
import os
import re
from datetime import datetime, timedelta, timezone

import requests

from engine import config as C

IST = timezone(timedelta(hours=5, minutes=30))
LOG_T = "SNITCH_DB.MAPLEMONK.TW_ALLOC_LOG"
RULE_T = "SNITCH_DB.MAPLEMONK.TW_ALLOC_RULES"
ID_RE = re.compile(r"^[a-z0-9]{6,32}$")
SKU_RE = re.compile(r"^[A-Z0-9_-]{1,40}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
KEEP_DAYS = 35


def _kv(path, **params):
    url = ("https://api.cloudflare.com/client/v4/accounts/%s/storage/kv/namespaces/%s/%s"
           % (C.CF_ACCOUNT_ID.strip(), C.CF_KV_NAMESPACE_ID.strip(), path))
    r = requests.get(url, params=params, headers={"Authorization": "Bearer " + C.CF_API_TOKEN.strip()}, timeout=60)
    r.raise_for_status()
    return r


def _kv_keys(prefix):
    keys, cursor = [], None
    while True:
        j = _kv("keys", prefix=prefix, limit=1000, **({"cursor": cursor} if cursor else {})).json()
        keys += j.get("result", [])
        cursor = (j.get("result_info") or {}).get("cursor")
        if not cursor:
            return keys


def read():
    """-> (allocs [{id, meta, lines}], rules [{id, meta, exp}])"""
    dev = os.environ.get("TW_ALLOCS_FILE")
    if dev:
        j = json.load(open(dev))
        return j.get("allocs", []), j.get("rules", [])
    if not (C.CF_ACCOUNT_ID and C.CF_API_TOKEN and C.CF_KV_NAMESPACE_ID):
        return [], []
    allocs = []
    for k in _kv_keys("alloc:"):
        aid = k["name"][len("alloc:"):]
        if not ID_RE.match(aid):
            continue
        try:
            v = _kv("values/" + k["name"]).json()
            allocs.append({"id": aid, "meta": v.get("meta", {}), "lines": v.get("lines", [])})
        except Exception as e:                               # expired between list and get, or malformed
            print("  saved allocation %s skipped (%s)" % (aid, e))
    rules = [{"id": k["name"][len("rule:"):], "meta": k.get("metadata") or {}, "exp": k.get("expiration")}
             for k in _kv_keys("rule:") if ID_RE.match(k["name"][len("rule:"):])]
    return allocs, rules


def _clean(allocs):
    """Validated (alloc_id, name, date, by, bc, sku, type, pack, units, ros, ev, have) rows within the last 35 days."""
    cutoff = (datetime.now(IST) - timedelta(days=KEEP_DAYS)).strftime("%Y-%m-%d")
    rows = []
    for a in allocs:
        m = a.get("meta") or {}
        d = str(m.get("date", ""))
        if not ID_RE.match(a.get("id", "")) or not DATE_RE.match(d) or d < cutoff:
            continue
        for l in a.get("lines") or []:
            sku = str(l.get("sku", "")).upper()
            try:
                bc = int(l.get("bc"))
            except (TypeError, ValueError):
                continue
            if not SKU_RE.match(sku):
                continue
            rows.append((a["id"], str(m.get("name", ""))[:120], d, str(m.get("by", ""))[:40], bc, sku,
                         str(l.get("type", ""))[:10], str(l.get("pack", ""))[:10], int(l.get("units") or 0),
                         float(l.get("ros") or 0), int(l.get("ev") or 0), int(l.get("have") or 0)))
    return rows


def _mirror(cur, rows, rules):
    cur.execute("""CREATE TABLE IF NOT EXISTS %s (ALLOC_ID VARCHAR, ALLOC_NAME VARCHAR, ALLOC_DATE DATE, SAVED_BY VARCHAR,
        BC NUMBER, SKU VARCHAR, LINE_TYPE VARCHAR, PACK_TYPE VARCHAR, UNITS NUMBER, PROJ_ROS FLOAT, EVIDENCE NUMBER,
        HAVE_BEFORE NUMBER, SYNCED_AT TIMESTAMP_LTZ)""" % LOG_T)
    cur.execute("""CREATE TABLE IF NOT EXISTS %s (RULE_ID VARCHAR, BC NUMBER, RULE_TYPE VARCHAR, RULE_VALUE VARCHAR,
        SKU VARCHAR, CATEGORY VARCHAR, REMARK VARCHAR, CREATED_BY VARCHAR, ALLOC_ID VARCHAR, STORE VARCHAR,
        CREATED_AT TIMESTAMP_LTZ, EXPIRES_AT TIMESTAMP_LTZ, SYNCED_AT TIMESTAMP_LTZ)""" % RULE_T)
    cur.execute("BEGIN")
    cur.execute("DELETE FROM %s" % LOG_T)
    if rows:
        cur.executemany("INSERT INTO %s (ALLOC_ID, ALLOC_NAME, ALLOC_DATE, SAVED_BY, BC, SKU, LINE_TYPE, PACK_TYPE, UNITS,"
                        " PROJ_ROS, EVIDENCE, HAVE_BEFORE, SYNCED_AT) VALUES (%%s, %%s, %%s, %%s, %%s, %%s, %%s, %%s, %%s,"
                        " %%s, %%s, %%s, CURRENT_TIMESTAMP())" % LOG_T, rows)
    cur.execute("DELETE FROM %s" % RULE_T)
    rr = []
    for r in rules:
        m = r.get("meta") or {}
        try:
            bc = int(m.get("bc"))
        except (TypeError, ValueError):
            continue
        ts = lambda v: datetime.fromtimestamp(v, timezone.utc).strftime("%Y-%m-%d %H:%M:%S") if v else None
        rr.append((r["id"], bc, str(m.get("type", "")), str(m.get("value", "")), str(m.get("sku", "")), str(m.get("cat", "")),
                   str(m.get("text", "")), str(m.get("by", "")), str(m.get("alloc", "")), str(m.get("store", "")),
                   ts((m.get("created") or 0) / 1000), ts(r.get("exp"))))
    if rr:
        cur.executemany("INSERT INTO %s (RULE_ID, BC, RULE_TYPE, RULE_VALUE, SKU, CATEGORY, REMARK, CREATED_BY, ALLOC_ID,"
                        " STORE, CREATED_AT, EXPIRES_AT, SYNCED_AT) VALUES (%%s, %%s, %%s, %%s, %%s, %%s, %%s, %%s, %%s,"
                        " %%s, %%s, %%s, CURRENT_TIMESTAMP())" % RULE_T, rr)
    cur.execute("COMMIT")


def _values_src(triples):
    """Inline source for alloc_perf.sql; every value was validated against a strict pattern above."""
    return "(SELECT column1 AS ALLOC_ID, column2 AS ALLOC_DATE, column3 AS BC, column4 AS SKU FROM VALUES %s)" % ", ".join(
        "('%s', '%s', %d, '%s')" % t for t in triples)


def build():
    """-> payload piece {perf: {asOf, a: {alloc_id: [[bc, sku, day_off, units, rev], ...]}}, rules: [...]}"""
    asof = (datetime.now(IST) - timedelta(days=1)).strftime("%Y-%m-%d")
    out = {"perf": {"asOf": asof, "a": {}}, "rules": []}
    try:
        allocs, rules = read()
    except Exception as e:
        print("  [warn] saved allocations not read from KV: %s" % e)
        return out
    now = datetime.now(timezone.utc).timestamp()
    out["rules"] = [r for r in rules if not r.get("exp") or r["exp"] > now]
    rows = _clean(allocs)
    print("  saved allocations: %d (%d lines) | store rules: %d" % (len({r[0] for r in rows}), len(rows), len(out["rules"])))
    if not rows and not out["rules"]:
        return out
    from engine.snowflake_io import connect
    from engine.config import SQL_PARAMS
    from engine.snowflake_io import SQL_DIR
    ctx = connect()
    try:
        cur = ctx.cursor()
        cur.execute("ALTER SESSION SET TIMEZONE = 'Asia/Kolkata'")      # CURRENT_DATE() = today in IST
        try:
            if os.environ.get("TW_NO_LOG_TABLES"):                     # development: never write test rows to MAPLEMONK
                raise RuntimeError("TW_NO_LOG_TABLES set")
            _mirror(cur, rows, out["rules"])
            srcs = [LOG_T]
        except Exception as e:                                          # no CREATE TABLE / INSERT rights: inline list
            try:
                cur.execute("ROLLBACK")
            except Exception:
                pass
            print("  [warn] log tables not written (%s) - performance from an inline list" % str(e)[:200])
            triples = sorted({(r[0], r[2], r[4], r[5]) for r in rows})
            srcs = [_values_src(triples[i:i + 4000]) for i in range(0, len(triples), 4000)]
        if not rows:
            return out
        tmpl = (SQL_DIR / "alloc_perf.sql").read_text()
        for src in srcs:
            cur.execute(tmpl.format(LOG_SRC=src, **SQL_PARAMS))
            for aid, bc, sku, off, u, rev in cur.fetchall():
                out["perf"]["a"].setdefault(aid, []).append([int(bc), sku, int(off), int(u or 0), int(round(float(rev or 0)))])
        print("  performance rows: %d" % sum(len(v) for v in out["perf"]["a"].values()))
    except Exception as e:
        print("  [warn] allocation performance not computed: %s" % str(e)[:300])
    finally:
        ctx.close()
    return out
