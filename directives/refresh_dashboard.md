# Directive: Refresh / change the dashboard

**Normal refresh:** automatic every day at 10:00 IST (Worker cron → GitHub Actions). For an on-demand refresh: Actions → TopWear refresh → Run workflow (tick `refresh_only`).

**Change logic or thresholds:**
1. Constants (exclusions, scope, NEW/nudge/fresh days, similarity, demand, default weights, fill ceiling) all live in `engine/config.py`.
2. Data: edit the relevant `engine/sql/<dataset>.sql`, and use `{PLACEHOLDERS}` from `config.SQL_PARAMS` for exclusions.
3. Scoring / allocation / UI: `web/template.html`. Weights are also editable live in the Allocation tab.
4. Test before pushing:
   ```bash
   TW_DEV_DATA=.cache/dev/data.pkl python -m engine.build      # first run pulls and pickles; then reuses the pickle
   node tests/smoke_dashboard.js index.html [SKU]               # needs: npm i jsdom
   ```
   In a Snowflake workspace add `TW_FAKE_EMBED=1 TW_CACHE_DIR=.cache/dev`, because images are unreachable there.
5. Pushing to `main` redeploys the Worker and refreshes the data.

**Add a category** (for example Overshirt): add it to `config.CATEGORIES`, extend the prefix regexes in `sql/size_sales.sql` and `sql/b2b.sql`, and add an ideal-mix branch in `sql/ideal_mix.sql` and `config.mix_key`. The first run then embeds the new images.

**Learnings log:**
- Snowflake NUMBER columns can arrive as `decimal.Decimal`; `build._numeric` converts them.
- The workspace stage mount doesn't support zip seeks, so `embeddings.save_cache` writes through an in-memory buffer.
- `pip install torch` from the PyTorch index is blocked in the workspace sandbox, and Hugging Face / the Shopify CDN return 403 there.
