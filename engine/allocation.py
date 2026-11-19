# Store health, mix deltas, neighbour-based demand projection and per-SKU store placements.
# The dashboard runs the final greedy allocation in the browser (editable weights / filters) using these placements.
import math
from datetime import date

import numpy as np
import pandas as pd

from . import config as C

U = ["U_" + s for s in C.SIZES]
W = ["W_" + s for s in C.SIZES]
SZ_SLOT = {s: i for i, s in enumerate(C.SIZES)}
SZ_SLOT["2XL"] = SZ_SLOT["XXL"]


# ---------------------------------------------------------------- product enrichment
def _meta(cat, collar, designs, style):
    d = str(designs or "").strip().upper()
    st = str(style or "")
    if cat == "T-SHIRTS":
        c = str(collar or "").strip().lower()
        m1 = "Round" if c in ("v neck", "crew", "round") else "Polo" if c == "polo" else "Others"
        m2 = ("Solid" if d == "SOLID" else "Self Design & Textured" if d in ("TEXTURED", "SELF DESIGN")
              else "Stripes" if d == "STRIPES" else "Checks" if d == "CHECKS"
              else "Embroided" if d in ("EMBROIDED", "EMBELLISHED")
              else "Graphic Print" if d in ("PRINTED", "GEOMETRIC", "FLORAL", "TIE & DYE", "ANIMAL PRINT", "GRAPHIC PRINT")
              else "Others")
        return m1, m2
    if "linen" in st.lower():
        return "Linen", "N/A"
    if "luxe" in st.lower():
        return "Snitch LUXE", "N/A"
    m1 = ("Solid" if d == "SOLID" else "Stripes" if d == "STRIPES"
          else "Self Design & Textured" if d in ("TEXTURED", "SELF DESIGN") else "Checks" if d == "CHECKS"
          else "Embroided" if d in ("EMBROIDED", "EMBELLISHED")
          else "Printed" if d in ("PRINTED", "FLORAL", "GEOMETRIC", "TIE & DYE", "GRAPHIC PRINT", "ANIMAL PRINT")
          else "Others")
    return m1, "N/A"


def enrich_products(prod, wh):
    today = pd.Timestamp(date.today())
    prod = prod.copy()
    mm = [_meta(r.CATEGORY, r.COLLAR_NEW, r.DESIGNS, r.STYLE) for r in prod.itertuples()]
    prod["META1"], prod["META2"] = [m[0] for m in mm], [m[1] for m in mm]
    prod["BUCKET"] = prod["META1"] + np.where(prod["META2"] == "N/A", "", " | " + prod["META2"])
    prod["MRP"] = pd.to_numeric(prod["MRP"], errors="coerce").fillna(0)
    prod["PRICE_TIER"] = prod["MRP"].map(C.price_tier)
    prod["COLOR_FAM"] = prod["COLOR"].map(C.color_family)
    for c in ("LIVE_DATE", "WH_LIVE_DATE", "FIRST_OFFLINE_SALE", "LAST_INWARD"):
        prod[c] = pd.to_datetime(prod[c], errors="coerce")
    prod["DAYS_LIVE"] = (today - prod["LIVE_DATE"]).dt.days
    prod["DAYS_WH_LIVE"] = (today - prod[["WH_LIVE_DATE", "LAST_INWARD"]].max(axis=1)).dt.days
    prod["DAYS_OFF_FIRST"] = (today - prod["FIRST_OFFLINE_SALE"]).dt.days
    # NEW = never sold offline, or first offline sale / WH live within NEW_SKU_DAYS
    prod["IS_NEW"] = (prod["FIRST_OFFLINE_SALE"].isna() | (prod["DAYS_OFF_FIRST"] <= C.NEW_SKU_DAYS)).astype(int)
    prod["RET_RATE"] = np.where(prod["OFFLINE_L90"] > 0, prod["RET_L90"] / prod["OFFLINE_L90"].clip(lower=1), 0)
    prod["GP"] = prod["MRP"] - pd.to_numeric(prod["COST_PRICE"], errors="coerce").fillna(0)
    w = wh.groupby("SKU")[["WH_UNITS"]].sum()
    prod["WH_UNITS"] = prod["SKU"].map(w["WH_UNITS"]).fillna(0)
    return prod.reset_index(drop=True)


