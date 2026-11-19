"""Tiered similarity search (filtering_logic.md, FINAL), vectorised over the whole catalogue.

For every in-scope SKU (query; any status, incl. drafts) find similar SKUs in the same category:
  Tier 0  candidate pool = ACTIVE, or DRAFT with FINAL_LIVE_DATE; never the query itself (leave-one-out)
  Tier 1  hard cascade collar+fit+material -> collar+fit -> collar -> category; a candidate is scored once, at the
          tightest tier it appears in. Stop widening once >= top_k candidates clear the quality floor.
  Tier 2  soft boost = share of matching soft attributes (damped)
  Tier 3  DESIGNS / PRINT_DESIGN agreement flag (diagnostic only)
  final_score = visual × tier_multiplier × (1 + damping × soft_boost)
  quality gate = visual × (1 + damping × soft_boost) >= calibrated floor  AND  visual >= min_visual
The floor = Nth percentile of the same quantity over colourway siblings (same style code, different colour).
"""
import numpy as np
import pandas as pd

from engine import config as C

S = C.SIM


def _norm(v):
    v = "" if v is None or (isinstance(v, float) and np.isnan(v)) else str(v).strip().lower()
    return "" if v in ("", "none", "nan", "unknown", "na", "n/a") else v


def _codes(series):
    """Categorical -> int codes, unknown = -1 (never matches)."""
    vals = series.map(_norm)
    cats = {v: i for i, v in enumerate(sorted(set(vals) - {""}))}
    return vals.map(lambda v: cats.get(v, -1)).to_numpy(np.int32)


def fit_normalized(fit):
    f = (fit or "").strip().upper() if isinstance(fit, str) else ""
    return C.FIT_NORMALIZE.get(f, "Regular")


def style_code(sku):
    return sku.split("-")[0]


def calibrate_floor(vecs, soft, style):
    """Nth percentile of damped sibling scores; default floor when there are no siblings."""
    df = pd.DataFrame({"i": np.arange(len(style)), "st": style})
    scores = []
    for _, g in df.groupby("st"):
        idx = g["i"].to_numpy()
        if len(idx) < 2:
            continue
        idx = idx[:12]                                   # cap pairs per style
        sim = vecs[idx] @ vecs[idx].T
        sm = soft[idx]
        known = (sm >= 0)
        for a in range(len(idx)):
            for b in range(a + 1, len(idx)):
                k = known[a]
                boost = ((sm[a] == sm[b]) & k).sum() / max(k.sum(), 1)
                scores.append(sim[a, b] * (1 + S["soft_boost_damping"] * boost))
    if not scores:
        return S["default_floor"], 0
    return float(np.percentile(scores, S["calibration_percentile"])), len(scores)


def search(products, skus, vecs):
    """products: DataFrame (one row per SKU), skus/vecs: embedded SKUs.
    Returns {sku: [(cand_sku, final, visual, tier, boost, soft_matched_list, obvious, designs_match, print_match)]}
    and per-category calibration info."""
    p = products.set_index("SKU").loc[skus].reset_index()
    p["FIT_NORMALIZED"] = p["FIT"].map(fit_normalized)
    eligible = ((p["STATUS"].str.upper() == "ACTIVE") | p["FINAL_LIVE_DATE"].notna()).to_numpy()
    collar, fitn, mat = _codes(p["COLLAR_NEW"]), _codes(p["FIT_NORMALIZED"]), _codes(p["MATERIAL_NEW"])
    soft = np.stack([_codes(p[a]) for a in S["soft_attrs"]], axis=1)
    designs, prnt = _codes(p["DESIGNS"]), _codes(p["PRINT_DESIGN"])
    style = p["SKU"].map(style_code).to_numpy()
    cat = p["CATEGORY"].to_numpy()
    sku_arr = p["SKU"].to_numpy()
    damp, minv, topk, keep = S["soft_boost_damping"], S["min_visual"], S["top_k"], S["keep"]
    mult = np.array([0, *[S["tier_mult"][t] for t in (1, 2, 3, 4)]], np.float32)

    out, calib = {}, {}
    for c in np.unique(cat):
        qi = np.where(cat == c)[0]
        ci = qi[eligible[qi]]
        if len(ci) == 0:
            continue
        floor, npairs = calibrate_floor(vecs[ci], soft[ci], style[ci])
        calib[c] = {"floor": round(floor, 4), "sibling_pairs": npairs, "pool": int(len(ci)), "queries": int(len(qi))}
        print("  %-9s pool %d | queries %d | floor %.3f from %d sibling pairs" % (c, len(ci), len(qi), floor, npairs))
        cv, cc, cf, cm, cs = vecs[ci], collar[ci], fitn[ci], mat[ci], soft[ci]
        for start in range(0, len(qi), 256):
            q = qi[start:start + 256]
            simm = vecs[q] @ cv.T
            for row, i in enumerate(q):
                sim = simm[row]
                same_c = (cc == collar[i]) & (collar[i] >= 0)
                same_f = (cf == fitn[i]) & (fitn[i] >= 0)
                same_m = (cm == mat[i]) & (mat[i] >= 0)
                tier = np.full(len(ci), 4, np.int8)
                tier[same_c] = 3
                tier[same_c & same_f] = 2
                tier[same_c & same_f & same_m] = 1
                qs = soft[i]
                known = qs >= 0
                match = (cs == qs) & known
                boost = match.sum(1) / max(known.sum(), 1)
                damped = sim * (1 + damp * boost)
                ok = (damped >= floor) & (sim >= minv) & (ci != i)
                # cascade: include tiers 1..t, stop at the first t that reaches top_k qualifying candidates
                accepted = np.zeros(len(ci), bool)
                for t in (1, 2, 3, 4):
                    accepted |= ok & (tier == t)
                    if accepted.sum() >= topk:
                        break
                idx = np.where(accepted)[0]
                if len(idx) == 0:
                    out[sku_arr[i]] = []
                    continue
                final = sim[idx] * mult[tier[idx]] * (1 + damp * boost[idx])
                order = idx[np.argsort(-final)[:keep]]
                res = []
                for j in order:
                    g = ci[j]
                    res.append((sku_arr[g], round(float(sim[j] * mult[tier[j]] * (1 + damp * boost[j])), 4),
                                round(float(sim[j]), 4), int(tier[j]), round(float(boost[j]), 3),
                                [S["soft_attrs"][k] for k in np.where(match[j])[0]],
                                bool(style[g] == style[i]),
                                bool(designs[i] >= 0 and designs[g] == designs[i]),
                                bool(prnt[i] >= 0 and prnt[g] == prnt[i])))
                out[sku_arr[i]] = res
    return out, calib
