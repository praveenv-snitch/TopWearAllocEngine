"""TopWear Allocation Engine build:  Snowflake -> embeddings -> similarity -> demand -> store health -> index.html -> KV.

    python -m engine.build                 # full run (GitHub Actions)
    TW_DEV_DATA=.cache/dev/data.pkl ...    # reuse a pickled Snowflake pull (development)
"""
import base64
import json
import os
import pickle
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytz

from engine import config as C, demand, embeddings, health, similarity

DATASETS = ["products", "store_sku", "stores", "ideal_mix", "size_sales", "b2b", "fresh_pool", "pp_codes", "fac_stock"]
TEMPLATE = Path(__file__).resolve().parent.parent / "web" / "template.html"
IMG_PREFIX = "https://cdn.shopify.com/s/files/1/0420/7073/7058/files/"


def _s(v):
    return "" if v is None or (isinstance(v, float) and np.isnan(v)) or str(v) in ("None", "nan", "NaT") else str(v)


def _i(v):
    try:
        return 0 if v is None or pd.isna(v) else int(round(float(v)))
    except (TypeError, ValueError):
        return 0


def _d(v):
    """date -> 'YYYY-MM-DD' or ''."""
    t = pd.to_datetime(v, errors="coerce")
    return "" if pd.isna(t) else t.strftime("%Y-%m-%d")


def _arr(v):
    if isinstance(v, str):
        v = json.loads(v)
    if not isinstance(v, (list, tuple, np.ndarray)):      # NULL -> None / NaN
        v = [0] * 10
    return [_i(x) for x in v][:10]


def _numeric(d):
    """Snowflake NUMBER columns can arrive as decimal.Decimal objects -> float."""
    from decimal import Decimal
    for df in d.values():
        for c in df.columns:
            if df[c].dtype == object and df[c].map(lambda v: isinstance(v, Decimal)).any():
                df[c] = pd.to_numeric(df[c], errors="coerce")
    return d


def load():
    dev = os.environ.get("TW_DEV_DATA")
    if dev and os.path.exists(dev):
        print("Using cached Snowflake pull", dev)
        return _numeric(pickle.load(open(dev, "rb")))
    from engine.snowflake_io import fetch_all
    print("Fetching from Snowflake...")
    d = fetch_all(DATASETS)
    if dev:
        os.makedirs(os.path.dirname(dev), exist_ok=True)
        pickle.dump(d, open(dev, "wb"))
    return _numeric(d)


def prepare_products(p):
    p = p.drop_duplicates("SKU").reset_index(drop=True)
    p = p[~p["SKU"].fillna("").str.upper().str.startswith(tuple(C.PLUS_EXCL_PREFIXES))].reset_index(drop=True)   # plus size out
    p["MIX_KEY"] = [C.mix_key(c, co, de, st) for c, co, de, st in zip(p["CATEGORY"], p["COLLAR_NEW"], p["DESIGNS"], p["STYLE"])]
    p["COLOUR"] = p["COLOR"].map(health.colour_name)
    p["PRICE_BAND"] = p["MRP"].map(lambda m: C.price_band(float(m or 0)))
    # ASP = 90-day offline revenue / units; no offline sale in 90 days -> current selling price, else MRP
    rev = pd.to_numeric(p.get("OFFLINE_REV90", 0), errors="coerce").fillna(0)
    u90 = pd.to_numeric(p["OFFLINE_L90"], errors="coerce").fillna(0)
    sp = pd.to_numeric(p["SELLING_PRICE"], errors="coerce").fillna(0)
    mrp = pd.to_numeric(p["MRP"], errors="coerce").fillna(0)
    p["ASP"] = np.where((u90 > 0) & (rev > 0), rev / u90.where(u90 > 0, 1), np.where(sp > 0, sp, mrp))
    p["ASP_BAND"] = p["ASP"].map(lambda m: C.price_band(float(m or 0)))
    p["SLEEVE"] = p["SLEEVE_TYPE"].map(lambda v: C.txt(v).strip().title() or "Unknown").replace({"None": "Unknown", "Nan": "Unknown"})
    today = pd.Timestamp.today().normalize()
    first = pd.to_datetime(p["FIRST_OFFLINE_SALE"], errors="coerce")
    p["AGE_TAG"] = np.where(p["OFFLINE_UNITS"] <= 0, 0,
                            np.where((today - first).dt.days <= C.NEW_SKU_DAYS, 1, 2))   # 0 new, 1 recent, 2 old
    return p