# ---------------------------------------------------------------- store x category health
def store_health(stores, ss, prod, ideal, size_sales):
    """Returns (health rows per store x category, mix detail dict) for the dashboard."""
    pm = prod.set_index("SKU")
    ss = ss.copy()
    ss["STOCK"] = ss["INV"] + ss["JIT"]
    for c in ("BUCKET", "META1", "META2", "PRICE_TIER", "COLOR_FAM", "MRP"):
        ss[c] = ss["SKU"].map(pm[c])
    ss["BUCKET"] = ss["BUCKET"].fillna("Others")
    st = stores.set_index("BC")
    live = ss[ss["STOCK"] > 0]

    g = ss.groupby(["BC", "CATEGORY"])
    lg = live.groupby(["BC", "CATEGORY"])
    h = pd.DataFrame({
        "STOCK": g["STOCK"].sum(), "INV": g["INV"].sum(), "JIT": g["JIT"].sum(),
        "L7": g["L7"].sum(), "L30": g["L30"].sum(), "L90": g["L90"].sum(),
        "STR_NUM": g["STR_NUM"].sum(), "STR_DEN": g["STR_DEN"].sum(),
        "OPTIONS": lg["SKU"].nunique(),
        "CUT_OPTIONS": live[(live["IS_CUT"] == 1)].groupby(["BC", "CATEGORY"])["SKU"].nunique(),
        "FRESH30": live[live["AGE_DAYS"] <= 30].groupby(["BC", "CATEGORY"])["STOCK"].sum(),
        "AGED90": live[live["AGE_DAYS"] > 90].groupby(["BC", "CATEGORY"])["STOCK"].sum(),
        "STALE": live[(live["LAST_SALE_DAYS"].isna()) | (live["LAST_SALE_DAYS"] > 30)].groupby(["BC", "CATEGORY"])["STOCK"].sum(),
        "ROS_PER_OPT": live.groupby(["BC", "CATEGORY"])["ROS"].mean(),
    }).fillna(0).reset_index()

    mix_col = {"SHIRTS": "MIX_SHIRTS", "T-SHIRTS": "MIX_TSHIRTS"}
    h["CAT_MIX"] = [st.at[b, mix_col[c]] if b in st.index else np.nan for b, c in zip(h["BC"], h["CATEGORY"])]
    h["BASE_STOCK"] = h["BC"].map(st["BASE_STOCK"])
    h["VM_OPTION"] = h["BC"].map(st["VM_OPTION"])
    h["IDEAL_QTY"] = (h["BASE_STOCK"] * h["CAT_MIX"]).round()
    # ideal options: VM option count x category mix; else ideal qty / avg depth 10
    h["IDEAL_OPTIONS"] = np.where(h["VM_OPTION"].notna(), h["VM_OPTION"] * h["CAT_MIX"], h["IDEAL_QTY"] / 10).round()
    h["FILL_PCT"] = np.where(h["IDEAL_QTY"] > 0, h["STOCK"] / h["IDEAL_QTY"] * 100, np.nan)
    h["STR"] = np.where(h["STR_DEN"] > 0, h["STR_NUM"] / h["STR_DEN"], 0)
    h["DOI"] = np.where(h["L30"] > 0, h["STOCK"] / (h["L30"] / 30), 999)
    h["ROOM"] = (h["IDEAL_QTY"] - h["STOCK"]).clip(lower=0).fillna(0)

    # ---- mix detail: actual stock share vs ideal (metafield), vs sales share (colour / price / size)
    def share(df, key, val):
        t = df.groupby(["BC", "CATEGORY", key])[val].sum()
        return (t / t.groupby(level=[0, 1]).transform("sum")).fillna(0)

    ideal = ideal.copy()
    ideal["BUCKET"] = ideal["META1"] + np.where(ideal["META2"] == "N/A", "", " | " + ideal["META2"])
    ideal_s = ideal.groupby(["BC", "CATEGORY", "BUCKET"])["IDEAL_PCT"].sum() / 100
    meta_stock = share(live, "BUCKET", "STOCK")
    meta_sales = share(ss, "BUCKET", "L90")

    # size: store stock by size vs 90-day size sales
    size_sales = size_sales.copy()
    size_sales["SLOT"] = size_sales["SZ"].map(SZ_SLOT)
    size_sales = size_sales.dropna(subset=["SLOT"])
    size_sales["CATEGORY"] = size_sales["SKU"].map(pm["CATEGORY"])
    size_sales = size_sales.dropna(subset=["CATEGORY"])
    sz_sales = size_sales.groupby(["BC", "CATEGORY", "SLOT"])["QTY"].sum().unstack(fill_value=0)
    sz_stock = live.groupby(["BC", "CATEGORY"])[U].sum()
    col_stock, col_sales = share(live, "COLOR_FAM", "STOCK"), share(ss, "COLOR_FAM", "L90")
    pr_stock, pr_sales = share(live, "PRICE_TIER", "STOCK"), share(ss, "PRICE_TIER", "L90")

    mix = {}
    keys = h[["BC", "CATEGORY"]].itertuples(index=False)
    for b, c in keys:
        k = (b, c)
        def d(series, key=k):
            try:
                return series.loc[key].round(4).to_dict()
            except KeyError:
                return {}
        ideal_d, stock_d, sales_d = d(ideal_s), d(meta_stock), d(meta_sales)
        buckets = sorted(set(ideal_d) | set(stock_d) | set(sales_d))
        mix["%d|%s" % (b, c)] = {
            "meta": [[x, ideal_d.get(x), stock_d.get(x, 0), sales_d.get(x, 0)] for x in buckets],
            "color": _pair(d(col_stock), d(col_sales)),
            "price": _pair(d(pr_stock), d(pr_sales)),
            "size": [[C.SIZES[i],
                      _i(sz_stock.loc[k].iloc[i]) if k in sz_stock.index else 0,
                      _i(sz_sales.loc[k].get(i, 0)) if k in sz_sales.index else 0] for i in range(len(C.SIZES))],
        }
    return h, mix, ideal_s, meta_stock


