# PROJECT CONTEXT — Visual SKU Allocation System ("Snitch" project)

**Purpose of this file:** full context handoff so a new Claude session can continue
this project with no re-explaining needed. Read this in full before responding
to any new message in this project.

---

## 1. Who I'm working with

Kanishk — self-describes as a "vibe coder," beginner-to-intermediate in Python/ML,
comfortable with the concept of coding but needs steps spelled out. Works in
Google Antigravity (a VS Code-based agentic IDE) on a MacBook Air M1, 8GB RAM.
Project folder: `/Users/kanishk/Snitch-Image Search model/`.

Communication style that works well: concrete step-by-step instructions,
copy-pasteable commands, plain-language explanations of jargon before using it,
honest pushback when an idea has a real flaw (he responds well to this and
often refines his own thinking further in response — treat him as a capable
collaborator, not someone to just agree with).

---

## 2. What this project actually is

A local visual-similarity + attribute-based demand estimation system for a
menswear brand's merchandising team. Goal: given a SKU (e.g. a red striped
polo), decide which of 100+ physical stores should receive it and in what
quantity — including for brand-new SKUs with zero sales history anywhere
(the "cold start" problem).

**Two separate systems, deliberately decoupled:**
1. This project (image search + attribute similarity) → produces a demand
   estimate per store.
