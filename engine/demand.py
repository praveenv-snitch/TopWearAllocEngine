"""Store-level demand projection for a SKU from its similar SKUs' offline history.

proj_ros[sku, store] = base[store] × exp( (own_w·log r_own + Σ_n w_n·log r[n, store] + k·log perf) / (own_w + Σ_n w_n + k) )
  r[n, store] = neighbour n's ROS at the store ÷ store x category baseline ROS (its index vs a typical style there)
  w_n         = similarity final_score × recency (0.5 ^ (age / half-life), floored) × store-history weight
  own_w       = the SKU's own store history weight (old SKUs), grows with days live at that store
  perf        = neighbours' average index across all their stores (shrinkage target when store evidence is thin)
  base[store] = median ROS of styles carried >= 30 days there (new stores: cluster, then network median)
"""
import numpy as np
import pandas as pd

from engine import config as C

ROS_MAX = 5.0                       # browser payload: uint8 on a sqrt scale, ros = (q/255)^2 * ROS_MAX


def _age_days(dates, today):
    d = pd.to_datetime(dates, errors="coerce")
    return (today - d).dt.days.fillna(3650).clip(lower=0).to_numpy()


def build(products, store_sku, stores_bc, neighbours, targets, store_cluster=None, use_own=True):
    """Returns (proj matrix float32 [len(targets), len(stores)], evidence int [same], baseline dict)."""
    st_idx = {b: i for i, b in enumerate(stores_bc)}
    ns = len(stores_bc)
    today = pd.Timestamp.today().normalize()
    cat_of = dict(zip(products["SKU"], products["CATEGORY"]))

    ss = store_sku[store_sku["BC"].isin(st_idx)].copy()
    ss["si"] = ss["BC"].map(st_idx)
    carried = ss[(ss["DAYS_LIVE"] >= 7) | (ss["TOTAL_SALES"] > 0)]
    carried = carried.assign(CAT=carried["SKU"].map(cat_of))

    # store x category baseline = median ROS of styles carried there >= 30 days (short histories inflate ROS);
    # stores with < 20 such styles (new stores) fall back to their cluster median, then the network median
    base = {}
    clus = np.array([(store_cluster or {}).get(b, "") for b in stores_bc])
    for c, g in carried[carried["DAYS_LIVE"] >= 30].groupby("CAT"):
        arr = np.full(ns, np.nan, np.float32)
        agg = g.groupby("si")["ROS"].agg(["median", "size"])
        agg = agg[agg["size"] >= 20]
        arr[agg.index.to_numpy()] = agg["median"].to_numpy()
        net = float(np.nanmedian(arr)) if np.isfinite(arr).any() else 0.05
        for cl in set(clus):
            m = (clus == cl) & np.isfinite(arr)
            cm = float(np.median(arr[m])) if cl and m.any() else net
            arr[(clus == cl) & ~np.isfinite(arr)] = cm
        base[c] = np.where(np.isfinite(arr), arr, net).clip(min=0.005)

    # per SKU: stores carried + ROS + days live. Neighbour evidence uses >= 30-day store rows only (backtest: shorter
    # histories add noise); a SKU's own history may use shorter rows, down-weighted by days live.
    def _index(rows):
        return {s: (g["si"].to_numpy(), g["ROS"].to_numpy(np.float32), g["DAYS_LIVE"].to_numpy())
                for s, g in rows.groupby("SKU")}
    by_sku = _index(carried)
    by_sku_n = _index(carried[carried["DAYS_LIVE"] >= 30])
    rel = {}                                        # SKU performance vs store baseline (median ratio)
    for s, (si, ros, _) in by_sku_n.items():
        b = base.get(cat_of.get(s))
        if b is not None and len(si):
            rel[s] = float(np.median(ros / b[si]))

    live_age = dict(zip(products["SKU"], _age_days(products["FINAL_LIVE_DATE"], today)))
    hl, k = C.DEMAND["recency_half_life_days"], C.DEMAND["prior_weight"]
    proj = np.zeros((len(targets), ns), np.float32)
    evid = np.zeros((len(targets), ns), np.int16)
    for t, sku in enumerate(targets):
        b = base.get(cat_of.get(sku))
        if b is None:
            continue
        num = np.zeros(ns, np.float32)
        den = np.zeros(ns, np.float32)
        rels, relw = [], []
        for nb in neighbours.get(sku, []):
            n, final = nb[0], nb[1]
            if n not in by_sku_n:
                continue
            w = final * max(0.5 ** (live_age.get(n, 3650) / hl), C.DEMAND["recency_floor"])
            si, ros, dl = by_sku_n[n]
            ws = w * np.clip(dl / 30.0, 0.05, 1.0)        # short store history = noisy ROS -> less weight
            # average the neighbour's index vs the store baseline (log-ratio damps one-off fast sellers)
            num[si] += ws * np.log(np.clip(ros / b[si], 0.05, 20.0))
            den[si] += ws
            evid[t, si] += 1
            if n in rel:
                rels.append(rel[n]); relw.append(w)
        perf = float(np.exp(np.average(np.log(np.clip(rels, 0.05, 20.0)), weights=relw))) if rels else 1.0
        prior = np.log(perf)
        if use_own and sku in by_sku:                # old SKU: its own history dominates where it exists
            si, ros, dl = by_sku[sku]
            ow = C.DEMAND["own_weight"] * np.clip(dl / 30.0, 0.05, 1.0)
            num[si] += ow * np.log(np.clip(ros / b[si], 0.05, 20.0))
            den[si] += ow
            evid[t, si] += 100                      # marker: own history present (decoded in the browser)
        proj[t] = b * np.exp((num + k * prior) / (den + k))
    return proj, evid, base, by_sku


def pack_uint8(proj):
    """float ROS matrix -> uint8 bytes on a sqrt scale (fine resolution for slow sellers), row-major."""
    return np.clip(np.round(np.sqrt(np.clip(proj, 0, ROS_MAX) / ROS_MAX) * 255), 0, 255).astype(np.uint8).tobytes()
