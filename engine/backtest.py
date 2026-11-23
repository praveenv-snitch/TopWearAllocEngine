"""Leave-one-out backtest of the store demand projection (directives/run_backtest.md).

For established SKUs (carried >= 30 days in >= 5 stores), hide the SKU's own history, project its store ROS from
similar SKUs only (similarity already excludes the SKU itself), and compare with its actual store ROS.
  WAPE        Σ|pred − actual| / Σ actual over store rows (robust to zeros, unlike MAPE)
  naive WAPE  same, predicting the store x category baseline ROS
  Spearman    rank correlation across stores per SKU (does the model order stores correctly?)

    python -m engine.backtest            # uses the same data / embedding cache as engine.build
"""
import csv
import os
import subprocess
from datetime import date

import numpy as np

from engine import build, config as C, demand, embeddings, similarity

N_SKUS = int(os.environ.get("TW_BACKTEST_SKUS", "400"))


def _spearman(a, b):
    if len(a) < 3 or np.std(a) == 0 or np.std(b) == 0:
        return np.nan
    ra, rb = np.argsort(np.argsort(a)), np.argsort(np.argsort(b))
    return float(np.corrcoef(ra, rb)[0, 1])


def main():
    d = build.load()
    prods = build.prepare_products(d["products"])
    ss = d["store_sku"]
    stores = d["stores"].drop_duplicates("BC")
    st_bc = sorted(int(b) for b in stores["BC"])
    skus, vecs = embeddings.embed(prods)
    nbrs, _, _ = similarity.search(prods, skus, vecs)

    est = ss[ss["DAYS_LIVE"] >= 30].groupby("SKU").filter(lambda g: len(g) >= 5)
    pool = sorted(set(est["SKU"]) & set(nbrs))
    rng = np.random.default_rng(42)
    test = list(rng.choice(pool, min(N_SKUS, len(pool)), replace=False))
    if len(test) < 20:
        raise SystemExit("only %d eligible SKUs - backtest would not be reliable" % len(test))
    clus = dict(zip(stores["BC"].astype(int), stores["CLUSTER"]))
    proj, _, base, _ = demand.build(prods, ss, st_bc, nbrs, test, clus, use_own=False)
    si = {b: i for i, b in enumerate(st_bc)}
    cat = dict(zip(prods["SKU"], prods["CATEGORY"]))

    err = err_naive = tot = 0.0
    rhos = []
    for t, s in enumerate(test):
        g = est[(est["SKU"] == s) & est["BC"].isin(si)]
        idx = g["BC"].map(si).to_numpy()
        act = g["ROS"].to_numpy(float)
        pred, naive = proj[t, idx], base[cat[s]][idx]
        err += np.abs(pred - act).sum(); err_naive += np.abs(naive - act).sum(); tot += act.sum()
        rhos.append(_spearman(pred, act))
    res = {"wape": err / tot, "naive_wape": err_naive / tot, "spearman": float(np.nanmedian(rhos)), "skus": len(test)}
    print("Backtest on %d SKUs: WAPE %.3f | naive store-baseline WAPE %.3f | median Spearman %.3f%s"
          % (len(test), res["wape"], res["naive_wape"], res["spearman"],
             "  [FAKE embeddings - not a model result]" if embeddings.FAKE else ""))
    os.makedirs("logs", exist_ok=True)
    path = "logs/experiments.csv"
    new = not os.path.exists(path)
    try:
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    except OSError:
        commit = ""
    with open(path, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["date", "embedding", "half_life_days", "wape", "naive_wape", "spearman", "skus", "commit"])
        w.writerow([date.today(), "FAKE" if embeddings.FAKE else embeddings.MODEL_NAME, C.DEMAND["recency_half_life_days"],
                    round(res["wape"], 4), round(res["naive_wape"], 4), round(res["spearman"], 4), res["skus"], commit])


if __name__ == "__main__":
    main()
