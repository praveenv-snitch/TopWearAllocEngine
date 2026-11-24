"""Store x category health: fill, options, STR, DOI, cut, freshness, and actual-vs-benchmark mixes.

Benchmarks
  category mix   GS_SHEET3 CATEGORY_MIX (ideal share of base stock)
  metafield mix  GS_T_SHIRTS_IDEAL_MIX (collar|designs) / GS_SHIRTS_IDEAL_MIX (designs)
  colour mix     the store's cluster 90-day offline sales share by colour (no colour ideal is maintained)
  price mix      the store's own 90-day sales share by MRP band
  size curve     the store's 90-day category size sales share
"Actual" is always the share of current store stock (on hand + JIT).

Net stock (STORE_CATEGORY_DELTA, size_category_meta_delta_offline):
  after JIT = inventory + JIT - ROS7d x lead time - outward
  after IST = after JIT + IST inbound (IST_JIT_QTY) - IST given away (IST_GIVEN_QTY)
Ideal options = base stock x category mix / depth; per meta combination x the meta ideal mix as well.
Category target (MTD) = FACT_PARETO_TARGET_PERFORMANCE_SUMMARY monthly category target (store target x category
  inventory share x category ASP / sum over the store's categories) x days elapsed to yesterday / days in month.
"""
import calendar
import json

import numpy as np
import pandas as pd

from engine import config as C

SZ_SLOT = {"XS": 0, "S": 1, "M": 2, "L": 3, "XL": 4, "XXL": 5, "2XL": 5, "3XL": 6, "XXXL": 6, "4XL": 7,
           "5XL": 8, "6XL": 9, "28": 0, "30": 1, "32": 2, "34": 3, "36": 4, "38": 5, "40": 6, "42": 7, "44": 8, "46": 9}
TOP_COLOURS = 14


def _arr(v):
    if isinstance(v, str):
        v = json.loads(v)
    if not isinstance(v, (list, tuple, np.ndarray)):      # NULL -> None / NaN
        v = [0] * 10
    return np.array([_f(x) for x in v][:10], np.float32)


def colour_name(c):
    c = (c or "").strip().title() if isinstance(c, str) else ""
    return c if c and c.lower() not in ("none", "nan") else "Unknown"


def _f(v):
    try:
        v = float(v)
        return 0.0 if np.isnan(v) else v
    except (TypeError, ValueError):
        return 0.0


def _share(d):
    t = sum(d.values())
    return {k: v / t for k, v in d.items()} if t > 0 else {}


