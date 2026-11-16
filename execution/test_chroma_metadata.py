# execution/test_chroma_metadata.py
import chromadb

CHROMA_DB_PATH = "models/chroma_db"
COLLECTION_NAME = "sku_visual_embeddings"

client = chromadb.PersistentClient(path=CHROMA_DB_PATH)
collection = client.get_collection(name=COLLECTION_NAME)

print(f"Total items in collection: {collection.count()}")
results = collection.peek(limit=5)
print("\nSample metadata keys in Chroma:")
if results and "metadatas" in results and results["metadatas"]:
    for idx, meta in enumerate(results["metadatas"]):
        print(f"Sample {idx+1}: {list(meta.keys())}")
        print(f"  sku_id: {meta.get('sku_id')}")
        print(f"  category: {meta.get('category')}")
        print(f"  status_eligible: {meta.get('status_eligible')}")
        print(f"  fit_normalized: {meta.get('fit_normalized')}")