2. An **already-existing, separate** two-pass allocation loop (built prior to
   this project, not something we're building) → takes that demand estimate
   and produces final unit-level allocation, handling cut-size/pack constraints.
   We only need to feed it a clean `sku_id, store_id, estimated_demand` table
   — never touch its internal logic.

---

## 3. Core architecture (v1 scope)

```
Snowflake (3 tables) → Clean & encode attributes → Generate visual embeddings
→ Vector store (Chroma) → Filter (attributes) + rank (visual similarity)
→ Recency-weighted demand estimate per store → Hand off to existing
allocation loop → Merchandiser review/override (logged) → Backtest (MAPE)
→ Versioned via git
```

**v1 explicitly excludes** (deferred to v2, by design, not oversight):
- LightGBM as a learned signal combiner (v1 uses a hand-tuned rule-based
  formula instead: filter by category/price tier → rank by visual similarity
  → weight by recency decay). v1's output becomes v2's training data.
- Qdrant (v1 uses Chroma; swap later, same interface)
- Scheduled/live Snowflake refresh (v1 is a manual one-time snapshot pull)
- Photo angle classification/fine-tuning
- Shirts and other categories (v1 is T-shirts only)

---

## 4. All key decisions made, with reasoning (do not re-litigate without new info)

- **Embedding model: Marqo-FashionSigLIP.** Free, open-source, best-benchmarked
  fashion-specific embedding model available (beat generic CLIP and DINOv2/v3
  on fashion retrieval benchmarks). Confirmed input resolution: **224×224**
  (verify locally via `preprocess.transforms` before first production run).
  768-dimensional output embedding.
- **Vector store: Chroma for v1**, Qdrant planned once production-scale
  (Qdrant's strong metadata filtering will matter more at that stage).
- **Multi-vector-per-SKU embedding, NOT one-photo-per-SKU.** The catalog has
  ~10 image slots per SKU (`IMAGE_1`-`IMAGE_10`) with **no standardized
  angle-to-slot mapping** — e.g. `image_link_1` is the front shot for most
  SKUs but the back shot for back-print-only tees. Rather than trying to
  classify/select angles (fragile, guaranteed to break on edge cases), every
  available photo is embedded as its own separate vector tagged with `sku_id`.
  Retrieval finds the nearest *photo* (any angle, any SKU) and collapses to
  the parent SKU. New SKUs being scored are also embedded on ALL their photos,
  not just one, and results are merged/averaged — avoids a lopsided
  single-angle-query vs. multi-angle-catalog comparison.
  - Known tradeoff: SKUs with more surviving photos (post-dedup) get more
    "chances" at a close match, independent of true similarity. Mitigated by
    ranking on **average distance across matched photos**, not single-best-photo
    distance. Revisit if backtest results show a correlation between photo
    count and match frequency.
  - Backtesting implication: leave-one-out exclusion must remove ALL of a
    tested SKU's photo vectors, not just one ID.
- **Pre-embedding photo filtering:** only exclude genuine non-product images
  (size charts, promotional banners/logos with text). **Do NOT exclude
  lifestyle photos** — they contain the real garment (sometimes the only
  source for certain angles) and are not equivalent to true noise. Both
  "product" and "lifestyle" labels are kept in the CLIP zero-shot filter.
- **Photo storage:** resize to 224×224 (matching the model's actual input
  size — NOT 384×384, an earlier unverified assumption that was corrected),
  JPEG quality=90 (not aggressive compression — negligible embedding-quality
  impact at this setting, most of the storage win comes from resizing anyway).
- **Demand signal: Rate of Sale (ROS), not raw units**, computed per store,
  per matched SKU, over 7/15/30-day windows where enough data exists. Avoids
  bias toward SKUs that have simply been live longer.
- **Price is NOT embedded into the visual/attribute vector.** It's a
  confounder (two visually-similar SKUs at different price points serve
  different segments) — used instead as a hard filter/bucket (price tier),
  applied at the Section 4/5 filtering stage, not baked into the embedding.
- **Date/recency is NOT embedded either**, for a different reason (embeddings
  should represent durable properties; ROS/recency are time-varying). Instead:
  seasonal/occasion tags are used as a hard filter, and a recency-decay
  weight (`similarity × e^(−months_since_launch/decay_constant)`, starting
  decay_constant≈12) discounts older comparables in the Section 5 demand
  calculation.
- **Store tiering basis: `CATEGORY_BASE_STOCK`, explicitly NOT square footage
  or overall `BASE_STOCK`.** Category-specific base stock is the accurate
  signal for a category-scoped allocation decision.
- **Store target rank (if/when added): a POST-estimate adjustment layer**,
  applied after Section 5's data-driven demand estimate, never blended into
  the same calculation. Keeps data-driven and strategic/business-judgment
  signals separately auditable, and avoids circularity (if target rank was
  itself influenced by past allocation-driven sales).
- **Fill-rate columns** (`*_FILL_RATE`): pulled separately from `sku_master`,
  used in Section 2 to flag which attribute columns are reliable enough to
  encode and to set a `has_missing_attributes` flag per SKU. Never encoded
  into the attribute vector themselves (they describe the column, not the SKU).
- **Attribute hierarchy for filtering/encoding** (from `image_search_master`
  schema, most recent refinement):
  - **Tier 0 (hard filter, already fixed):** `CATEGORY`, `L1_CATEGORY` = T-Shirts
  - **Tier 1 (hard filter, ONE at a time only):** `FIT` / `SLEEVE_TYPE` / `STYLE`
    — pick the single most demand-relevant one as hard filter (likely `FIT`);
    treat the others as soft signals. Stacking 2+ of these as simultaneous
    hard filters risks shrinking buckets below a usable pool size.
  - **Tier 2 (soft filter / score boost, not exclusion):** `COLLAR_NEW`,
    `CLOSURE`, `POCKET`
  - **Tier 3 (attribute vector input, no filtering):** `MATERIAL_NEW`,
    `FABRIC_WEIGHT`, `COMPOSITION`
  - **Tier 4 (left to visual embedding, NOT hard-filtered):** `PRINT_DESIGN`,
    `DESIGNS`, `COLOR`, `OCCASSION_NEW` — this is the "can't standardize this
    into tags" layer that's the whole reason the visual model exists.
    Exception: `COLOR` also gets a soft filter/boost as backup, since it's
    usually the single biggest demand driver and photo lighting can make the
    embedding's color read less reliable than a human tag.
  - **Practical guardrail:** after applying a Tier-1 hard filter, check the
    resulting bucket sizes (`sku_df.groupby("FIT").size()`); any bucket under
    roughly 150-200 SKUs is too thin to trust, reconsider that filter.
  - **Never hard-filter on a column with a low fill rate** (check
    `*_FILL_RATE` first — anything below ~85-90% complete defaults to Tier 2
    soft treatment regardless of the tier assigned above).
- **v1 pilot scope — intentional asymmetry:**
  - Store/output side: Kerala cluster ONLY (2 stores) — scoped down.
  - SKU/comparison pool side: full T-shirt category (~3,500 SKUs) — NOT
    scoped down to only what Kerala has historically sold. Restricting the
    comparison pool by geography would bias matches toward "what Kerala
    already got," missing genuinely-better matches from elsewhere, and would
    reinforce a monoculture feedback loop over time.
- **Backtesting requires leave-one-out**: the SKU under test must be excluded
  from its own comparison pool before searching (all its photo vectors, per
  the multi-vector note above), or the model trivially matches itself and
  produces a falsely perfect result. Any backtest run without confirmed
  exclusion should be treated as invalid.
- **Success metric:** MAPE vs. a naive baseline (category-average sell-through),
  computed across at least 20-30 held-out SKUs. If the model doesn't beat the
  naive baseline, that's a valid, useful result to report plainly — not a
  failure to hide.

---

## 5. Confirmed Snowflake tables (already built)

- SKU master: `snitch_db.maplemonk.image_search_master`
- Sales history: `snitch_db.maplemonk.image_search_sales_history`
- Store master: `SNITCH_DB.MAPLEMONK.IMAGE_SEARCH_STORE_MASTER` (already
  created via `CREATE TABLE ... AS SELECT` from `STORE_CATEGORY_DELTA`,
  including essential + explicitly-requested-back excluded columns)

**Known schema quirks / open questions, unresolved:**
- `PRINT_DESIGN` and `DESIGNS` both exist in `image_search_master` — likely
  duplicates, not yet confirmed with data team which is canonical.
- `MATERIAL_NEW` vs. a possible `MATERIAL_MAPPED` — not yet confirmed which
  is the canonical cleaned field.
- `image_search_sales_history` has **no visible returns/units-returned
  column** (only `SUBORDER_QUANTITY`) — need to confirm with data team
  whether returns appear as negative quantities in this same table, or
  aren't captured at all. This affects the ROS calculation's accuracy.
- Exact `BRANCH_CODE` values for Kerala's 2 stores — not yet identified/
  confirmed, needed before running the scoped extraction query.
- `CATEGORY` column exists in both `sku_master` and `store_master` — possible
  name collision, meaning not yet confirmed to be equivalent between tables.
- `image_search_master` has 10 image slots (`IMAGE_1`-`IMAGE_10`), more than
  the 5-7 originally assumed — directives updated accordingly.
- `FABRIC_WEIGHT` and `COMPOSITION` are new columns not part of earlier
  discussion — potentially useful for Tier 3 attribute encoding, pending
  fill-rate confirmation.
- Fill-rate check not yet run on `FIT`, `SLEEVE_TYPE`, `COLLAR_NEW`, etc. to
  confirm which are reliable enough for hard/soft filtering — a SQL query
  for this was in progress as of the last message in this thread (see
  Section 8, "Immediate next step").

---

## 6. Agent operating framework (already in place in the project folder)

Kanishk has his own established 3-layer framework (mirrored across
`AGENTS.md`/`CLAUDE.md`/`GEMINI.md`), which supersedes any earlier
Claude-suggested "skills" structure — do not reintroduce a separate
`.agents/skills/` system, it's redundant with this:

- **Layer 1 — Directive** (`directives/*.md`): SOPs in plain markdown — goals,
  inputs, tools/scripts, outputs, edge cases.
- **Layer 2 — Orchestration**: the agent itself — reads directives, calls
  execution scripts in order, handles errors, asks for clarification, updates
  directives with learnings.
- **Layer 3 — Execution** (`execution/*.py`): deterministic, tested Python
  scripts. Secrets in `.env`.
- **Self-annealing loop**: fix → update the tool → test → update the
  directive → system is stronger. Directives are living documents, but never
  created/overwritten without asking, unless explicitly told to.
- **Token-minimization additions layered on top** (from a separate source
  Kanishk shared, cross-checked and partially adopted — the "symbolic graph
  tuples" idea from that source was explicitly rejected as unverified/vague):
  - `CONTEXT.md` at project root — persistent project-state "brain," read
    FIRST every session (added as Operating Principle 0 in `AGENTS.md`).
  - Session cap ~2 hours; at natural breakpoints, update `CONTEXT.md` and
    start a fresh conversation rather than letting one session run long.
  - Directives (already Layer 1 above) serve as the "zero-token local skills"
    equivalent — no separate workflows folder needed.

**Current file structure in the project root** (confirmed via screenshot):
```
Snitch-Image Search model/
├── config/
├── data/
├── directives/
│   ├── extract_snowflake_data.md
│   ├── generate_visual_embeddings.md
│   ├── run_backtest.md
│   └── add_new_sku.md
├── execution/        (empty so far — Section 1 code not yet written)
├── logs/
├── models/
├── notebooks/
├── src/
├── venv/
├── docs/
│   └── project-architecture-buildplan.md
├── .gitignore        (fixed — now includes .env, credentials.json,
│                       token.json, .tmp/, alongside original
│                       venv/, data/raw/, data/processed/, models/, *.pyc,
│                       __pycache__/)
├── .env.example
├── .env               (correctly gitignored, holds real Snowflake creds,
│                       confirmed via `git check-ignore -v .env`)
├── AGENTS.md          (his original 3-layer framework + added Operating
│                       Principle 0: read CONTEXT.md first every session)
└── CONTEXT.md
```

Git is initialized, first commits made, `.gitignore` issue (was missing
`.env` initially, causing it to show as untracked) has been fixed and
confirmed resolved.

---

## 7. Environment / tooling facts established

- **IDE:** Google Antigravity (VS Code fork with agentic layer) — sufficient
  on its own, no separate VS Code install needed.
- **Hardware:** M1 Air, 8GB RAM — sufficient for v1 (embedding generation via
  pretrained model, batched 50-100 images at a time; no local fine-tuning).
  Colab only needed later if fine-tuning becomes necessary or catalog scope
  grows much larger.
- **Python environment:** `venv`, activated once per session
  (`source venv/bin/activate`), packages installed once (persist on disk,
  no need to reinstall each session).
- **Git:** identity not yet configured globally (was using auto-detected
  username/hostname) — worth setting via `git config --global user.name/
  user.email` at his convenience, not urgent for solo local work.
- **Not yet pushed to GitHub** — all work so far is local-only commits.

---

## 8. Immediate next step (as of end of this thread)

Kanishk was asking for a Snowflake SQL query to compute the **fill rate
percentage of every column** in `image_search_master`, to decide which
attribute columns are reliable enough for the Tier 1/2 hard/soft filtering
scheme above, before proceeding into Section 2 (attribute cleaning/encoding).
This query had not yet been delivered when this context file was requested —
**this is the correct next action to pick up with.**

Approach to use: since Snowflake doesn't run column-wise aggregate loops
natively, either (a) generate the query dynamically via
`INFORMATION_SCHEMA.COLUMNS` + `LISTAGG` producing a `UNION ALL` string to
copy-paste and re-run, or (b) write the explicit long-form query by hand
listing every real attribute column with
`COUNT(col)*100.0/COUNT(*) AS fill_rate_pct`. Note: `image_search_master`
already contains some precomputed `*_FILL_RATE` columns from an earlier
pipeline stage, but these appear to be per-row completeness scores (small
integers), not the whole-table percentage Kanishk is asking for now — worth
clarifying this distinction when resuming.

After the fill-rate check: finalize which Tier 1/2 columns get hard vs. soft
filter treatment, then proceed to Section 1 (Snowflake extraction, scoped to
Kerala output + full T-shirt catalog) and Section 2 (attribute cleaning).

---

## 9. Working style notes for whoever picks this up

- Give copy-pasteable commands/code, not abstract descriptions, given
  Kanishk's stated beginner level.
- Explain jargon in plain language the first time it's used in a session.
- Push back genuinely when something in his plan has a real flaw (the
  ROI/price/date embedding question, the store-scope-vs-catalog-scope
  question, and the photo angle-selection problem are all examples where
  he initially proposed something with a real issue, engaged well with the
  pushback, and the resulting decision was better for it).
- Update `directives/*.md` and `CONTEXT.md` text explicitly whenever a new
  decision is made in conversation — he's been manually copying these
  updates into his actual files after each exchange, so give him ready-to-
  paste text, not just verbal confirmation of the decision.
- He is deliberately building this as a durable v1 foundation for v2, not
  throwaway prototype code — decisions should account for that even when
  scoped down for v1 (e.g., LightGBM deferred but v1 designed to produce its
  training data; Chroma now but Qdrant-compatible interface later).
