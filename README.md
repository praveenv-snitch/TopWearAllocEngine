# Snitch TopWear Allocation Engine (Shirts + T-shirts)

```
Worker cron every 2 h, 10:00-18:00 IST → GitHub Actions (or "Run workflow")
        │  python -m engine.build
        ├─ pulls live store × SKU, product, WH, ideal-mix data from Snowflake (key-pair auth)
        ├─ embeds new/changed product images (Marqo-FashionSigLIP), cached between runs
        ├─ tiered similarity search for every Shirt / T-shirt SKU
        ├─ store-level demand projection + store health
        ├─ builds index.html (one file, all interactive logic runs in the browser)
        └─ PUTs it into Workers KV ──► Worker "topwearalloc" serves it ──► your URL
```
Same hosting pattern as the IST engine. Every run updates the live site immediately.

## What the dashboard does
| Tab | What you get |
|---|---|
| **SKU Similarity & Placement** | Type a SKU code. You see whether it is **NEW** (never sold offline), **RECENT** (first offline sale ≤ 30 days ago) or **OLD**, its attributes, price/GP and WH stock by zone and size. Then the top-10 similar SKUs with score breakdown, match tier, Obvious/Other and sales/STR/returns, followed by insights. Finally, **where to allocate**: stores ranked by score, with projected ROS and 30-day sales, evidence, quantity and size split from the preferred WH zone (fallback to the other), and a cluster summary. |
| **Allocation Engine & Store Health** | Filters: zone, cluster, store type, any set of stores, category, price band, SKU freshness. Store health per store: fill vs base, category mix, options vs ideal, STR, DOI, cut %, freshness, aged stock, no-sale options, MTD vs target. Click a store to see metafield mix vs ideal, colour mix vs cluster sales, price band and size curve, plus its cut / aged / top-seller SKUs. **Allocation run**: all WH-available SKUs × the filtered stores, ranked by editable weights and capped by demand, DOI, fill ceiling and WH stock by zone and size. Download as CSV. |
| **Nudges** | SKUs inwarded to the WH in the last 21 days that are not yet allocated offline (with days in WH and projected sales), plus store alerts (low fill, broken sizes, aged stock, overstock, no fresh stock). |

How it works: `docs/similarity_logic.md` (similarity), `engine/demand.py` (projection), `engine/health.py` (benchmarks), `web/template.html` (scoring and allocation).

## Files
| Path | What it is |
|---|---|
| `engine/config.py` | Exclusions, category normalisation, scope, all tunable constants |
| `engine/sql/*.sql` | One query per dataset (live tables only) |
| `engine/snowflake_io.py` | Snowflake connection (key-pair in CI, OAuth inside a Snowflake workspace) |
| `engine/embeddings.py` | Image embeddings with an incremental cache |
| `engine/similarity.py` | Tier 0–4 cascade, floor calibration from colourway siblings |
| `engine/demand.py` | Store-level ROS projection from similar SKUs |
| `engine/health.py` | Store × category health and mix benchmarks |
| `engine/build.py` | Orchestration → payload → `index.html` → Workers KV |
| `engine/backtest.py` | Leave-one-out accuracy check of the projection |
| `web/template.html` | The dashboard |
| `worker/` | Cloudflare Worker (serves KV, optional password, cron trigger) |
| `.github/workflows/refresh.yml` | preflight → deploy-worker → refresh-data |
| `tests/smoke_dashboard.js` | Headless check of all three tabs (`node`, needs `jsdom`) |

## Credentials (same names everywhere; same Snowflake key as the IST engine)
| Name | Required | Value |
|---|---|---|
| `SNOW_ACCOUNT` | yes | `fs03183.ap-south-1.aws` |
| `SNOW_USER` | yes | Snowflake user with the key-pair |
| `SNOW_PRIVATE_KEY` | yes | Full PEM text (or base64 of it) |
| `SNOW_KEY_PASSPHRASE` | if encrypted | Key passphrase |
| `SNOW_ROLE` | optional | Role that can read `SNITCH_DB.MAPLEMONK` |
| `SNOW_WH` | optional | Defaults to `SNITCH_WH` |
| `CF_ACCOUNT_ID` | yes | Cloudflare account id (can reuse the IST account) |
| `CF_API_TOKEN` | yes | "Edit Cloudflare Workers" token (the IST one works) |
| `CF_KV_NAMESPACE_ID` | yes | **New** KV namespace, e.g. `TOPWEAR` |

