# Visual SKU Allocation System — Full Architecture & Build Plan (v1)

**Scope of this version:** Attribute-based + visual-similarity-based demand estimation, feeding your existing two-pass allocation loop. The LightGBM multi-signal combiner (price, recency, visual, attributes as learned weights) is intentionally deferred to v2 — flagged clearly at the end so you know exactly what to build next and why v1 sets it up cleanly.

**Data source:** Snowflake.
**Assumed background:** Beginner in Python and ML — every step below spells out *what* to do, *why*, and roughly *how*, including setup commands.

---

## How to read this document

Each section is a self-contained stage of the pipeline. Do them in order — each one produces an output the next one consumes. At the end of every section there's a **"Definition of Done"** checklist — don't move to the next section until you can tick every box. This is deliberate: since this prototype needs to become the base of everything you build later, each stage needs to be genuinely solid, not just "good enough to move on."

```
SECTION 0: Project Foundations
        │
SECTION 1: Extract Data from Snowflake
        │
SECTION 2: Clean & Encode Attributes
        │
SECTION 3: Generate Visual Embeddings
        │
SECTION 4: Build the Vector Store & Similarity Search
        │
SECTION 5: Combine Signals → Demand Estimate (v1: rule-based)
        │
SECTION 6: Feed Into Your Allocation Engine
        │
SECTION 7: Capture Feedback & Overrides
        │
SECTION 8: Evaluate — Did It Actually Work?
        │
SECTION 9: Version & Track Everything
        │
SECTION 10: V2 Roadmap (LightGBM combiner)
```

---

## SECTION 0: Project Foundations

### 0.1 Why this section matters

Before writing a single line of model code, you need a project skeleton that's built to be extended, not thrown away. A huge number of "prototypes that couldn't graduate to production" fail not because the model was bad, but because the code was written as a one-off notebook with no structure — so nobody (including future-you) can safely build on it.

### 0.2 Define what "success" means, in numbers, before you start

Write these down now, even if roughly. You cannot tell if v2 is better than v1 without this.

