# Directive: Generate Visual Embeddings

**Goal:** Produce and save a visual embedding for every SKU photo, using Marqo-FashionSigLIP.

**Photo handling — multi-vector per SKU, slot-number-agnostic:**
image_link_1 through image_link_5 do NOT have a standardized angle mapping
across SKUs. Do NOT assume any slot position represents a specific angle.
1. Embed all available photos per SKU (typically 5, good quality — no
   quality filtering needed for this catalog).
2. Deduplicate near-identical embeddings per SKU (cosine similarity > 0.98)
   before storing.
3. Store each surviving photo as a SEPARATE vector tagged with sku_id in
   metadata — never blend multiple photos into one averaged embedding.
4. At query/inference time (new SKU), embed ALL available photos of the new
   SKU too, not just one — merge/average results across them so the
   comparison isn't lopsided (multi-angle catalog vs. single-angle query).

**Known tradeoff — photo-count bias:** rank candidate SKUs using AVERAGE
distance across their matched photos, not single-best-photo distance, in
find_similar_skus(), to avoid unfairly favoring SKUs with more surviving photos.

**Pre-embedding photo filtering (one-time, run before batch embedding):**
Some downloaded photos are non-product images (size charts, banners,
blurry) and must be filtered out before embedding — separate concern from
the multi-vector angle-handling decision. Use execution/filter_photos.py
(CLIP zero-shot classification against data/raw/images/), producing
data/processed/photo_filter_log.json. Only size charts and banners are
excluded; product and lifestyle photos are both kept. Manually spot-check
~20-30 flagged results before trusting the filter at full scale. Only embed
photos marked keep=True. Runtime: ~30min-2hrs for the full T-shirt catalog,
run in batches of 50-100 with progress saved.

**Pre-embedding photo filtering — only excludes size_chart and banner
categories.** Product AND lifestyle photos are both kept — lifestyle shots
still show the real garment (sometimes the only source for certain angles)
and are not equivalent to true non-product noise like size charts/banners.

**Inputs:** `data/processed/sku_clean.csv` (must exist — run cleaning first if not)

**Tools to use:**
- `execution/visual_embedding.py` — `embed_image()`
- `execution/build_visual_index.py` — batch runner

**Steps:**
1. Check `data/embeddings/visual_embeddings.npy` for already-processed SKUs; skip those.
2. Process remaining SKUs in batches of 50–100 (hardware limit: M1 Air, 8GB —
   do not increase batch size without user confirmation).
3. Save progress after every batch, not just at the end.
4. On completion, run the sanity check: pick 3 known SKUs, print their top-5
   nearest neighbors by cosine similarity, and report whether they look
   visually sensible.

**Outputs:** `data/embeddings/visual_embeddings.npy`, sanity-check report

**Edge cases:**
- Memory error → halve batch size, log the new size in Learnings below, retry once.
- Unresolvable photo path → skip that SKU, log its ID, don't halt the whole batch.
- Do NOT attempt local fine-tuning — flag to user that this needs Colab/GPU.

**Learnings log:**
-
