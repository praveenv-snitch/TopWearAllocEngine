# Directive: Add New SKU

**Goal:** Process and ingest a newly launched SKU into the similarity index.

**Steps:**
1. Embed ALL available photos of the new SKU (not just one).
2. Add each as a separate vector to the Chroma index.
3. Run find_similar_skus() once per new-SKU photo, then merge/average
   results across those queries before ranking candidate matches — avoids
   a lopsided comparison (multi-angle catalog vs. single-angle query)

**Outputs:** Updated Chroma index with the new SKU's photos.