- **Primary metric**: Forecast accuracy — e.g., Mean Absolute Percentage Error (MAPE) between predicted store-level demand and actual sell-through for a held-out set of past SKUs. (MAPE = average of how far off your prediction was, as a percentage of the actual value — lower is better.)
- **Business metrics** (track alongside): stockout rate (how often a store sold out and lost sales) and markdown rate (how much stock had to be discounted because it didn't sell) for SKUs allocated using this system, versus the current manual process.
- **Adoption metric**: how often merchandisers accept the model's suggestion versus override it, and why (captured in Section 7).

### 0.3 Set up your project folder structure

This structure is designed so that v2 (adding LightGBM, adding new data sources) slots in without you rewriting v1.

```
sku-allocation/
├── config/
│   └── settings.yaml          # all constants: paths, weights, thresholds — never hardcode these in code
├── data/
│   ├── raw/                   # untouched exports from Snowflake — never edit these files
│   ├── processed/             # cleaned tables ready for modeling
│   └── embeddings/            # saved visual + attribute embeddings
├── src/
│   ├── extract/                # Section 1 code
│   ├── features/               # Section 2 & 3 code (attribute encoding, visual embedding)
│   ├── retrieval/               # Section 4 code (vector store, similarity search)
│   ├── demand_estimation/       # Section 5 code
│   └── evaluation/              # Section 8 code
├── notebooks/                  # exploration/experiments ONLY — nothing here should be required to run the pipeline
├── models/                      # saved model files, embedding indexes
├── logs/                        # run logs, experiment tracking (Section 9)
└── README.md
```

**Why this matters for you specifically:** you called out that this prototype needs to be the base for future versions. The single biggest thing that determines whether that's true is whether your data extraction, feature-building, and modeling code are separated into reusable functions (in `src/`) rather than living only inside a notebook. Notebooks are for exploring; `src/` is for anything that needs to run again.

### 0.4 Environment setup (do this once)

```bash
# 1. Create an isolated Python environment so this project's packages don't clash with anything else on your machine
python -m venv venv

# 2. Activate it (run this every time you start working on the project)
# On Mac/Linux:
source venv/bin/activate
# On Windows:
venv\Scripts\activate

# 3. Install the core packages you'll need across all sections
pip install snowflake-connector-python pandas numpy pyyaml
pip install open_clip_torch torch torchvision --extra-index-url https://download.pytorch.org/whl/cpu
pip install chromadb pillow scikit-learn matplotlib
```

A couple of terms explained since you're new to this:
- **Virtual environment (`venv`)**: a self-contained bubble of Python packages just for this project, so installing something here never breaks another project on your laptop.
- **`torch` (PyTorch)**: the underlying deep-learning library that FashionCLIP/Marqo models are built on. You don't need to understand its internals — you're using it the way you'd use a calculator, not building one.

### 0.5 Version control (git) — non-negotiable for "this becomes the base of future versions"

```bash
git init
echo "venv/
data/raw/
data/processed/
models/
*.pyc
__pycache__/" > .gitignore
git add .
git commit -m "Initial project structure"
```

Commit after every section below. This gives you a rollback point if something breaks, and a clear history of what changed as you move from v1 to v2 — genuinely important for a project you plan to keep extending.

### Definition of Done — Section 0
- [ ] Folder structure created
- [ ] Virtual environment created and packages installed
- [ ] Git repository initialized with first commit
- [ ] Success metrics written down (even roughly) in `README.md`

---

## SECTION 1: Extract Data From Snowflake

### 1.1 What you need to pull

Three tables, minimum:

1. **SKU master** — SKU ID, all attribute tags, product photo file path/URL, category, launch date, MRP (launch price).
2. **Sales/inventory history** — SKU ID, store ID, date, units sold, current price on that date (captures markdowns), returns (if tracked separately).
3. **Store master** — store ID, region, store tier/size, format, and current inventory/weeks-of-cover if available.

If store tier or region isn't cleanly available, flag this now — it's a genuine gap (see Section 0's missed-data-points discussion) and worth getting from whoever owns store master data before Section 6.

### 1.2 Connect to Snowflake from Python

```python
# src/extract/snowflake_client.py
import snowflake.connector
import pandas as pd
import yaml

def get_connection(config_path="config/settings.yaml"):
    with open(config_path) as f:
        cfg = yaml.safe_load(f)["snowflake"]
    conn = snowflake.connector.connect(
        user=cfg["user"],
        password=cfg["password"],       # better: use key-pair auth or env variables instead of plaintext — ask IT/data team
        account=cfg["account"],
        warehouse=cfg["warehouse"],
        database=cfg["database"],
        schema=cfg["schema"],
    )
    return conn

def run_query(query, config_path="config/settings.yaml"):
    conn = get_connection(config_path)
    df = pd.read_sql(query, conn)
    conn.close()
    return df
```

**Important — never hardcode credentials in code.** Put them in `config/settings.yaml` and make sure that file is in `.gitignore` (already covered above) so it never gets committed to version control. Better still, ask your data/IT team whether they use key-pair authentication or a secrets manager rather than a plaintext password — worth a five-minute conversation before you build anything long-lived on this.

### 1.3 Pull the three tables

```python
# src/extract/pull_data.py
from snowflake_client import run_query

sku_master = run_query("""
    SELECT sku_id, category, color, fabric, fit, sleeve_length,
           pattern, occasion, factory, launch_date, mrp, photo_path
    FROM sku_master_table
""")

sales_history = run_query("""
    SELECT sku_id, store_id, sale_date, units_sold, selling_price, units_returned
    FROM sales_fact_table
""")

store_master = run_query("""
    SELECT store_id, region, store_tier, store_format, sqft
    FROM store_master_table
""")

sku_master.to_csv("data/raw/sku_master.csv", index=False)
sales_history.to_csv("data/raw/sales_history.csv", index=False)
store_master.to_csv("data/raw/store_master.csv", index=False)
```

Adjust table/column names to match your actual Snowflake schema — ask your data engineering team for the exact table names if you don't have direct schema visibility.

**Practical tip:** pull a limited date range first (e.g., last 2 seasons) to keep the prototype fast to iterate on. Widen the window once the pipeline works end-to-end.

### 1.4 Photo access

Your `photo_path` column probably points to a URL or a shared drive/blob storage path, not a local file. Write a small downloader that pulls each photo locally once (into `data/raw/images/`) so Section 3 doesn't need live Snowflake/network access every time it runs — this is both faster and avoids repeatedly hitting your image storage system.

### Definition of Done — Section 1
- [ ] Can connect to Snowflake from Python successfully
- [ ] Three raw CSVs saved in `data/raw/`
- [ ] Photos downloaded locally and every SKU's `photo_path` resolves to an actual accessible image file
- [ ] Credentials are NOT hardcoded in any committed file

---

## SECTION 2: Clean & Encode Attributes

### 2.1 Cleaning checklist (do this before any encoding)

- Remove duplicate SKU rows.
- Standardize tag casing/spelling ("Half Sleeve" vs "half sleeve" vs "Half-Sleeve" should all become one value).
- Decide how to handle missing tags (e.g., missing fabric) — don't silently drop the row; flag it in a `has_missing_attributes` column so you can review these later.
- Confirm each SKU has exactly one resolvable photo before moving on.

### 2.2 Turn tags into a vector (the "attribute embedding")

Two options, simplest first:

**Option A — Multi-hot encoding (start here, genuinely fine for v1)**
Every unique tag across your whole catalog becomes one column; 1 if the SKU has that tag, 0 if not.

```python
# src/features/attribute_encoding.py
import pandas as pd

def multi_hot_encode(sku_df, tag_columns):
    # tag_columns = ['category','color','fabric','fit','sleeve_length','pattern','occasion']
    dummies = pd.get_dummies(sku_df[tag_columns])
    return pd.concat([sku_df[['sku_id']], dummies], axis=1)
```

**Option B — Dense text embedding (upgrade later, not needed for v1)**
Run the concatenated tag list through a small sentence-embedding model so semantically similar tags ("Half Sleeve" and "Short Sleeve") land near each other, instead of being treated as completely unrelated columns like multi-hot encoding does. Skip this for v1 — multi-hot is simpler, fully interpretable, and enough to prove the concept.

### Definition of Done — Section 2
- [ ] Cleaned SKU table saved to `data/processed/sku_clean.csv`
- [ ] Attribute vector generated for every SKU, saved to `data/embeddings/attribute_vectors.csv`
- [ ] You can manually spot-check 5 SKUs and confirm their attribute vector correctly reflects their tags

---

## SECTION 3: Generate Visual Embeddings

### 3.1 Load the model

Using Marqo-FashionSigLIP (recommended from our earlier comparison — free, open, best fashion-specific benchmark performance):

```python
# src/features/visual_embedding.py
import open_clip
import torch
from PIL import Image

model, _, preprocess = open_clip.create_model_and_transforms(
    'hf-hub:Marqo/marqo-fashionSigLIP'
)
model.eval()

def embed_image(image_path):
    image = preprocess(Image.open(image_path).convert("RGB")).unsqueeze(0)
    with torch.no_grad():
        embedding = model.encode_image(image)
    return embedding.squeeze().numpy()
```

### 3.2 Embed your whole catalog once, save it

```python
# src/features/build_visual_index.py
import pandas as pd
import numpy as np
from visual_embedding import embed_image

sku_df = pd.read_csv("data/processed/sku_clean.csv")

embeddings = {}
for _, row in sku_df.iterrows():
    embeddings[row["sku_id"]] = embed_image(row["photo_path_local"])

np.save("data/embeddings/visual_embeddings.npy", embeddings)
```

**Why save this instead of recomputing every time:** generating embeddings is the slowest step in the whole pipeline. Do it once per SKU, store the result, and only regenerate for new/changed SKUs going forward — never re-embed your entire historical catalog on every run.

### 3.3 Sanity-check before moving on (important, don't skip)

Manually pick 5 SKUs you know well. Find their nearest neighbors by visual embedding distance (cosine similarity) and eyeball whether the matches actually look similar to a human. If they don't, something's wrong before Section 4 — check photo quality/consistency first (background, cropping, lighting), since that's the most common cause.

```python
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np

embeddings = np.load("data/embeddings/visual_embeddings.npy", allow_pickle=True).item()
sku_ids = list(embeddings.keys())
vectors = np.array([embeddings[s] for s in sku_ids])

target_idx = sku_ids.index("YOUR_TEST_SKU_ID")
similarities = cosine_similarity([vectors[target_idx]], vectors)[0]
top_matches = sorted(zip(sku_ids, similarities), key=lambda x: -x[1])[:6]  # top 6, first will be itself
print(top_matches)
```

### Definition of Done — Section 3
- [ ] Every SKU has a saved visual embedding
- [ ] Manual spot-check of 5 SKUs shows visually sensible nearest neighbors
- [ ] Embedding generation code is in `src/`, not just a notebook, and re-runnable for new SKUs only

---

## SECTION 4: Build the Vector Store & Similarity Search

### 4.1 Why Chroma for v1

As discussed earlier — Chroma is the simplest option to stand up locally, ideal for the prototype stage. You can swap to Qdrant later (Section 10 / v2) without changing anything upstream, since the "embed → store → query nearest neighbors" interface stays the same.

### 4.2 Set it up

```python
# src/retrieval/vector_store.py
import chromadb
import numpy as np

client = chromadb.PersistentClient(path="models/chroma_db")
collection = client.get_or_create_collection(name="sku_visual_embeddings")

def index_all_skus(embeddings_dict, sku_metadata_df):
    ids = list(embeddings_dict.keys())
    vectors = [embeddings_dict[i].tolist() for i in ids]
    metadatas = sku_metadata_df.set_index("sku_id").loc[ids].to_dict("records")
    collection.add(ids=ids, embeddings=vectors, metadatas=metadatas)

def find_similar(new_sku_embedding, category_filter, top_k=20):
    results = collection.query(
        query_embeddings=[new_sku_embedding.tolist()],
        n_results=top_k,
        where={"category": category_filter}   # this is your attribute-based hard filter from Section 2
    )
    return results
```

### 4.3 Similarity Search — Tiered Filtering & Scoring Logic (FINAL)

**Purpose:** given a query SKU, return the top 10 visually-and-attribute-similar SKUs from the T-shirt catalog. This output feeds TWO downstream consumers — company-level demand estimation for the new SKU, and store-level allocation (which stores + how much) — NOT a customer-facing browse/recommendation feature. Price is deliberately not yet a filter here (see Tier 4 note).

---

#### QUERY SKU eligibility (separate from candidate pool rules below)
- Query SKU can be ANY status, including draft with no `FINAL_LIVE_DATE`.
- This is the expected normal case — the system exists to solve cold-start for brand-new, not-yet-launched SKUs. The Tier 0 status rule below applies ONLY to the candidate/comparison pool being searched through, never to the query SKU itself.

---

#### Tier 0 — Hard filter on CANDIDATE POOL only (always applied first)
- `CATEGORY` = T-Shirts
- `STATUS` = active, OR (`STATUS` = draft AND `FINAL_LIVE_DATE` IS NOT NULL)
- Candidates that are draft AND have no `FINAL_LIVE_DATE` are excluded — they have no launch/sales history to lend as a valid comparable.

#### Tier 1 — Hard filter cascade (sequential, in this exact order)
1. `COLLAR_NEW`
2. `FIT_NORMALIZED` (see mapping below)
3. `MATERIAL_NEW`

**FIT normalization mapping:**
- `Cropped Oversized Fit`, `Box Fit`, `Oversized Fit`, `Relaxed Fit` → **Oversized**
- `Slim Fit` → **Slim**
- everything else → **Regular**
(Original granular FIT value retained separately as a Tier 2 soft signal.)

**Cascade trigger — quality-gated, not count-gated:**
- Start at the narrowest bucket (collar+fit+material). Score visual similarity for every candidate in this bucket.
- Keep only candidates whose `final_score` clears the evidence-based floor (see "Threshold calibration" below).
- If 10+ qualifying candidates found → STOP, return top 10 by `final_score`.
- If fewer than 10 → drop filters one at a time, in this order: drop `MATERIAL_NEW` → then `FIT_NORMALIZED` → then `COLLAR_NEW`.
- At each broader step, score ONLY newly-exposed candidates (set difference from the previous, narrower bucket) — never re-score a candidate already evaluated at a tighter tier.
- A candidate that failed the floor at a tighter tier is PERMANENTLY rejected — not reconsidered at a broader tier.
- Each surviving candidate is tagged with the TIGHTEST tier it was found and scored in (never upgraded/downgraded later).
- If all tiers are exhausted (down to category+status only) and still fewer than 10 qualifying candidates exist, return whatever was found — never pad with sub-threshold matches to force 10.
- Record the FULL evaluated candidate list (not just final top 10) for future backtesting and threshold tuning.

#### Tier 2 — Soft filters (score boost, not exclusion)
`SLEEVE_TYPE`, `CLOSURE`, `POCKET`, `STYLE`, `FABRIC_WEIGHT`, `COMPOSITION`, `OCCASSION_NEW`
- Direct categorical match per attribute (query value == candidate value), plain lookup — NOT multi-hot vector similarity.
- `soft_match_boost` = weighted count of matching attributes. v1 default: equal weighting across all 7 (simple proportion matched). Revisit weighting once backtest data exists.
- Original granular `FIT` (pre-normalization) is retained here as an ADDITIONAL soft signal, separate from `FIT_NORMALIZED` used in Tier 1.
- Every output row records WHICH specific Tier 2 attributes matched (e.g. `["SLEEVE_TYPE", "STYLE"]`) — not just the aggregate boost number.
- Multi-hot attribute encoding is NOT used anywhere in this scoring logic. Remains a valid input for v2's LightGBM combiner only.

#### Tier 3 — Aesthetic layer (diagnostic only, NOT part of the score)
`DESIGNS`, `PRINT_DESIGN`
- Surfaced as a diagnostic flag (does visual-model ranking agree with the PRINT_DESIGN/DESIGNS tag or not?) — never influences ranking.

#### Tier 4 — Output metadata (not filtering, not scoring)
- `MRP_BUCKET` derived from `MRP` in `image_search_master`.
- `GP` = `MRP − COGS`, both pulled from `image_search_master`.
- `COLOR` used as a display/sort convenience and as the key signal for obvious/other bifurcation.
- NOT used as a filter or sort key in scoring yet — deferred decision. Do not let this quietly become a filter without an explicit update here.
- Two independent GP-priority sort toggles available downstream only (presentation layer, applied AFTER top-10 is selected, never changes which SKUs enter the demand math):
  (a) closest-price-tier-first, GP breaks ties
  (b) highest-GP-overrides-price-proximity

#### Final blended score formula
$$\text{final\_score} = \text{visual\_similarity} \times \text{tier\_confidence\_multiplier} \times (1 + \text{soft\_match\_boost})$$

- The `+1` ensures soft filters can only ever BOOST the score, never zero it out — a candidate with zero Tier 2 matches gets `(1+0)=1`, leaving the base score (visual_similarity × tier_confidence_multiplier) untouched. Each additional soft match adds a proportional increment on top.
- `tier_confidence_multiplier` starting values (TBD exact numbers, to be validated against backtest data): 1.0 (collar+fit+material) / 0.8 (collar+fit) / 0.6 (collar-only) / 0.4 (category+status only).

#### Threshold calibration (evidence-based, not guessed)
- The blended-score floor gating cascade progression must be derived from real data. Method: identify known colorway-sibling SKU pairs (same style, different color) and compute their blended scores — use that distribution to set the floor. Revisit as more backtest data accumulates.

#### Output bifurcation: Obvious vs. Other matches
- **Obvious matches**: literal same style, different colorway of the query SKU (genuine colorway siblings).
- **Other matches**: everything else in the top 10.

---

#### Output sheet format
**Single header block** (query SKU, shown once, above all candidate rows):
`SKU_GROUP`, `PRODUCT_NAME`, and its attribute values (COLLAR_NEW, FIT, FIT_NORMALIZED, MATERIAL_NEW, and Tier 2/3 attribute values).

**10 candidate rows below**, one row per matched SKU, columns:
- `CANDIDATE_SKU_GROUP`
- `CANDIDATE_PRODUCT_NAME`
- `FINAL_SCORE`
- `VISUAL_SIMILARITY` (component 1)
- `TIER_CONFIDENCE_MULTIPLIER` (component 2)
- `SOFT_MATCH_BOOST` (component 3, the `(1 + boost)` value)
- `IMAGE_LINK_1`, `IMAGE_LINK_2` (best two Shopify image URLs from `image_search_master`)
- `TIGHTEST_TIER_TAG` (e.g. `collar+fit+material`, `collar+fit`, `collar`, `category`)
- `SOFT_FILTERS_MATCHED` (list of matched Tier 2 attributes)
- `TIER_3_DIAGNOSTIC` (agreement flag on PRINT_DESIGN/DESIGNS)
- `MRP_BUCKET`
- `COLOR`
- `GP`
- `MATCH_TYPE` (`Obvious` or `Other`)

---

#### Open dependency
This output feeds company-level demand estimation and store-level allocation. Price is NOT a pre-filter here for now (see Tier 4) — a deliberate, temporary divergence from the original demand-estimation architecture (price as pre-filter bucket), to be reconciled once the price-filter decision is finalized.

### Definition of Done — Section 4
- [ ] All SKU embeddings loaded into Chroma with attribute metadata attached
- [ ] `find_similar()` returns top 10 matching SKUs using the Tiered Filtering & Scoring cascade
- [ ] For each matching SKU, the output correctly records the similarity score, multiplier, soft boost, and matched attributes
- [ ] Obvious vs. Other output bifurcation is correctly tagged based on style ID matching


---

## SECTION 5: Combine Signals → Demand Estimate (v1: rule-based)

### 5.1 The logic, step by step

For a new SKU with no sales history:

1. Filter to visually-and-attribute-similar past SKUs (Section 4's `find_similar`), restricted to the same category, fabric, and price tier (bucket price into tiers now, per our price discussion — don't compare across tiers).
2. Apply a recency weight to each match, so older comparables count for less:
   `weight = similarity_score * exp(-months_since_launch / decay_constant)`
   Start with `decay_constant = 12` (roughly a 1-year half-life) and tune later against real outcomes.
3. Pull each matched SKU's store-level sell-through history.
4. Compute a **weighted average sell-through per store/region**, using the weights from step 2, as your demand estimate for the new SKU.

```python
# src/demand_estimation/estimate_demand.py
import numpy as np
import pandas as pd

def estimate_store_demand(similar_skus, sales_history_df, decay_constant=12):
    weighted_rows = []
    for sku_id, similarity, months_old in similar_skus:
        weight = similarity * np.exp(-months_old / decay_constant)
        sku_sales = sales_history_df[sales_history_df["sku_id"] == sku_id]
        store_sales = sku_sales.groupby("store_id")["units_sold"].sum().reset_index()
        store_sales["weight"] = weight
        weighted_rows.append(store_sales)

    combined = pd.concat(weighted_rows)
    demand_estimate = (
        combined.groupby("store_id")
        .apply(lambda g: np.average(g["units_sold"], weights=g["weight"]))
        .reset_index(name="estimated_demand")
    )
    return demand_estimate
```

### 5.2 Why rule-based and not LightGBM yet

You need enough historical *validated* predictions (Section 8) before a learned model like LightGBM has anything useful to learn from — feeding it too little data, or data you haven't yet validated as sensible, risks learning noise. The rule-based version above is fully interpretable (a merchandiser can see exactly which past SKUs drove a number) and gives you the labeled dataset (`predicted demand` vs `actual demand`) that the v2 LightGBM model will train on. This is a deliberate, sequenced choice, not a shortcut.

### Definition of Done — Section 5
- [ ] Demand estimate function runs end-to-end for a test "new" SKU (one you're holding out from training/matching)
- [ ] Output is a clean table: SKU, store, estimated demand
- [ ] You can trace any single number back to which past SKUs and weights produced it

---

## SECTION 6: Feed Into Your Allocation Engine

### 6.1 The handoff contract

Your existing two-pass allocation loop expects a demand signal per store, per SKU, to drive Loop 1 (full-size fills) and Loop 2 (remaining/cut-size fills from the merged pool). The output table from Section 5 (`sku_id, store_id, estimated_demand`) should be shaped to plug into that loop exactly the same way real historical sales data would.

### 6.2 One addition worth making here

Add a `demand_source` column (`"actual_sales"` vs `"visual_similarity_estimate"`) alongside every row going into the allocation engine. This costs nothing to add now and is exactly the auditability feature that lets merchandisers apply appropriate scrutiny to estimated-vs-known numbers, and lets you later measure allocation quality separately for each source.

### Definition of Done — Section 6
- [ ] Section 5's output correctly feeds your existing allocation loop with no manual reshaping
- [ ] `demand_source` flag present on every row
- [ ] A full run — new SKU photo in, final store-level unit allocation out — works end-to-end

---

## SECTION 7: Capture Feedback & Overrides

### 7.1 Why this can't wait until v2

Every time a merchandiser overrides a model-suggested allocation, that's a labeled data point about where the model was wrong — and it's also exactly the training data v2's LightGBM model will need. If you don't capture it from day one of v1, you'll wish you had six months in.

### 7.2 What to log, every time

```
sku_id, store_id, model_estimated_demand, merchandiser_final_allocation,
override_flag, override_reason (free text or dropdown), timestamp, merchandiser_id
```

A simple shared spreadsheet or a Snowflake table you write back to is completely fine for v1 — the point is that it exists and is being filled consistently, not that it's fancy.

### Definition of Done — Section 7
- [ ] Every allocation decision (model-driven or overridden) is logged somewhere durable
- [ ] Override reason is captured, not just the fact that an override happened

---

## SECTION 8: Evaluate — Did It Actually Work?

### 8.1 Backtesting method

Take SKUs you already have full history for. For each one, pretend you didn't — use only its photo and tags, run the full v1 pipeline, and compare the predicted demand against what actually happened.

```python
# src/evaluation/backtest.py
import numpy as np

def mape(actual, predicted):
    actual, predicted = np.array(actual), np.array(predicted)
    return np.mean(np.abs((actual - predicted) / np.maximum(actual, 1))) * 100
```

Run this across a few dozen held-out SKUs, not just one or two — a single lucky/unlucky example tells you nothing reliable.

### 8.2 Compare against a naive baseline

Always compare your model's MAPE against the simplest possible baseline — e.g., "just use the category average sell-through for every store." If your visual+attribute model doesn't beat this simple baseline, that's critical information, not a failure to hide — it tells you exactly where to invest next (better photos? better attribute data? the visual signal genuinely isn't adding value for your catalog?).

### Definition of Done — Section 8
- [ ] Backtest run across at least 20-30 held-out SKUs
- [ ] MAPE (or your chosen metric) computed for both the model and the naive baseline
- [ ] Results written down somewhere durable (not just console output) — this becomes your v1 vs v2 comparison point

---

## SECTION 9: Version & Track Everything

### 9.1 Minimum viable tracking (no fancy tools needed yet)

For every run, log to a simple CSV or text file in `logs/`:

```
run_id, date, embedding_model_version, decay_constant, category_filter_rules,
mape_score, num_skus_evaluated, git_commit_hash
```

The `git_commit_hash` matters — run `git rev-parse HEAD` and save it alongside your results, so you can always reproduce exactly which code version produced which numbers. This is the difference between "a project you can keep building on" and "a black box even you can't fully explain in six months."

### Definition of Done — Section 9
- [ ] A log file exists recording every experiment run with its settings and results
- [ ] Git commit hash captured alongside every logged result

---

## SECTION 10: V2 Roadmap — The LightGBM Combiner (not built now, but designed for)

This is the "bigger architectural point" from our discussion, sequenced properly:

**What changes in v2:** instead of the hand-tuned weighted rule from Section 5 (fixed decay constant, fixed similarity weighting), you train a LightGBM regression model where each row is a past (SKU, store) pair, and the features are:

- visual similarity score to nearest matches
- attribute match score
- price tier / price difference from comparables
- recency-decayed weight
- season/occasion match flag
- store features (region, tier, size)

...and the target is actual historical sell-through. LightGBM will learn, from your real data, how much weight each signal deserves — rather than you guessing constants like `decay_constant=12`.

**Why this is v2, not v1:** LightGBM needs a reasonably sized, *already validated* dataset of (features → actual outcome) pairs to learn from. Section 8's backtest results and Section 7's override logs are exactly the data that makes this possible — which is why v1, done properly, is a genuine prerequisite rather than throwaway work. You are not redoing v1's work in v2; you're feeding v1's outputs into a smarter combiner.

**What to preserve as you build v2:** keep the Section 5 rule-based output around as a permanent baseline. Every future model iteration should be judged against "did this beat the simple rule-based version," using the exact backtest method from Section 8.

---

## Final Architecture Diagram (v1)

```
Snowflake (SKU master, sales history, store master)
        │  [Section 1]
        ▼
Cleaned attribute table  +  Downloaded product photos
        │  [Section 2]              │  [Section 3]
        ▼                           ▼
Attribute vectors (multi-hot)   Visual embeddings (Marqo-FashionSigLIP)
        │                           │
        └───────────┬───────────────┘
                     ▼  [Section 4]
        Chroma vector store (visual embeddings + attribute metadata)
                     │
        New SKU photo + tags ──► filter (category/fabric/price tier)
                     │           ──► rank by visual similarity
                     ▼  [Section 5]
        Recency-weighted demand estimate per store
                     │  [Section 6]
                     ▼
        Your existing two-pass allocation loop
                     │
                     ▼
        Final store-level unit allocation  +  demand_source flag
                     │  [Section 7]
                     ▼
        Merchandiser review/override, logged
                     │  [Section 8 & 9]
                     ▼
        Backtested, versioned, ready to inform v2 (LightGBM combiner)
```
