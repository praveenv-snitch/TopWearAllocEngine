# CONTEXT.md: project state (read first, every session)

**Last updated:** 2026-11-19

## What this project is
A daily-refreshed dashboard for Shirts + T-shirts offline allocation. Similar SKUs are found by image similarity plus attributes, and their store sales project demand for any SKU, including new and draft ones. Store health covers mix, colour, price, size, cut and freshness. A WH-constrained allocation run and new-inward nudges complete it. Hosting follows the IST engine: GitHub Actions → `index.html` → Workers KV → Worker. See README.md.

## Where we are
- **v2 restructure done (2026-11-19).** The terminal-only v1 (local Chroma, Kerala pilot, `IMAGE_SEARCH_*` snapshot tables) is replaced by `engine/` on live tables. v1 files are archived in `.cache/v1_backup.tar.gz` (not in git).
- **Built and tested in the Snowflake workspace with FAKE embeddings only.** That sandbox can't reach Hugging Face / the Shopify CDN. All six SQL datasets, similarity, demand, health, payload and all three dashboard tabs ran end-to-end (headless smoke test: 0 JS errors; the full allocation run takes about 6 s in the browser).
- **Next steps:**
  1. Push to GitHub, add the secrets, and run the workflow once. This is the first real image-embedding run.
  2. Re-run with the `backtest` option and record the result below.
  3. Agree the download format with the allocation team.

## Decisions (don't re-litigate without a reason)
- **Scope:** SHIRTS + T-SHIRTS. Category = METAFIELDS_DATA category synonyms, otherwise the SKU-prefix table in `engine/config.py`. Exclusions are as given in the DB brain (branches, WH/marketplace names, OMS/QCOM, CB/NT/N0/hangers/uniform, NON-TRADING).
- **Source tables:** live tables only. `IMAGE_SEARCH_*` are stale snapshots (last updated Jul–Sep 2026); only `FABRIC_WEIGHT` / `COMPOSITION` are still read from `IMAGE_SEARCH_MASTER`, as an optional soft attribute. `OFFLINE_METAFIELD_STR` is stale (Feb 2026), so STR comes from `OFFLINE_MASTER` + `OFFLINE_MASTER_DAILY_REPORT_1`.
- **Similarity:** `docs/similarity_logic.md` (FINAL tiered cascade). It uses one image per SKU (`BASE_PRODUCT.IMAGE_URL`). Multi-image embedding is a later option and is not needed for v2.
- **NEW / RECENT / OLD:** never sold offline / first offline sale ≤ 30 d / otherwise.
- **Demand projection (backtest-tuned):** log-index blend. A neighbour's ROS ÷ the store baseline is averaged, weighted by similarity × recency × store-history length, using only neighbour store rows with ≥ 30 days live. It is shrunk (k = 3) toward the neighbours' overall index. Old SKUs blend in their own store history.
- **Ideal options** = base stock × ideal category mix ÷ DEPT_IDEAL. **DOI cap** is 60 d in KA/DL/HR and 90 d elsewhere (as in the longtail SQL).
- **Fill ceiling default is 140%**, because network median fill against base stock × category mix is already about 130%. Revisit with the merch team: either the base stock values or the ceiling are off.
- **Colour benchmark** = cluster 90-day sales share, because GS ideal-mix COLOUR / MATERIAL columns are empty. **Price benchmark** = the store's own 90-day sales share by MRP band.
- **Warehouse:** a store's zone (NORTH/SOUTH) picks the preferred WH from `AVAILABILITY_MASTER_V2_MERGED`; the other zone is the fallback. WEST / unmapped stores use whichever WH has more stock.

## Known issues / open questions
- [ ] The download format for the allocation CSV is to be defined; the current columns are a placeholder.
- [ ] Fill > 100% almost everywhere: confirm whether GS_SHEET3 BASE_STOCK is current.
- [ ] TARGET_MTD for yesterday is often missing, so it falls back to monthly target × elapsed share of the month.
- [ ] NORTH_RULE_MERCH / FINAL_SOUTHRULEBOOK are logistics rules (lanes, TAT, box capacity), not size rules, so they aren't used yet. Use them for dispatch-day / box-capacity caps if wanted.

## Backtest results
| date | embedding | WAPE | naive WAPE | Spearman | SKUs | note |
|---|---|---|---|---|---|---|
| 2026-11-19 | FAKE (attribute hash) | 0.616 | 0.633 | 0.324 | 400 | pipeline check only, not a model result |

## Session end checklist
1. Update "Where we are" above.
2. Update directives with new learnings.
3. Commit with a clear message.
