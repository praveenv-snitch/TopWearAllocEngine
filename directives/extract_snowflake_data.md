# Directive: Extract Snowflake Data

**Goal:** Pull SKU master, sales history, and store master tables from Snowflake
into local CSVs, ready for cleaning. v1 pilot scope: Kerala cluster output,
full T-shirt category catalog.

**Inputs:** None required from user unless schema/table names have changed
(see Known Table Names below).

**Tools to use:**
- `execution/snowflake_client.py` — connection handling, reads creds from `.env`
- `execution/pull_data.py` — the three named pull functions below

**Known table names:**
- SKU master: `snitch_db.maplemonk.image_search_master`
- Sales history: `snitch_db.maplemonk.image_search_sales_history`
- Store master: `SNITCH_DB.MAPLEMONK.IMAGE_SEARCH_STORE_MASTER`

**v1 pilot scope — apply these filters:**
- `store_master` and `sales_history` → filter to Kerala's 2 stores only
  (`WHERE branch_code IN ('KL_STORE_1', 'KL_STORE_2')` — replace with real codes)
- `sku_master` → filter to T-shirt category only, but do NOT filter by store/region
  (`WHERE category = 'T-Shirts'` — confirm exact category value in your data)
- This asymmetry is intentional: output stores are scoped down, the comparison
  catalog is scoped by category only, not by geography. Do not narrow sku_master
  to only SKUs that have sold in Kerala — see CONTEXT.md decisions log for why.

**SKU master must include:** all 5 image_link columns (not just one),
FINAL_LIVE_DATE, ORIGINAL_PRICE, CURRENT_SLASHED_PRICE. Confirm with data
team whether MATERIAL_NEW or MATERIAL_MAPPED is canonical before encoding.

**Fill-rate columns — separate pull, not merged into sku_master.csv:**
Pull all *_FILL_RATE columns into `data/raw/attribute_fill_rates.csv`, keyed
by SKU_GROUP. Do NOT merge into sku_master.csv — used in Section 2 for
data-quality flagging only, never encoded as an attribute. RISE_FILL_RATE
can be excluded entirely for this T-shirt-scoped pilot.

**Store master — already pre-built with essential columns, no further
filtering needed on column selection.** Tiering basis: CATEGORY_BASE_STOCK,
not square footage or overall BASE_STOCK.

**Photo download — resize, keep all photos, no angle selection:**
Resize every available photo (~5 per SKU) during download — do not store
full-resolution originals. Do NOT attempt to select "best" photos or assume
any image_link slot represents a specific angle (confirmed inconsistent across
catalog — e.g. image_link_1 is front for most SKUs but back for back-print tees).
Angle handling is resolved in the embedding step (see generate_visual_embeddings.md),
not here.

**Photo compression detail:** Use JPEG quality=90 (not aggressive compression)
when resizing — negligible quality impact on embeddings at this setting,
while still achieving most of the storage reduction. Before finalizing resize
target size, check open_clip's preprocess.transforms for Marqo-FashionSigLIP
to confirm the model's actual expected input resolution — resize directly to
that value rather than assuming 384x384.

**Steps:**
1. Confirm `.env` has SNOWFLAKE_USER, SNOWFLAKE_ACCOUNT, SNOWFLAKE_WAREHOUSE,
   SNOWFLAKE_DATABASE, SNOWFLAKE_SCHEMA. If missing, stop and ask — never invent values.
2. Run `pull_data.pull_sku_master()`, `pull_sales_history()`, `pull_store_master()`,
   `pull_attribute_fill_rates()`, applying the scope filters above.
3. Save each to `data/raw/<name>.csv`. Do not overwrite an existing file without confirming.
4. Download and resize photos per the photo handling rules above, into
   `data/raw/images/`.
5. Report row counts per table and flag any table returning 0 rows or
   unexpectedly-null columns.

**Outputs:** `data/raw/sku_master.csv`, `data/raw/sales_history.csv`,
`data/raw/store_master.csv`, `data/raw/attribute_fill_rates.csv`,
`data/raw/images/`

**Edge cases:**
- Auth error → surface the exact error, do not retry with modified credentials.
- Empty result set → flag before proceeding; do not silently continue the pipeline
  on empty data.
- Store-master CATEGORY column vs sku_master CATEGORY column — possible name
  collision, confirm meaning before assuming they're equivalent.

**Learnings log:** (append here as discovered, per Operating Principle 3)
- The store master table `IMAGE_SEARCH_STORE_MASTER` contains multiple rows per store (one for each product category like T-Shirts, Shirts, Jeans, etc.). Consequently, any JOIN with this table must include a category filter (e.g., `sm.CATEGORY = 'T-Shirts'`) in addition to the store filter (`sh.BRANCH_CODE = sm.BRANCH_CODE`) to prevent data replication/skew (e.g., matching 12 times per store).