## Setup (one time)
1. **Cloudflare:** Storage & Databases → KV → Create → `TOPWEAR`, and copy its Namespace ID. You can reuse the IST API token.
2. **GitHub:** create a **private** repo and push the contents of this folder as the repo root:
   ```bash
   cd TopWearAllocEngine
   git init && git add . && git commit -m "TopWear allocation engine"
   git branch -M main
   git remote add origin https://github.com/<you>/topwearalloc.git
   git push -u origin main
   ```
3. Repo → Settings → Secrets and variables → **Actions**: add every secret from the table.
4. Actions → **TopWear refresh** → **Run workflow**. The **first run embeds about 18k product images**, which takes roughly 1–2 h on GitHub's CPU runners. It checkpoints, so a cancelled run keeps its progress. The cache is saved as a release called `embeddings-cache`. Don't delete it, or the next run re-embeds everything. Daily runs after that take about 5 min.
5. **On-time schedule:** create a fine-grained GitHub token (this repo only, *Actions: Read and write*), then `cd worker && npx wrangler secret put GH_TOKEN`. The Worker cron starts the refresh every 2 hours at 10:00, 12:00, 14:00, 16:00 and 18:00 IST, and the GitHub `schedule:` is a backup. To change the time, edit both cron lists.
6. **Password (recommended; the page holds store-level sales and stock):** `cd worker && npx wrangler secret put SITE_PASSWORD`, or use Cloudflare Zero Trust Access.

## Run locally / in a Snowflake workspace
```bash
pip install -r requirements.txt
python -m engine.build                   # writes index.html; publishes too if CF_* are set
python -m engine.backtest                # accuracy of the demand projection (appends logs/experiments.csv)
```
Inside a Snowflake workspace the connection uses the session OAuth token, so no key is needed. That sandbox can't reach Hugging Face or the Shopify CDN, so real image embeddings run only in GitHub Actions or locally. `TW_FAKE_EMBED=1` builds with attribute-hash vectors for **pipeline testing only**: the page shows a red "TEST BUILD" banner and `build` refuses to publish it.

Dev shortcuts: `TW_DEV_DATA=.cache/dev/data.pkl` pickles and reuses the Snowflake pull; `TW_EMBED_LIMIT=200` embeds at most 200 new images per run.

## Troubleshooting
| Symptom | Fix |
|---|---|
| preflight lists errors | Fix every secret it names, then **Re-run all jobs** |
| `JWT token is invalid` | Public key not set on the user: `ALTER USER <u> SET RSA_PUBLIC_KEY='...'` |
| `KV publish failed (403/404)` | Token lacks *Workers KV Storage: Edit*, or wrong account / namespace id |
| Refresh job slow every day | The `embeddings-cache` release is missing or was deleted; the next run rebuilds it |
| Many `image fetch failures` | Shopify CDN throttling; the next run retries the missing SKUs automatically |
| Site says "not published yet" | Worker is up but the data job hasn't run yet; run the workflow |

## Saved allocations and store rules
"Save allocation" stores a finalised allocation for 35 days (Worker + KV). The **Saved allocations** tab lists them
(search, re-download, delete) and analyses actual sales since the allocation date against the engine's projection for the
same days (updated with every refresh). A remark on a line becomes a **store rule** (e.g. "Half Sleeve doesn't work here")
that every later allocation follows. The build mirrors both into `SNITCH_DB.MAPLEMONK.TW_ALLOC_LOG` / `TW_ALLOC_RULES`;
the CI Snowflake role needs CREATE TABLE on MAPLEMONK for that (otherwise it still works, without the tables).