def _pair(stock_d, sales_d):
    return [[x, stock_d.get(x, 0), sales_d.get(x, 0)] for x in sorted(set(stock_d) | set(sales_d))]


def _i(v):
    try:
        return 0 if v is None or (isinstance(v, float) and math.isnan(v)) else int(round(float(v)))
    except (TypeError, ValueError):
        return 0


# ---------------------------------------------------------------- demand projection + placements
def placements(prod, stores, ss, health, neighbours, ideal_s, meta_stock, pipe):
    """For every SKU with WH stock (or NEW), rank stores by projected ROS and return compact placement rows:
       [store_idx, projROS*1000, ownROS*1000, neighbourCoverage, curStock, pipeQty, mixGapPct*10, suggQty]"""
    today = pd.Timestamp(date.today())
    sku_i = {s: i for i, s in enumerate(prod["SKU"])}
    st_i = {int(b): i for i, b in enumerate(stores["BC"])}
    ss = ss[ss["BC"].isin(st_i)].copy()
    ss["STOCK"] = ss["INV"] + ss["JIT"]
    ss["si"] = ss["SKU"].map(sku_i)
    ss = ss.dropna(subset=["si"])
    ss["si"] = ss["si"].astype(int)
    ss["bi"] = ss["BC"].map(st_i).astype(int)

    # per SKU: {store_idx: ROS} where it actually sold there (history the neighbours lend)
    hist = ss[ss["TOTAL_SALES"] > 0]
    ros_by_sku = {k: dict(zip(g["bi"], g["ROS"])) for k, g in hist.groupby("si")}
    stock_by = {(a, b): v for a, b, v in zip(ss["si"], ss["bi"], ss["STOCK"])}
    pipe_by = {}
    name_bc = {str(n).upper().strip(): int(b) for n, b in zip(stores["STORE_NAME"], stores["BC"])}
    for r in pipe.itertuples():
        b, s = name_bc.get(r.STORE_NAME), sku_i.get(r.SKU)
        if b is not None and s is not None and r.PIPE_QTY > 0:
            pipe_by[(s, st_i[b])] = pipe_by.get((s, st_i[b]), 0) + r.PIPE_QTY

    hk = health.set_index(["BC", "CATEGORY"])
    base_ros = {(st_i[b], c): v for (b, c), v in hk["ROS_PER_OPT"].items() if b in st_i}
    live_days = prod["DAYS_LIVE"].fillna(9999).to_numpy()

    out = {}
    targets = prod.index[(prod["WH_UNITS"] >= C.MIN_ALLOC) | (prod["IS_NEW"] == 1)]
    nstores = len(stores)
    for qi in targets:
        cat = prod.at[qi, "CATEGORY"]
        num, den, cov = np.zeros(nstores), np.zeros(nstores), np.zeros(nstores, int)
        for j, final, *_ in neighbours.get(int(qi), []):
            rmap = ros_by_sku.get(j)
            if not rmap:
                continue
            w = final * 0.5 ** (min(live_days[j], 3 * C.DECAY_DAYS) / C.DECAY_DAYS)   # older comparables count less
            for b, r in rmap.items():
                num[b] += w * r
                den[b] += w
                cov[b] += 1
        own = ros_by_sku.get(int(qi), {})
        base = np.array([base_ros.get((b, cat), 0.0) for b in range(nstores)])
        k = 1.0                                                     # shrink sparse neighbour evidence to store avg
        nb = np.where(den > 0, (num + k * base) / (den + k), 0.0)
        own_a = np.array([own.get(b, np.nan) for b in range(nstores)])
        proj = np.where(np.isnan(own_a), nb, 0.6 * np.nan_to_num(own_a) + 0.4 * nb)
        if not proj.any():
            continue
        top = np.argsort(-proj)[:C.PLACEMENTS_PER_SKU]
        bucket = prod.at[qi, "BUCKET"]
        rows = []
        for b in top:
            if proj[b] <= 0:
                break
            bc = int(stores.at[b, "BC"])
            ideal = ideal_s.get((bc, cat, bucket))
            actual = meta_stock.get((bc, cat, bucket), 0.0)
            gap = (ideal - actual) * 100 if ideal is not None and not pd.isna(ideal) else 0.0
            cur = stock_by.get((int(qi), int(b)), 0)
            pq = pipe_by.get((int(qi), int(b)), 0)
            want = proj[b] * C.COVER_DAYS
            cap = proj[b] * C.MAX_DOI
            sugg = int(max(0, min(want, cap) - cur - pq))
            sugg = sugg if sugg >= C.MIN_ALLOC else (C.MIN_ALLOC if cur + pq == 0 else 0)
            rows.append([int(b), _i(proj[b] * 1000), _i(own_a[b] * 1000) if not np.isnan(own_a[b]) else -1,
                         int(cov[b]), _i(cur), _i(pq), _i(gap * 10), sugg])
        out[int(qi)] = rows
    return out


