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

## Placement v2 (2026-11-20)
- **Store return rate** = customer returns made at stores only (STORE_RETURNS_FACT_ITEMS rows whose MARKETPLACE_MAPPED is a COCO/COFO/FOCO/FOFO/FICO store). The table is ~97% online / WH / marketplace returns, which the first version wrongly included.
- **Offline units** are labelled: lifetime (since Jul 2023), L30, L90.
- **Exclusions:** SKUs starting with MP are dropped everywhere. Stores without base stock or with an unmapped cluster are dropped (today: MAPLE MYSURU, PANIPAT).
- **NRC** (brand level) = cut at >= 1 store (store_replen_prepack cut rule incl. JIT) AND the WH (N+S) can build < 5 loose size sets (IST local_wh_cut rule). It flags ~5.8k SKUs because old tail SKUs with no WH stock count too.
- **Prepacks:** sendable packs per zone = min(PREPACKS_ALLOCATION_HELPER_V1 sets, live PP codes in LIVE_INV_WAREHOUSE_OFFLINE_REPLEN), depth with most sets (as store_replen_prepack.sql). PP codes are separate rows in the WH table, so WH_N / WH_S are loose units. Prepacks are allocated before loose.
- **Pack rules:**
  - Fresh: 2 prepacks max, or one loose set XS1 S2 M3 L3 XL2 XXL1. S-XL must be complete; plus = at least 3 of 3XL-6XL.
  - Replen: 1-2 whole prepacks, or only the loose sizes short of a full set / 30-day need.
  - Fresh sets and packs are never cut down to fit.
- **Basket allocator** (web/template.html `allocate`): greedy with lazy re-scoring. Gaps (meta, colour, price band, options, fill room) are held in units and consumed per line; the adjacent price band gets half credit.

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

## v3 (fresh-pool engine)
- **New datasets:** `engine/sql/fresh_pool.sql` (AV_MASTER_HTMBASE, store_avail.py logic: FULL_SIZE_OPTIONS, sizes after buffer, prepack sets per zone) and `engine/sql/pp_codes.sql` (prepack serial codes with UNITS_ON_HAND > 0, LIVE_INV_WAREHOUSE_OFFLINE_REPLEN).
- **stores.sql** joins STORE_CATEGORY_DELTA (size_category_meta_delta_offline). Store fill now = SUM(inventory) ÷ base. After JIT = (inv + JIT − ROS7d × lead time − outward) ÷ base. After IST = (inv + JIT + IST in − ROS7d × lead time − outward − IST given) ÷ base. It also joins FACT_PARETO_TARGET_PERFORMANCE_SUMMARY (store wise, current month) for the category target and % achieved.
- **Fresh run (Allocation tab):**
  - Uses the whole fresh pool, for filtered stores, one store, or clusters.
  - Auto budget = 110% × base − net stock after JIT + IST (store level). It is split between Shirts and T-shirts by category gap, and each category is capped at 110% of its category base.
  - Manual mode: you set the units per store and choose Both or one category.
- **Pack rules:**
  - Fresh = exactly 2 coded prepacks, else one loose set (it uses a FULL_SIZE_OPTION).
  - Replen = per-size need, max 6 a size; prepacks follow the store_replen_prepack rule. The `replen_need` weight favours size-broken and under-30-day-cover styles.
  - Every prepack line lists its serial codes, and each code is used once.
- **UI:**
  - Store detail shows only for exactly one store, with a category toggle and a meta benchmark toggle (Ideal / Sales share). Deviation and ideal options per meta combination sit in a collapsed section.
  - Mini-tables have headers. Price and age filters recompute the health table, and there is a Reset button.
  - Nudges get status chips with a legend, a category toggle, and cascading alert filters; clicking an alert opens store health.

## v4
- **Sales shares:** every sales-share benchmark (metafield, colour, price band, sleeve, size curve) is weighted 50% L30 + 30% L15 + 20% L7 (`health.wshare`).
- **Price basis toggle (Store Health):** MRP or ASP, where ASP = 90-day offline revenue ÷ units, falling back to selling price. It drives the bands, the price filter and the allocation price gap.
- **New gap weights:** sleeve gap, size gap closed and cluster sellability. Cluster sellability = the cluster's average projected ROS per store ÷ the best cluster's, so a cluster doesn't rank higher just for having more stores. The 12 fresh weights add up to 1. New columns after Price gap.
- **Fresh run:**
  - "Exhaust stock" sends the remaining WH stock after the budget pass.
  - Two held-back cases, each with Force: no category delta (`noCatDelta`), and category delta but no fresh room (`noRoom`, force = send the delta only).
  - One-store search.
