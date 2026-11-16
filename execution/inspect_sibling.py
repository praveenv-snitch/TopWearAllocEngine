# execution/inspect_sibling.py
import pandas as pd

CLEAN_SKU_PATH = "data/processed/sku_clean.csv"
df = pd.read_csv(CLEAN_SKU_PATH)

target_sku = "4MST2439-02"
sibling_sku = "4MST2439-05"

row_target = df[df["SKU_GROUP"] == target_sku]
row_sibling = df[df["SKU_GROUP"] == sibling_sku]

print("Target SKU:")
print(row_target[["SKU_GROUP", "PRODUCT_NAME", "COLLAR_NEW", "FIT_NORMALIZED", "MATERIAL_NEW", "STATUS", "FINAL_LIVE_DATE"]])

print("\nSibling SKU:")
print(row_sibling[["SKU_GROUP", "PRODUCT_NAME", "COLLAR_NEW", "FIT_NORMALIZED", "MATERIAL_NEW", "STATUS", "FINAL_LIVE_DATE"]])