def size_curves(stores, prod, size_sales):
    """Store x category 90-day size share (10 slots, sums to 1000). Falls back to chain curve."""
    st_i = {int(b): i for i, b in enumerate(stores["BC"])}
    cat = prod.set_index("SKU")["CATEGORY"]
    s = size_sales.copy()
    s["SLOT"] = s["SZ"].map(SZ_SLOT)
    s["CATEGORY"] = s["SKU"].map(cat)
    s = s.dropna(subset=["SLOT", "CATEGORY"])
    s = s[s["BC"].isin(st_i)]
    chain = s.groupby(["CATEGORY", "SLOT"])["QTY"].sum().unstack(fill_value=0)
    per = s.groupby(["BC", "CATEGORY", "SLOT"])["QTY"].sum().unstack(fill_value=0)
    out = {}
    for c in C.CATEGORIES:
        ch = chain.loc[c] if c in chain.index else pd.Series(dtype=float)
        for bc, i in st_i.items():
            row = per.loc[(bc, c)] if (bc, c) in per.index else ch
            if row.sum() < 30:                                      # too little evidence -> chain curve
                row = ch
            tot = row.sum() or 1
            out["%d|%s" % (i, c)] = [_i(row.get(k, 0) * 1000 / tot) for k in range(len(C.SIZES))]
    return out
