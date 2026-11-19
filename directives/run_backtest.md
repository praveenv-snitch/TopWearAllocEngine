# Directive: Run Backtest

**Goal:** check that the store demand projection beats a naive baseline and orders stores correctly.

**Tool:** `python -m engine.backtest`, or in GitHub Actions: **Run workflow** with `backtest` ticked (the result appears in the run summary).

**How it works (`engine/backtest.py`):**
1. Pick up to `TW_BACKTEST_SKUS` (default 400) established SKUs, each carried ≥ 30 days in ≥ 5 stores, using a fixed seed.
2. Hide each SKU's own history (`demand.build(..., use_own=False)`). Similarity already excludes the SKU itself, so the run is leave-one-out.
3. Compare projected and actual store ROS:
   - **WAPE** = Σ|pred − actual| / Σ actual. MAPE isn't used because many store ROS values are near zero.
   - **naive WAPE**: the same, predicting the store × category baseline.
   - **Spearman**: median per-SKU rank correlation across stores. This matters most, because placement uses the ranking.
4. A row is appended to `logs/experiments.csv`. Copy the result into CONTEXT.md → Backtest results.

**Edge cases:**
- If the model doesn't beat the naive WAPE, report it plainly and look at `config.DEMAND` (half-life, prior weight).
- If fewer than 20 eligible SKUs are found, the script stops, because the result wouldn't be reliable.
- Rows labelled `FAKE` come from attribute-hash vectors (sandbox testing). They are not model results.

**Learnings log:**
- 2026-11-19 (FAKE vectors): averaging raw neighbour ROS lost to the naive baseline (WAPE 0.715 vs 0.633). Switching to a log-index blend with k = 3 and neighbour rows ≥ 30 days live gave WAPE 0.616, Spearman 0.32. Short store histories (< 30 days) inflate ROS: a store open 5 days showed 3–5 units/day.
