# Directive: Clean & Encode Attributes

**Goal:** Clean SKU master data, flag SKUs with missing or low-quality tags using fill-rate reports, filter to SKUs with at least one successfully downloaded photo, and generate multi-hot encoded attribute vectors.

**Inputs:**
- `data/raw/sku_master.csv` (raw catalog data)
- `data/raw/attribute_fill_rates.csv` (data-quality fill rates)
- `data/raw/images/` (downloaded JPEG photos)

**Tools to use:**
- `execution/clean_attributes.py` — execution script

**Categorical columns to clean and encode:**
- `COLOR`
- `MATERIAL_NEW` (fabric)
- `FIT`
- `OCCASSION_NEW` (standardize double 's')
- `PRINT_DESIGN`
- `SLEEVE_TYPE`
- `COLLAR_NEW`
- `DESIGNS`
- `CLOSURE`
- `POCKET`
- `MAPPING_FINAL`
- `SKU_CLASS`
- `FABRIC_WEIGHT`
- `COMPOSITION`
- `STYLE`

**Steps:**
1. **Deduplicate SKU rows**: Remove any duplicate rows based on `ID`.
2. **Filter by photo existence**: Check the `data/raw/images/` directory. If a SKU `ID` has zero successfully downloaded photos (e.g., no `{ID}_1.jpg` through `{ID}_10.jpg` exist), remove it from the pipeline.
3. **Flag missing attributes (`HAS_MISSING_ATTRIBUTES`)**: 
   - Load `attribute_fill_rates.csv`.
   - Identify attributes that are unreliable/low fill-rate (or check if any of the target columns for the SKU contains nulls or empty strings).
   - Set a boolean column `HAS_MISSING_ATTRIBUTES` to `True` for any SKU containing missing values in our key attributes.
4. **Standardize values**:
   - Convert all string attributes to lowercase, strip trailing/leading whitespace, and replace duplicate spaces or dashes.
   - Standardize equivalent names (e.g., `half-sleeve` and `half sleeve` should resolve to `half_sleeve`).
5. **Multi-hot encode**:
   - Apply multi-hot encoding to the standard category/feature tags.
   - Key the resulting vectors table by `ID` (SKU ID) and save.
6. **Spot-check**: Print 5 random SKUs showing their original tags and their encoded vector format to verify correctness.

**Outputs:**
- `data/processed/sku_clean.csv` (cleaned and validated catalog table)
- `data/embeddings/attribute_vectors.csv` (multi-hot encoded representation, keyed by `ID`)

**Edge cases:**
- An attribute column contains only null values → do not encode it; drop it from the encoding set and print a warning.
- SKU has images in CSV but files are missing → the photo existence check must rely on actual disk file scans, not the CSV url values.

**Learnings log:**

