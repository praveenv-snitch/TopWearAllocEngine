# CONTEXT.md — Project State (read this first, every session)

**Last updated:** 2026-07-16

## What this project is
Local visual-similarity + attribute-based demand estimation for a menswear
brand's merchandising team, feeding an existing two-pass store allocation loop.
Full architecture: see `directives/` for how-to's. This file is *current state*,
not how-to.

## Where we are right now
- **Current phase:** Section 5 — Combine Signals → Demand Estimate (v1: rule-based)
- **Last completed:** Section 4 (Build the Vector Store & Similarity Search) — Implemented the finalized Tiered Filtering & Scoring cascade (Tiers 0-4) with dynamic price bucketing (100-step dynamic increments) and automated calibration of score floor thresholds from sibling pairs. Also fixed data skew issue in `pull_cluster_data.py` (which joined store master 12 times per store).
- **Next step:** Section 5 (Combine Signals → Demand Estimate) — Implement store-level demand estimation using recency-weighted average of similar SKU sales.

## Decisions made (don't re-litigate these without a stated reason)
- v1 pilot scope: Kerala cluster only (2 stores) for sales/demand OUTPUT.
  Comparison/embedding pool is NOT geography-restricted — see catalog scope below.
- v1 catalog scope: full T-shirt category only (~3,500 SKUs), not the entire
  27k catalog. Chosen over a cross-category random sample because it's a
  coherent category boundary and fully feasible to embed on local hardware.
  Shirts and other categories are out of scope for this pilot — extend later
  once T-shirts validate.
- Backtesting uses leave-one-out: the SKU being tested is excluded from its
  own comparison pool before searching, or the model trivially matches itself.
  This is mandatory, not optional — see run_backtest.md.
- Embedding model: Marqo-FashionSigLIP (chosen over generic CLIP — see backtest note below)
- Vector store: Chroma for prototype, Qdrant planned for production
- Demand estimation: rule-based (filter by category/price tier, rank by visual
  similarity, recency-weighted) — LightGBM combiner deliberately deferred to v2
- Hardware: M1 Air 8GB — embeddings batched in chunks of 50–100, no local fine-tuning
- Store master table created as IMAGE_SEARCH_STORE_MASTER (from
  STORE_CATEGORY_DELTA). Store tiering basis is CATEGORY_BASE_STOCK, not
  square footage or overall BASE_STOCK.
- Store target rank (if added later) is used as a POST-estimate adjustment
  layer applied after Section 5's demand calculation, not blended into it —
  keeps data-driven and strategic signals separately auditable, and avoids
  circularity risk if target rank was itself influenced by past
  allocation-driven sales. Confirm with data owner how/how often target rank
  is set before relying on it.
- Rate of Sale (ROS), not raw units, is used when aggregating matched SKUs'
  historical performance in Section 5 — avoids bias toward SKUs that have
  simply been live longer. ROS is explicitly NOT included in the visual/
  attribute embedding vector — would cause data leakage and break cold-start
  comparability (new SKUs have no ROS to embed).
- Fill-rate columns (*_FILL_RATE) are pulled separately from sku_master and
  used in Section 2 to flag unreliable attribute columns / set
  has_missing_attributes per SKU. They are never encoded into the attribute
  vector themselves — they describe the column, not the SKU.
- SUPERSEDES earlier "select 2 best photos per SKU" decision: catalog has no
  standardized angle-to-slot mapping (e.g. image_link_1 is front for most
  SKUs but back for back-print tees). Resolved by embedding ALL ~5 photos
  per SKU as separate vectors (multi-vector per SKU), tagged with sku_id,
  rather than trying to select or classify angles. Retrieval finds nearest
  PHOTO (any angle, any SKU) and collapses to parent SKU. Photos are still
  resized to 384x384 JPEG on download for storage efficiency — that part of
  the original plan is unchanged, only the "pick 2" part is superseded.
- Known tradeoff of multi-vector embeddings: SKUs with more surviving photos
  (post-dedup) get more chances at a close match, independent of true visual
  similarity. Mitigated by ranking candidate SKUs on AVERAGE distance across
  matched photos, not single-best-photo distance. Revisit if backtest results
  show a correlation between a SKU's photo count and match frequency.
- v1 data extraction is a manual, one-time snapshot pull (no scheduling).
  v2 will add: (a) scheduled re-runs, (b) incremental extraction using a
  last-modified/updated timestamp column, to avoid full re-pulls every cycle.
- All photos were downloaded (not just angle-relevant ones), including some
  non-product images (size charts, banners, etc.). Added a pre-embedding
  filtering step (filter_photos.py) using CLIP zero-shot classification to
  drop these before Section 3 embedding. This does not block Section 2
  (attribute cleaning, text-only) — only needs to complete before Section 3.
- Similarity Search — Tiered Filtering & Scoring Logic (FINAL): Adopted a 4-tier filtering and scoring logic for visual similarity query. Exclude draft SKUs with no `FINAL_LIVE_DATE` from the candidate pool (Tier 0). Tier 1 applies a hard filter cascade sequentially (`COLLAR_NEW` -> `FIT_NORMALIZED` -> `MATERIAL_NEW`) quality-gated by a minimum blended score floor, falling back if fewer than 10 matches survive. Tier 2 applies a simple boost based on matching attributes (`SLEEVE_TYPE`, `CLOSURE`, `POCKET`, `STYLE`, `FABRIC_WEIGHT`, `COMPOSITION`, `OCCASSION_NEW`, and granular `FIT` raw). Tier 3 surfaces `DESIGNS`/`PRINT_DESIGN` agreement flags. Tier 4 includes `MRP_BUCKET`, `COLOR`, and `GP` as metadata. The scoring formula is:
  $$\text{final\_score} = \text{visual\_similarity} \times \text{tier\_confidence\_multiplier} \times (1 + \text{soft\_match\_boost})$$
- Visual Search Cascade Execution Method (v1): Revisit Chroma-backed ANN retrieval once the active catalog exceeds 20,000 SKUs / 100,000 photos, or in-memory search latency exceeds 50ms. Until then, exhaustive in-memory scoring via pandas + NumPy is used for exactness, scoring 100% of candidate SKUs in each tier. Chroma is retained as a dormant index scaffold populated during index runs but bypassed during active search queries.

## Known issues / open questions
- [ ] Store tier/region data completeness — not yet confirmed available
- [ ] Real Snowflake table names — placeholders in directives, need confirming

## Backtest / experiment results so far
- [none yet — update once Section 8 runs]

## Session end checklist (do this before closing a session)
1. Update "Where we are right now" above.
2. Update any directive in `directives/` with new learnings (per AGENTS.md
   Operating Principle 3).
3. Commit with a clear message (see commit conventions in AGENTS.md).
4. If mid-task, note exactly where to resume under "Next step."
