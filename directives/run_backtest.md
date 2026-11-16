# Directive: Run Backtest

**Goal:** Measure model accuracy (MAPE) against a naive baseline, across held-out SKUs.

**Inputs:** At least 20–30 SKUs with full sales history, deliberately excluded
from the similarity-matching pool for this test.

**Tools to use:** `execution/backtest.py` — `mape()`, `run_backtest()`

**Steps:**
1. For each held-out SKU: run the full pipeline (attribute filter → visual
   similarity → demand estimate) as if it were new.
2. Compare predicted vs actual store-level demand — compute MAPE.
3. Compute the naive baseline (category-average sell-through) for the same SKUs.
4. Append results to `logs/experiments.csv` (per `commit-and-track` convention):
   run_id, date, embedding_model_version, decay_constant, mape_score,
   naive_baseline_mape, num_skus_evaluated, git_commit_hash.
5. Update CONTEXT.md's "Backtest / experiment results so far" section.

**Outputs:** `logs/experiments.csv` row, CONTEXT.md updated

**Edge cases:**
- Model doesn't beat naive baseline → report this plainly, don't hide it. It's
  a valid, useful result that tells us where to invest next.
- Fewer than 20 held-out SKUs available → flag before running; results won't
  be reliable enough to act on.
- **Leave-one-out with multi-vector embeddings:** exclusion must cover ALL
  photo vectors for the SKU under test (e.g. sku_id_img0 through img4), not
  just one ID. Verify exclusion by confirming zero vectors with the tested
  SKU's sku_id remain in query results before trusting any backtest run.

**Learnings log:**
-
