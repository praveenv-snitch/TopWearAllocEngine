## Similarity Search — Tiered Filtering & Scoring Logic (FINAL)

**Purpose:** given a query SKU, return the top 10 visually-and-attribute-similar
SKUs from the T-shirt catalog. This output feeds TWO downstream consumers —
company-level demand estimation for the new SKU, and store-level allocation
(which stores + how much) — NOT a customer-facing browse/recommendation
feature. Price is deliberately not yet a filter here (see Tier 4 note).

---

### QUERY SKU eligibility (separate from candidate pool rules below)
- Query SKU can be ANY status, including draft with no `FINAL_LIVE_DATE`.
- This is the expected normal case — the system exists to solve cold-start
  for brand-new, not-yet-launched SKUs. The Tier 0 status rule below applies
  ONLY to the candidate/comparison pool being searched through, never to
  the query SKU itself.

---

### Tier 0 — Hard filter on CANDIDATE POOL only (always applied first)
- `CATEGORY` = T-Shirts
- `STATUS` = active, OR (`STATUS` = draft AND `FINAL_LIVE_DATE` IS NOT NULL)
- Candidates that are draft AND have no `FINAL_LIVE_DATE` are excluded —
  they have no launch/sales history to lend as a valid comparable.

### Tier 1 — Hard filter cascade (sequential, in this exact order)
1. `COLLAR_NEW`
2. `FIT_NORMALIZED` (see mapping below)
3. `MATERIAL_NEW`

**FIT normalization mapping:**
- `Cropped Oversized Fit`, `Box Fit`, `Oversized Fit`, `Relaxed Fit` → **Oversized**
- `Slim Fit` → **Slim**
- everything else → **Regular**
(Original granular FIT value retained separately as a Tier 2 soft signal.)

**Cascade trigger — quality-gated, not count-gated:**
- Start at the narrowest bucket (collar+fit+material). Score visual
  similarity for every candidate in this bucket.
- Keep only candidates whose `final_score` clears the evidence-based floor
  (see "Threshold calibration" below).
- If 10+ qualifying candidates found → STOP, return top 10 by `final_score`.
- If fewer than 10 → drop filters one at a time, in this order:
  drop `MATERIAL_NEW` → then `FIT_NORMALIZED` → then `COLLAR_NEW`.
- At each broader step, score ONLY newly-exposed candidates (set difference
  from the previous, narrower bucket) — never re-score a candidate already
  evaluated at a tighter tier.
- A candidate that failed the floor at a tighter tier is PERMANENTLY
  rejected — not reconsidered at a broader tier.
- Each surviving candidate is tagged with the TIGHTEST tier it was found
  and scored in (never upgraded/downgraded later).
- If all tiers are exhausted (down to category+status only) and still
  fewer than 10 qualifying candidates exist, return whatever was found —
  never pad with sub-threshold matches to force 10.
- Record the FULL evaluated candidate list (not just final top 10) for
  future backtesting and threshold tuning.

### Tier 2 — Soft filters (score boost, not exclusion)
`SLEEVE_TYPE`, `CLOSURE`, `POCKET`, `STYLE`, `FABRIC_WEIGHT`, `COMPOSITION`,
`OCCASSION_NEW`

- Direct categorical match per attribute (query value == candidate value),
  plain lookup — NOT multi-hot vector similarity.
- `soft_match_boost` = weighted count of matching attributes. v1 default:
  equal weighting across all 7 (simple proportion matched). Revisit
  weighting once backtest data exists.
- Original granular `FIT` (pre-normalization) is retained here as an
  ADDITIONAL soft signal, separate from `FIT_NORMALIZED` used in Tier 1.
- Every output row records WHICH specific Tier 2 attributes matched
  (e.g. `["SLEEVE_TYPE", "STYLE"]`) — not just the aggregate boost number.
- Multi-hot attribute encoding is NOT used anywhere in this scoring logic.
  Remains a valid input for v2's LightGBM combiner only.

### Tier 3 — Aesthetic layer (diagnostic only, NOT part of the score)
`DESIGNS`, `PRINT_DESIGN`
- Surfaced as a diagnostic flag (does visual-model ranking agree with the
  PRINT_DESIGN/DESIGNS tag or not?) — never influences ranking.

### Tier 4 — Output metadata (not filtering, not scoring)
- `MRP_BUCKET` derived from `MRP` in `image_search_master`.
- `GP` = `MRP − COGS`, both pulled from `image_search_master`.
- `COLOR` used as a display/sort convenience and as the key signal for
  obvious/other bifurcation.
- NOT used as a filter or sort key in scoring yet — deferred decision.
  Do not let this quietly become a filter without an explicit update here.
- Two independent GP-priority sort toggles available downstream only
  (presentation layer, applied AFTER top-10 is selected, never changes
  which SKUs enter the demand math):
  (a) closest-price-tier-first, GP breaks ties
  (b) highest-GP-overrides-price-proximity

### Final blended score formula

final_score = visual_similarity × tier_confidence_multiplier × (1 + soft_match_boost)

- The `+1` ensures soft filters can only ever BOOST the score, never zero
  it out — a candidate with zero Tier 2 matches gets `(1+0)=1`, leaving
  the base score (visual_similarity × tier_confidence_multiplier) untouched.
  Each additional soft match adds a proportional increment on top.
- `tier_confidence_multiplier` starting values (TBD exact numbers, to be
  validated against backtest data): 1.0 (collar+fit+material) /
  0.8 (collar+fit) / 0.6 (collar-only) / 0.4 (category+status only).

### Threshold calibration (evidence-based, not guessed)
- The blended-score floor gating cascade progression must be derived from
  real data. Method: identify known colorway-sibling SKU pairs (same
  style, different color) and compute their blended scores — use that
  distribution to set the floor. Revisit as more backtest data accumulates.

### Output bifurcation: Obvious vs. Other matches
- **Obvious matches**: literal same style, different colorway of the query
  SKU (genuine colorway siblings).
- **Other matches**: everything else in the top 10.

---

### Output sheet format
**Single header block** (query SKU, shown once, above all candidate rows):
`SKU_GROUP`, `PRODUCT_NAME`, and its attribute values (COLLAR_NEW, FIT,
FIT_NORMALIZED, MATERIAL_NEW, and Tier 2/3 attribute values).

**10 candidate rows below**, one row per matched SKU, columns:
| Column | Contents |
|---|---|
| `CANDIDATE_SKU_GROUP` | |
| `CANDIDATE_PRODUCT_NAME` | |
| `FINAL_SCORE` | |
| `VISUAL_SIMILARITY` | component 1 |
| `TIER_CONFIDENCE_MULTIPLIER` | component 2 |
| `SOFT_MATCH_BOOST` | component 3, the `(1 + boost)` value |
| `IMAGE_LINK_1`, `IMAGE_LINK_2` | best two Shopify image URLs from `image_search_master` |
| `TIGHTEST_TIER_TAG` | e.g. `collar+fit+material`, `collar+fit`, `collar`, `category` |
| `SOFT_FILTERS_MATCHED` | list of matched Tier 2 attributes |
| `TIER_3_DIAGNOSTIC` | agreement flag on PRINT_DESIGN/DESIGNS |
| `MRP_BUCKET` | |
| `COLOR` | |
| `GP` | |
| `MATCH_TYPE` | `Obvious` or `Other` |

---

### Open dependency
This output feeds company-level demand estimation and store-level
allocation. Price is NOT a pre-filter here for now (see Tier 4) — a
deliberate, temporary divergence from the original demand-estimation
architecture (price as pre-filter bucket), to be reconciled once the
price-filter decision is finalized.