- **SKU tab search:** a full SKU opens similarity; a style code opens the colour-family grid (select / add all); a prepack code opens its SKU, and the pack can go into the basket, where its code is used first.
- **Insights:** best-selling clusters = L30 units per store carrying a similar SKU, with units per cluster store shown alongside.
- **Schedule:** every 2 hours 10:00-18:00 IST (cron `30 4-12/2 * * *` UTC, 5 runs a day). The 10:00 run comes before AV_MASTER_HTMBASE (~10:15 IST) and SKU_LIVE_MECH_V2 (~11:40 IST) refresh, so new inwards show from the 12:00 run. GitHub backup runs outside 10:00-18:30 IST skip themselves.

## v5
- **Cluster names** are merged case-insensitively in `build.py` (the sources mixed "HARYANA" and "Haryana", "PUNJAB" and "Punjab").
- **Cluster priority** = projected ROS per store over all stores of the cluster, shrunk towards the network average with 3 pseudo-stores (`CLUS_K`). One-store clusters (West Bengal, Odisha, Assam…) often still lead because those stores really do sell the most per store (also on actual similar-SKU sales). The insight table shows actual and projected side by side.
- **SKU tab:**
  - NRC and PREPACK badges are stacked on the cards.
  - Back works for SKU, style and prepack searches (`navTo` / `CURQ`).
  - A style search opens the SKU-page layout with a family grid, "Add family to allocation" and "Add selected to allocation". With an empty basket, the family is what gets allocated.
  - SKU pages have a "colours" KPI.
- **Store Health:** a chart legend at the top, and the MRP/ASP toggle on the price-band graph (it drives the allocation price gaps).
- **Allocation tables:** a Meta column (and CSV META), and the SKU image appears when you hover over the SKU code.
- **Fresh run:** cluster scope uses search chips.
- Small-cluster cap: clusters with fewer than CLUS_MIN (3) stores are capped at the median cluster score in clusterRank (marked "capped" in the cluster table).
- Branding: build embeds web/assets/ (or web/assests/) favicon.* as the tab icon and snitch_logo.* as the header logo; the logo is auto-cropped to the wordmark and scaled to header height.

## Saved allocations, performance, store rules (v7)
- **Save**: "Save allocation" next to every Download (fresh run, Where to allocate). Name `DD-MM-YY_POC_branchcodes_qty`
  (POC in caps, MULTI if several; more than 8 stores -> first 8 codes + `+N`). Stored by the Worker in KV as `alloc:<id>`
  `{meta, cfg, lines, csv}`; `csv` is the exact downloaded file, so a re-download is byte-identical. KV expiry = 35 days.
- **Worker API** (`worker/src/index.js`, same password as the site): `GET/POST /api/allocs`, `GET/DELETE /api/allocs/<id>`,
  `GET/POST /api/rules`, `DELETE /api/rules/<id>`. Rules live in the KV key metadata (`rule:<id>`), optional expiry 30 / 90 days.
- **Build** (`engine/alloc_log.py`): reads KV (Cloudflare API), mirrors into `SNITCH_DB.MAPLEMONK.TW_ALLOC_LOG` /
  `TW_ALLOC_RULES` (full replace each run, so the 35-day purge follows KV; falls back to an inline list if the CI role
  cannot create / write tables), runs `engine/sql/alloc_perf.sql` (daily offline sales per saved store x SKU from the
  allocation date to yesterday IST, same exclusions as the engine) -> `D.perf {asOf, a:{id:[[bc,sku,dayOff,units,rev]]}}`
  and `D.rules` (fallback when the live API is unreachable). Dev: `TW_ALLOCS_FILE=<json>` and `TW_NO_LOG_TABLES=1`.
- **Analysis**: projected for the same period = line ROS x days since allocation (capped at stock sent + stock before);
  KPIs, cumulative actual vs projected chart, by store / SKU / evidence tier, below-projection (14+ days, < 50%) and
  beating-projection (> 150%) lists. Replen sales include stock the store already had; fresh sell-through is exact.
- **Remarks -> rules**: per line, a rule type (don't send SKU / design / metafield / colour / sleeve / fit / collar /
  material / MRP band, send less, note) with free text that pre-selects the type. Rules are per store (+ category);
  the allocator skips matching lines (`out.ruleSkips`, family colours too) and "send less" halves replen lines
  (prepacks: half the packs, min 1) and halves the score of fresh lines. Shown in the allocation summaries, the Store
  Health header chip and the Store rules list. Tests: `tests/smoke_saved.js`.
