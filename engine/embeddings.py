"""Image embeddings (Marqo-FashionSigLIP) with an incremental cache.

Cache = .cache/embeddings.npz {skus, urls, vecs(float16, L2-normalised)}. A SKU is (re-)embedded only when it is new
or its image URL changed, so a daily run embeds a few dozen images instead of ~18k. In GitHub Actions the cache is
kept as a release asset (see .github/workflows/refresh.yml).

TW_FAKE_EMBED=1 -> deterministic attribute-hash vectors instead of images. For pipeline testing ONLY where
Hugging Face / the Shopify CDN are unreachable; never use it for a published dashboard.
"""
import hashlib
import io
import os
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from engine import config as C

MODEL_NAME = "hf-hub:Marqo/marqo-fashionSigLIP"
FAKE = os.environ.get("TW_FAKE_EMBED") == "1"
CACHE_FILE = os.path.join(C.CACHE_DIR, "embeddings_fake.npz" if FAKE else "embeddings.npz")
BATCH = 32


def load_cache():
    if not os.path.exists(CACHE_FILE):
        return {}
    z = np.load(CACHE_FILE, allow_pickle=False)
    return {s: (u, v) for s, u, v in zip(z["skus"], z["urls"], z["vecs"])}


def save_cache(cache):
    os.makedirs(C.CACHE_DIR, exist_ok=True)
    skus = sorted(cache)
    buf = io.BytesIO()          # build in memory: stage mounts don't support the seeks zipfile needs
    np.savez_compressed(buf, skus=np.array(skus), urls=np.array([cache[s][0] for s in skus]),
                        vecs=np.stack([cache[s][1] for s in skus]).astype(np.float16))
    with open(CACHE_FILE, "wb") as f:
        f.write(buf.getvalue())


def _fetch(url):
    import requests
    from PIL import Image
    try:
        # Shopify CDN resizes on the fly: ask for a small JPEG instead of the multi-MB original
        u = url + ("&" if "?" in url else "?") + "width=384"
        r = requests.get(u, timeout=20)
        r.raise_for_status()
        return Image.open(io.BytesIO(r.content)).convert("RGB")
    except Exception:
        return None


def _fake_vec(text, dim=256):
    v = np.zeros(dim, np.float32)
    for tok in text.lower().split("|"):
        h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
        v[h % dim] += 1.0
    return v / (np.linalg.norm(v) or 1)


def embed(products):
    """products: DataFrame with SKU, IMAGE_URL (+ attributes for fake mode) -> (sku list, float32 matrix)."""
    cache = load_cache()
    fake = FAKE
    want = {r.SKU: C.txt(r.IMAGE_URL) for r in products.itertuples()}
    todo = [s for s, u in want.items() if u and (s not in cache or cache[s][0] != u)]
    if C.EMBED_LIMIT:
        todo = todo[:C.EMBED_LIMIT]
    print("  embeddings: %d cached, %d to embed%s" % (len(cache), len(todo), " (FAKE attribute vectors)" if fake else ""))

    if todo and fake:
        attrs = products.set_index("SKU")
        for s in todo:
            r = attrs.loc[s]
            txt = "|".join(str(r[c]) for c in ["COLLAR_NEW", "DESIGNS", "PRINT_DESIGN", "COLOR", "FIT", "STYLE",
                                               "SLEEVE_TYPE", "MATERIAL_NEW"])
            cache[s] = (want[s], _fake_vec(txt))
    elif todo:
        import open_clip
        import torch
        torch.set_num_threads(os.cpu_count() or 2)
        model, _, preprocess = open_clip.create_model_and_transforms(MODEL_NAME)
        model.eval()
        failed = 0
        with ThreadPoolExecutor(16) as pool:
            for i in range(0, len(todo), BATCH):
                chunk = todo[i:i + BATCH]
                imgs = list(pool.map(_fetch, [want[s] for s in chunk]))
                ok = [(s, im) for s, im in zip(chunk, imgs) if im is not None]
                failed += len(chunk) - len(ok)
                if not ok:
                    continue
                with torch.no_grad():
                    f = model.encode_image(torch.stack([preprocess(im) for _, im in ok]))
                    f = f / f.norm(dim=-1, keepdim=True)
                for (s, _), v in zip(ok, f.numpy()):
                    cache[s] = (want[s], v.astype(np.float32))
                if (i // BATCH) % 20 == 0:
                    print("    %d/%d embedded" % (min(i + BATCH, len(todo)), len(todo)), flush=True)
                if (i // BATCH) % 100 == 99:
                    save_cache(cache)          # checkpoint: a cancelled first run keeps its progress
        print("  image fetch failures: %d" % failed)
    if todo:
        save_cache(cache)

    skus = [s for s in want if s in cache]
    vecs = np.stack([cache[s][1] for s in skus]).astype(np.float32) if skus else np.zeros((0, 1), np.float32)
    vecs /= np.linalg.norm(vecs, axis=1, keepdims=True).clip(1e-6)
    return skus, vecs