def main():
    t0 = time.time()
    d = load()
    prods = prepare_products(d["products"])
    store_sku, stores = d["store_sku"], d["stores"]
    store_sku = store_sku[~store_sku["SKU"].fillna("").str.upper().str.startswith(tuple(C.PLUS_EXCL_PREFIXES))]
    stores = stores[stores["CATEGORY"].isin(C.CATEGORIES)
                    & ~stores["STORE_NAME"].fillna("").str.upper().str.contains("WAREHOUSE|TEST|DUMMY")]
    # stores need a base stock and a mapped cluster to be planned (e.g. SNITCH - MAPLE - MYSURU has neither cluster)
    base_ok = pd.to_numeric(stores["BASE_STOCK"], errors="coerce").fillna(0) > 0
    clus_ok = stores["CLUSTER"].fillna("").astype(str).str.strip().str.upper().replace({"NONE": "", "NAN": "", "UNMAPPED": ""}) != ""
    dropped = stores.loc[~(base_ok & clus_ok), "STORE_NAME"].drop_duplicates().tolist()
    stores = stores[base_ok & clus_ok].reset_index(drop=True)
    print("  stores left out (no base stock / unmapped cluster): %d %s" % (len(dropped), dropped[:8]))
    print("products %d | store-sku %d | stores %d" % (len(prods), len(store_sku), stores["BC"].nunique()))

    print("Embedding images...")
    emb_skus, vecs = embeddings.embed(prods)
    print("Similarity search...")
    nbrs, calib, alt_nbrs = similarity.search(prods, emb_skus, vecs)

    print("Store health...")
    hl, palette = health.build(stores, store_sku, prods, d["ideal_mix"], d["size_sales"])

    # ---- index tables
    store_rows = stores.drop_duplicates("BC").sort_values("BC").reset_index(drop=True)
    st_bc = [int(b) for b in store_rows["BC"]]
    st_idx = {b: i for i, b in enumerate(st_bc)}
    name_to_si = {str(n).upper().strip(): i for i, n in enumerate(store_rows["STORE_NAME"])}
    cats = list(C.CATEGORIES)
    ci = {c: i for i, c in enumerate(cats)}
    sku_list = prods["SKU"].tolist()
    ki = {s: i for i, s in enumerate(sku_list)}

    # ---- demand projection targets: WH stock, never sold offline, or recently inwarded
    wh_tot = prods["WH_N"].fillna(0) + prods["WH_S"].fillna(0)
    recent_inw = pd.to_datetime(prods["WH_LIVE_DATE"], errors="coerce") >= pd.Timestamp.today() - pd.Timedelta(days=60)
    fp = d.get("fresh_pool", pd.DataFrame(columns=["SKU"]))
    in_pool = prods["SKU"].isin(set(fp["SKU"]))
    tmask = ((wh_tot > 0) | (prods["AGE_TAG"] == 0) | recent_inw | in_pool) & prods["SKU"].isin(nbrs)
    targets = prods.loc[tmask, "SKU"].tolist()
    print("Demand projection for %d SKUs x %d stores..." % (len(targets), len(st_bc)))
    proj, evid, _, _ = demand.build(prods, store_sku, st_bc, nbrs, targets,
                                 dict(zip(store_rows["BC"].astype(int), store_rows["CLUSTER"])))
    proj_row = {s: i for i, s in enumerate(targets)}
    # evidence -> 2 bits: 0 none, 1 = 1-2 neighbours, 2 = 3+ neighbours, 3 = own history
    ev = np.where(evid >= 100, 3, np.where(evid >= 3, 2, np.where(evid >= 1, 1, 0))).astype(np.uint8)
    ev = np.pad(ev, ((0, 0), (0, (-ev.shape[1]) % 4)))
    ev_packed = (ev[:, 0::4] | (ev[:, 1::4] << 2) | (ev[:, 2::4] << 4) | (ev[:, 3::4] << 6)).astype(np.uint8)

    # ---- in-transit from B2B (store name -> index)
    b2b = d["b2b"]
    transit = {}
    sent = {}
    for r in b2b.itertuples():
        si = name_to_si.get(str(r.STORE).upper().strip())
        if si is None or r.SKU not in ki:
            continue
        if r.IN_TRANSIT:
            transit[(si, ki[r.SKU])] = _i(r.IN_TRANSIT)
        sent.setdefault(r.SKU, set()).add(si)

    # ---- payload
    mix_keys = {c: sorted(set(prods.loc[prods["CATEGORY"] == c, "MIX_KEY"]) |
                          {k for (bc, cc), h in hl.items() if cc == c for k in h["mix"]}) for c in cats}
    bands = [b[2] for b in C.PRICE_BANDS]
    soft = C.SIM["soft_attrs"]
    words = {}                                   # string dictionary: repeated attribute values -> ints

    def w(v):
        v = _s(v)
        if v not in words:
            words[v] = len(words)
        return words[v]

    skus = []
    for r in prods.itertuples():
        img = _s(r.IMAGE_URL)
        cogs, mrp = float(r.COGS or 0) if r.COGS == r.COGS else 0, float(r.MRP or 0) if r.MRP == r.MRP else 0
        skus.append([
            r.SKU, ci[r.CATEGORY], _s(r.PRODUCT_NAME), img[len(IMG_PREFIX):] if img.startswith(IMG_PREFIX) else img,
            w(r.COLLAR_NEW), w(r.FIT), w(r.MATERIAL_NEW), w(r.SLEEVE_TYPE), w(r.DESIGNS), w(r.PRINT_DESIGN),
            w(r.COLOUR), w(r.STYLE), w(r.OCCASSION_NEW),
            _i(mrp), _i(r.SELLING_PRICE), _i(mrp - cogs) if cogs else -1,
            _d(r.FINAL_LIVE_DATE), _s(r.STATUS)[:1],
            _i(r.WH_N), _i(r.WH_S), _arr(r.WH_N_SZ), _arr(r.WH_S_SZ),
            int(r.AGE_TAG), _i(r.OFFLINE_UNITS), _i(r.OFFLINE_STORES),
            round(float(r.OFFLINE_RETURNS) / r.OFFLINE_UNITS, 3) if r.OFFLINE_UNITS else 0,
            round(float(r.ONLINE_ROS or 0), 2), w(r.MIX_KEY), w(r.PRICE_BAND),
            _d(r.WH_LIVE_DATE) or _d(r.FIRST_WH_INWARD), 1 if _s(r.OFFLINE_ALLOCATED_STATUS) == "Offline Allocated" else 0,
            _d(r.FIRST_OFFLINE_SALE), proj_row.get(r.SKU, -1), len(sent.get(r.SKU, ())),
            w(r.CLOSURE), w(r.POCKET), w(r.SKU_CLASS),
            _i(r.OFFLINE_L30), _i(r.OFFLINE_L90), int(r.IS_NRC), _i(r.CUT_STORES), _i(r.WH_SIZE_SETS),
            _i(r.PP_DEPTH), _i(r.PP_N), _i(r.PP_S), _i(r.ASP), w(r.ASP_BAND), w(r.SLEEVE)])     # 45 ASP, 46 ASP band, 47 sleeve

    NB_W = C.SIM["top_k"]

    def nb_rows(src):
        """Neighbours as a flat uint16 array: per SKU NB_W slots x [k+1 (0 = empty), visual*1000, boost*1000,
        code low 16 bits, code high 16 bits]; code = tier | obvious<<3 | designs<<4 | print<<5 | soft-mask<<6."""
        a = np.zeros((len(sku_list), NB_W, 5), np.uint16)
        for i, s in enumerate(sku_list):
            n = 0
            for (cs, final, vis, tier, boost, matched, obv, dm, pm) in src.get(s, []):
                if cs not in ki or n >= NB_W:
                    continue
                code = tier | (obv << 3) | (dm << 4) | (pm << 5) | (sum(1 << soft.index(x) for x in matched) << 6)
                a[i, n] = (ki[cs] + 1, max(int(round(vis * 1000)), 0), int(round(boost * 1000)), code & 0xFFFF, code >> 16)
                n += 1
        return base64.b64encode(a.tobytes()).decode()

    nb_out, nb_vis, nb_meta = nb_rows(nbrs), nb_rows(alt_nbrs["visual"]), nb_rows(alt_nbrs["meta"])

    stock = []          # current store stock of in-scope SKUs (packed to uint16 below)
    ss = store_sku[(store_sku["INV"] + store_sku["JIT"] > 0) & store_sku["BC"].isin(st_idx) & store_sku["SKU"].isin(ki)]
    for r in ss.itertuples():
        si, k = st_idx[int(r.BC)], ki[r.SKU]
        sz = _arr(r.SZ)
        stock.append([si, k, _i(r.INV + r.JIT), _i(r.L30), _i(r.ROS * 1000), _i(r.AGE_DAYS), int(r.IS_CUT),
                      transit.get((si, k), 0), _i(r.LAST_SALE_DAYS) if r.LAST_SALE_DAYS == r.LAST_SALE_DAYS else -1,
                      sz if any(sz) else 0])          # size stock (incl. JIT) for replen sizing

    # [si, k, stock, l30, ros*1000, age, cut, transit, lastSale+1 (0 = never), sz x10] as uint16 (clipped)
    st_arr = np.zeros((len(stock), 19), np.int64)
    for j, r in enumerate(stock):
        st_arr[j, :9] = r[:8] + [r[8] + 1]
        if r[9]:
            st_arr[j, 9:] = r[9]
    stock_b64 = base64.b64encode(np.clip(st_arr, 0, 65535).astype(np.uint16).tobytes()).decode()

    # ---- fresh pool (AV_MASTER_HTMBASE, store_avail.py) + prepack serial codes on hand
    #  codes[k] = {depth: [north codes, south codes]}; a serial code is one sealed pack and is used once
    codes = {}
    for r in d.get("pp_codes", pd.DataFrame(columns=["SKU"])).itertuples():
        k = ki.get(r.SKU)
        if k is None or not _i(r.DEPTH):
            continue
        z = 0 if r.ZONE == "NORTH" else 1
        codes.setdefault(k, {}).setdefault(str(_i(r.DEPTH)), [[], []])[z].append(r.CODE)
    for v in codes.values():
        for lst in v.values():
            lst[0].sort(), lst[1].sort()
    #  pool[k] = [status word, [fso N, fso S], [sizes N], [sizes S], depth, [packs N, packs S]]; packs = min(sets, codes)
    pool = {}
    for r in fp.itertuples():
        k = ki.get(r.SKU)
        if k is None:
            continue
        z = 0 if r.ZONE == "NORTH" else 1
        e = pool.setdefault(k, [w(r.ALLOCATION_STATUS), [0, 0], [0] * 10, [0] * 10, 0, [0, 0]])
        e[1][z] = _i(r.FSO)
        e[1 + 1 + z] = [_i(getattr(r, c)) for c in ("XS", "S", "M", "L", "XL", "XXL", "XL3", "XL4", "XL5", "XL6")]
        dp = _i(r.PP_DEPTH)
        if dp and _i(r.PP_SETS):
            e[4] = e[4] or dp
            if e[4] == dp:
                e[5][z] = min(_i(r.PP_SETS), len(codes.get(k, {}).get(str(dp), [[], []])[z]))
    print("  fresh pool: %d SKUs in catalogue (%d rows; %d not in METAFIELDS skipped)"
          % (len(pool), len(fp), fp.loc[~fp["SKU"].isin(ki), "SKU"].nunique()))
    # only ship codes that can be used: the fresh-pool depth and the placement (helper) depth
    used = {}
    for k, v in codes.items():
        keep = {str(skus[k][42]), str(pool[k][4]) if k in pool else ""}
        v = {dp: x for dp, x in v.items() if dp in keep}
        if v:
            used[k] = v

    # store had the style before but has no stock / JIT now ("repeat" in store_avail.py): [si, k] uint16 pairs
    zr = store_sku[(store_sku["INV"] + store_sku["JIT"] <= 0) & store_sku["BC"].isin(st_idx) & store_sku["SKU"].isin(ki)]
    rep = np.array([[st_idx[int(b)], ki[s_]] for b, s_ in zip(zr["BC"], zr["SKU"])], np.uint16).reshape(-1, 2)
    repeat_b64 = base64.b64encode(rep.tobytes()).decode()

    # facility stock: South has two warehouses (SAPL-WH1 / SAPL-WH2). facStock[k] = {facility: [10 sizes]}; codes on hand
    # in a facility other than the zone default (North SAPL-NORTH-TAURU, South SAPL-WH2) are listed in ppFac.
    fac_stock = {}
    for r in d.get("fac_stock", pd.DataFrame(columns=["SKU"])).itertuples():
        k, slot = ki.get(r.SKU), health.SZ_SLOT.get(str(r.SZ))
        if k is None or slot is None or not str(r.FACILITY).startswith("SAPL-WH"):
            continue
        fac_stock.setdefault(str(k), {}).setdefault(r.FACILITY, [0] * 10)[slot] += _i(r.UNITS)
    pp_fac = {r.CODE: r.FACILITY for r in d.get("pp_codes", pd.DataFrame(columns=["CODE"])).itertuples()
              if getattr(r, "FACILITY", None) and r.FACILITY not in ("SAPL-NORTH-TAURU", "SAPL-WH2")}

    store_out, health_out = [], []
    for i, r in store_rows.iterrows():
        store_out.append([int(r.BC), _s(r.STORE_NAME), _s(r.STORE_TYPE), _s(r.STATE), _s(r.CITY),
                          _s(r.ZONE) or "UNMAPPED", _s(r.CLUSTER) or "UNMAPPED", _s(r.CITY_CLUSTER),
                          _i(r.CARPET_AREA), _i(r.BASE_STOCK), _i(r.MAX_DOI), _i(r.APPAREL_INV),
                          # 12 store base (delta), 13 store inventory, 14 net after JIT, 15 net after IST (all categories)
                          _i(r.S_BASE) or _i(r.BASE_STOCK), _i(r.S_INV), _i(r.S_NET_JIT), _i(r.S_NET_IST),
                          1 if r.S_NET_IST == r.S_NET_IST and r.S_NET_IST is not None else 0,
                          _s(getattr(r, "POC", "")) or "Unknown"])        # 17 cluster POC (STORE_CATEGORY_DELTA)
        health_out.append([hl.get((int(r.BC), c)) for c in cats])

    payload = {
        "built": datetime.now(pytz.timezone("Asia/Kolkata")).strftime("%d %b %Y, %I:%M %p IST"),
        "fake": embeddings.FAKE, "imgPrefix": IMG_PREFIX, "cats": cats, "sizes": C.SIZES, "soft": soft,
        "tierTag": C.SIM["tier_tag"], "tierMult": C.SIM["tier_mult"], "damp": C.SIM["soft_boost_damping"],
        "calib": calib, "mixKeys": mix_keys, "palette": palette, "bands": bands,
        "weights": C.ALLOC_DEFAULT_WEIGHTS, "alloc": C.ALLOC, "rosMax": demand.ROS_MAX,
        "newDays": C.NEW_SKU_DAYS, "nudgeDays": C.NUDGE_DAYS, "freshDays": C.FRESH_DAYS,
        "words": list(words), "stores": store_out, "health": health_out, "skus": skus, "nb": nb_out, "nbVis": nb_vis, "nbMeta": nb_meta, "nbW": NB_W,
        "packs": C.PACKS, "pool": {str(k): v for k, v in pool.items()}, "ppCodes": {str(k): v for k, v in used.items()},
        "fresh": C.FRESH_RUN, "repeat": repeat_b64, "facStock": fac_stock, "ppFac": pp_fac, "calibPct": C.SIM["calibration_percentile"], "stock": stock_b64, "stockW": 19,
        "nStores": len(st_bc),
        "proj": base64.b64encode(demand.pack_uint8(proj)).decode(),
        "evid": base64.b64encode(ev_packed.tobytes()).decode(), "evidW": int(ev_packed.shape[1]),
    }
    data_json = json.dumps(payload, separators=(",", ":"), default=lambda o: o.item() if hasattr(o, "item") else str(o))
    html = TEMPLATE.read_text(encoding="utf-8").replace("__DATA__", data_json.replace("</", "<\\/"))
    with open(C.OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(html)
    print("Built %s (%.1f MB) in %.0fs" % (C.OUTPUT_FILE, len(html) / 1e6, time.time() - t0))
    if len(html.encode("utf-8")) > 24 * 1024 * 1024:     # Workers KV hard limit is 25 MiB per value
        raise SystemExit("index.html is %.1f MB - over the 24 MB safety limit for Workers KV (25 MiB max)." % (len(html) / 1e6))
    publish(html)


def publish(html):
    if not (C.CF_ACCOUNT_ID and C.CF_API_TOKEN and C.CF_KV_NAMESPACE_ID):
        print("KV publish skipped (CF_* not set) - %s is a static file you can open/host anywhere" % C.OUTPUT_FILE)
        return
    if embeddings.FAKE:
        raise SystemExit("Refusing to publish: TW_FAKE_EMBED=1 builds use test vectors, not image similarity")
    import requests
    url = ("https://api.cloudflare.com/client/v4/accounts/%s/storage/kv/namespaces/%s/values/%s"
           % (C.CF_ACCOUNT_ID.strip(), C.CF_KV_NAMESPACE_ID.strip(), C.KV_KEY))
    resp = requests.put(url, data=html.encode("utf-8"), timeout=180,
                        headers={"Authorization": "Bearer " + C.CF_API_TOKEN.strip(),
                                 "Content-Type": "text/html; charset=utf-8"})
    if resp.status_code != 200 or not resp.json().get("success"):
        raise SystemExit("KV publish failed (%s): %s" % (resp.status_code, resp.text[:500]))
    print("[OK] published to Workers KV - live now")


if __name__ == "__main__":
    main()
