# execution/visual_embedding.py
# pyrefly: ignore [missing-import]
import open_clip
# pyrefly: ignore [missing-import]
import torch
# pyrefly: ignore [missing-import]
from PIL import Image

# Use CPU for local execution on M1 Air
DEVICE = "cpu"
MODEL_NAME = 'hf-hub:Marqo/marqo-fashionSigLIP'

print(f"Loading visual embedding model ({MODEL_NAME}) on {DEVICE}...")
try:
    model, _, preprocess = open_clip.create_model_and_transforms(MODEL_NAME)
    model = model.to(DEVICE)
    model.eval()
    print("Model loaded successfully.")
except Exception as e:
    print(f"Critical error loading model: {e}")
    model, preprocess = None, None

def embed_image(image_path: str):
    """Loads an image, preprocesses it, runs inference, and returns a normalized embedding vector."""
    if model is None or preprocess is None:
        print("Error: Model not initialized.")
        return None
        
    try:
        # Load and convert image to RGB
        img = Image.open(image_path).convert("RGB")
        # Apply preprocess and add batch dimension
        tensor = preprocess(img).unsqueeze(0).to(DEVICE)
        
        with torch.no_grad():
            # Get raw image features/embeddings
            features = model.encode_image(tensor)
            # Normalize to unit length (L2 norm) for direct cosine similarity calculation
            features /= features.norm(dim=-1, keepdim=True)
            
        return features.squeeze().cpu().numpy()
    except Exception as e:
        print(f"Error generating embedding for {image_path}: {e}")
        return None