def build(stores, store_sku, products, ideal_mix, size_sales):
    prod = products.set_index("SKU")
    p_cat, p_mix = prod["CATEGORY"].to_dict(), prod["MIX_KEY"].to_dict()
    p_col, p_band = prod["COLOUR"].to_dict(), prod["PRICE_BAND"].to_dict()

    ss = store_sku.copy()
    ss["CAT"] = ss["SKU"].map(p_cat)
    ss = ss[ss["CAT"].notna()]
    ss["STOCK"] = ss["INV"] + ss["JIT"]
    ss["MIX"], ss["COL"], ss["BAND"] = ss["SKU"].map(p_mix), ss["SKU"].map(p_col), ss["SKU"].map(p_band)
    stocked = ss[ss["STOCK"] > 0]

    # colour palette per category = top colours by stock+sales; the rest -> "Other"
    palette = {}
    for c, g in ss.groupby("CAT"):
        w = (g["STOCK"] + g["L90"]).groupby(g["COL"]).sum().sort_values(ascending=False)
        palette[c] = [x for x in w.index if x != "Unknown"][:TOP_COLOURS] + ["Other"]
    ss["COLB"] = [col if col in palette.get(cat, []) else "Other" for col, cat in zip(ss["COL"], ss["CAT"])]
    stocked = ss[ss["STOCK"] > 0]

    st_cluster = stores.drop_duplicates("BC").set_index("BC")["CLUSTER"].to_dict()
    ss["CLUSTER"] = ss["BC"].map(st_cluster)
    clus_col = {(k[0], k[1]): _share(g.groupby("COLB")["L90"].sum().to_dict())
                for k, g in ss.groupby(["CLUSTER", "CAT"])}

    ideal = {}
    for r in ideal_mix.itertuples():
        ideal.setdefault((int(r.BC), r.CATEGORY), {})[r.MIX_KEY] = float(r.IDEAL_MIX or 0)

    size_sale = {}
    for r in size_sales.itertuples():
        slot = SZ_SLOT.get(str(r.SZ).upper())
        if slot is not None and r.BC == r.BC:
            size_sale.setdefault((int(r.BC), r.CATEGORY), np.zeros(10))[slot] += r.QTY

    today = pd.Timestamp.today()
    month_frac = (today.day - 1) / calendar.monthrange(today.year, today.month)[1]
    groups = {k: g for k, g in stocked.groupby(["BC", "CAT"])}
    sales_groups = {k: g for k, g in ss.groupby(["BC", "CAT"])}

    health = {}
    for r in stores.itertuples():
        key = (int(r.BC), r.CATEGORY)
        g = groups.get(key, stocked.iloc[0:0])
        sg = sales_groups.get(key, ss.iloc[0:0])
        stock = float(g["STOCK"].sum())
        base = _f(r.BASE_STOCK) * _f(r.IDEAL_CAT_MIX)
        depth = _f(r.DEPTH) or 12.0
        opts = int(g["SKU"].nunique())
        l30 = float(g["L30"].sum()) if len(g) else _f(r.CAT_L30)
        str_den = float(sg["STR_DEN"].sum())
        mix_a = _share(g.groupby("MIX")["STOCK"].sum().to_dict())
        mix_i = ideal.get(key, {})
        mix_s = _share(sg.groupby("MIX")["L90"].sum().to_dict())
        mix_o = g.groupby("MIX")["SKU"].nunique().to_dict()
        col_a = _share(g.groupby("COLB")["STOCK"].sum().to_dict())
        col_b = clus_col.get((st_cluster.get(int(r.BC)), r.CATEGORY), {})
        band_a = _share(g.groupby("BAND")["STOCK"].sum().to_dict())
        band_s = _share(sg.groupby("BAND")["L90"].sum().to_dict())
        sz_inv = np.sum([_arr(v) for v in g["SZ"]], axis=0) if len(g) else np.zeros(10)
        sz_sale = size_sale.get(key, np.zeros(10))
        tgt = _f(r.TARGET_MTD) or _f(r.TARGET_MONTH) * month_frac
        has_d = getattr(r, "D_INV", None) is not None and r.D_INV == r.D_INV
        if has_d:
            cbase = _f(r.D_CAT_BASE) or base
            draw = _f(r.D_ROS7) * (_f(r.D_LEAD) or 3) + _f(r.D_OUTWARD)
            net_jit = _f(r.D_INV) + _f(r.D_JIT) - draw
            net_ist = net_jit + _f(r.D_IST_IN) - _f(r.D_IST_OUT)
        else:                                    # store not in STORE_CATEGORY_DELTA: stock + JIT only
            cbase, net_jit = base, stock
            net_ist = stock
        health[key] = {
            "base": round(base), "depth": depth, "stock": round(stock), "jit": round(_f(r.CAT_JIT)),
            "opts": opts, "idealOpts": round(base / depth) if base else 0,
            "fill": round(stock / base, 3) if base else -1,
            "l30": round(l30), "str": round(float(sg["STR_NUM"].sum()) / str_den, 3) if str_den else 0,
            "doi": round(stock / (l30 / 30), 1) if l30 else -1,
            "cut": round(float(g["IS_CUT"].sum()) / opts, 3) if opts else 0,
            "fresh": round(float(g.loc[g["AGE_DAYS"] <= C.FRESH_DAYS, "STOCK"].sum()) / stock, 3) if stock else 0,
            "aged": round(float(g.loc[g["AGE_DAYS"] > 120, "STOCK"].sum()) / stock, 3) if stock else 0,
            "noSale": int(((g["L30"] == 0) & (g["AGE_DAYS"] > 30)).sum()),
            "rev90": round(float(sg["REV90"].sum())),
            # mix: [ideal share, stock share, 90d sales share]; mixOpt: [ideal options, options carried]
            "mix": {k: [round(mix_i.get(k, 0), 3), round(mix_a.get(k, 0), 3), round(mix_s.get(k, 0), 3)]
                    for k in set(mix_i) | set(mix_a) | set(mix_s)},
            "mixOpt": {k: [round(base * mix_i.get(k, 0) / depth, 1), int(mix_o.get(k, 0))] for k in set(mix_i) | set(mix_o)},
            "catBase": round(cbase), "inv": round(_f(r.D_INV) if has_d else _f(r.CAT_INV)),
            "istIn": round(_f(r.D_IST_IN)), "istOut": round(_f(r.D_IST_OUT)), "ros7": round(_f(r.D_ROS7)),
            "lead": round(_f(r.D_LEAD) or 3), "outward": round(_f(r.D_OUTWARD)),
            "netJit": round(net_jit), "netIst": round(net_ist),
            "fillNow": round((_f(r.D_INV) if has_d else _f(r.CAT_INV)) / cbase, 3) if cbase else -1,
            "fillJit": round(net_jit / cbase, 3) if cbase else -1, "fillIst": round(net_ist / cbase, 3) if cbase else -1,
            # category target, MTD: FACT_PARETO monthly category target pro-rated to yesterday; revenue = category MTD sales
            "catTarget": round(_f(getattr(r, "CAT_TARGET_MTD", 0))), "catTargetMonth": round(_f(getattr(r, "CAT_TARGET_MONTH", 0))),
            "catRevenue": round(_f(getattr(r, "CAT_REVENUE_MTD", 0))),
            "catTargetPct": round(100 * _f(getattr(r, "CAT_REVENUE_MTD", 0)) / _f(r.CAT_TARGET_MTD), 1) if _f(getattr(r, "CAT_TARGET_MTD", 0)) else 0,
            "catTargetW": round(_f(getattr(r, "CAT_TARGET_WEIGHT", 0)), 1),
            "col": {k: [round(col_b.get(k, 0), 3), round(col_a.get(k, 0), 3)] for k in set(col_b) | set(col_a)},
            "band": {k: [round(band_s.get(k, 0), 3), round(band_a.get(k, 0), 3)] for k in set(band_s) | set(band_a)},
            "size": [[round(x / sz_sale.sum(), 3) if sz_sale.sum() else 0 for x in sz_sale],
                     [round(x / sz_inv.sum(), 3) if sz_inv.sum() else 0 for x in sz_inv]],
            "idealCat": round(_f(r.IDEAL_CAT_MIX), 3),
            "target": round(tgt), "actual": round(_f(r.ACTUAL_MTD)),
        }
    return health, palette
