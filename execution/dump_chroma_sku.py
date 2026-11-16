# execution/dump_chroma_sku.py
import chromadb
import json

CHROMA_DB_PATH = "models/chroma_db"
COLLECTION_NAME = "sku_visual_embeddings"

try:
    client = chromadb.PersistentClient(path=CHROMA_DB_PATH)
    collection = client.get_collection(name=COLLECTION_NAME)
    print(f"Connected to Chroma DB. Total items: {collection.count()}")
    
    # Check both casings
    results = collection.get(
        where={"sku_group": "4MST2242-02"},
        limit=2
    )
    if not (results and "metadatas" in results and results["metadatas"]):
        results = collection.get(
            where={"sku_group": "4mst2242-02"},
            limit=2
        )
    
    print("\n--- Chroma Metadata Dump ---")
    if results and "metadatas" in results and results["metadatas"]:
        print(json.dumps(results["metadatas"][0], indent=2))
    else:
        print("SKU 4MST2242-02 not found in Chroma!")
        fallback = collection.peek(limit=3)
        if fallback and "metadatas" in fallback and fallback["metadatas"]:
            print("\nSample metadata from DB instead:")
            print(json.dumps(fallback["metadatas"][0], indent=2))
except Exception as e:
    print(f"Error querying Chroma: {e}")
