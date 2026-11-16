# Visual SKU Allocation System (v1)

This repository implements an attribute-based and visual-similarity-based demand estimation system to feed into the store allocation loop. 

## Success Metrics

- **Primary Metric**: Forecast Accuracy (Mean Absolute Percentage Error - MAPE) between predicted store-level demand and actual sell-through for a held-out set of past SKUs.
- **Business Metrics**:
  - Stockout Rate (how often a store sells out of a SKU).
  - Markdown Rate (amount of inventory that has to be discounted).
- **Adoption Metric**: Overrides frequency and reasoning by merchandisers.

## Project Structure

```
├── config/
│   └── settings.yaml          # Constants (weights, decay_constant, thresholds)
├── data/
│   ├── raw/                   # Raw exports from Snowflake
│   ├── processed/             # Cleaned tables ready for modeling
│   └── embeddings/            # Generated visual and attribute embeddings
├── execution/                 # Layer 3 Execution scripts (deterministic Python tools)
├── directives/                # Layer 1 Directives (SOPs in Markdown)
├── notebooks/                 # Exploratory work only
├── models/                    # Saved model files/embedding indexes
├── logs/                      # Run logs and experiment tracking
├── CONTEXT.md                 # Current project state (read first)
└── README.md                  # Project overview
```

## Scoped v1 Pilot Parameters

- **Category Scope**: T-shirts category only (~3,500 SKUs).
- **Geography Output Scope**: Kerala cluster (2 stores) for demand/sales outputs.
- **Backtesting Scope**: Leave-one-out backtesting (exclusion of target SKU from similarity matching).
- **Image Embeddings**: Multi-vector embedding (all ~5 angles per SKU embedded, nearest-neighbor collapses to parent SKU, cosine distance averaged across matched images).
