import os
import io
import base64
import logging
from typing import List, Any, Union
import numpy as np
import torch
from PIL import Image
from transformers import CLIPProcessor, CLIPVisionModelWithProjection

logger = logging.getLogger("smartcart.ai.feature_extractor")

MODEL_NAME = "openai/clip-vit-base-patch32"
MODEL_VERSION = "v1.0.0-clip"
VECTOR_DIM = 512

# Determine local models storage path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LOCAL_MODEL_DIR = os.path.join(BASE_DIR, "models_storage", "clip_vision")
FALLBACK_MODEL_DIR = os.path.join(BASE_DIR, "models_storage", "clip-vit-base-patch32")

_processor = None
_model = None

def _load_model():
    """Load pretrained CLIP ViT-B/32 vision model from local cache for offline execution."""
    global _processor, _model
    if _model is not None and _processor is not None:
        return _processor, _model

    model_dir = None
    if os.path.exists(LOCAL_MODEL_DIR) and os.listdir(LOCAL_MODEL_DIR):
        model_dir = LOCAL_MODEL_DIR
    elif os.path.exists(FALLBACK_MODEL_DIR) and os.listdir(FALLBACK_MODEL_DIR):
        model_dir = FALLBACK_MODEL_DIR

    if model_dir:
        logger.info(f"Loading real CLIP ViT-B/32 from local offline cache: {model_dir}")
        try:
            _processor = CLIPProcessor.from_pretrained(model_dir, local_files_only=True)
            _model = CLIPVisionModelWithProjection.from_pretrained(model_dir, local_files_only=True)
        except Exception as e:
            logger.warning(f"Failed loading with local_files_only from {model_dir}: {e}. Retrying standard load...")
            _processor = CLIPProcessor.from_pretrained(model_dir)
            _model = CLIPVisionModelWithProjection.from_pretrained(model_dir)
    else:
        logger.info(f"Downloading real CLIP ViT-B/32 ({MODEL_NAME}) and saving locally for offline use...")
        _processor = CLIPProcessor.from_pretrained(MODEL_NAME)
        _model = CLIPVisionModelWithProjection.from_pretrained(MODEL_NAME)
        os.makedirs(LOCAL_MODEL_DIR, exist_ok=True)
        _processor.save_pretrained(LOCAL_MODEL_DIR)
        _model.save_pretrained(LOCAL_MODEL_DIR)

    _model.eval()
    logger.info("CLIP ViT-B/32 vision embedding model loaded and ready.")
    return _processor, _model

def _preprocess_image_input(image_input: Any) -> Image.Image:
    """Standardize any image representation into an RGB PIL Image."""
    if isinstance(image_input, Image.Image):
        return image_input.convert("RGB")

    if isinstance(image_input, np.ndarray):
        if len(image_input.shape) == 2:
            return Image.fromarray(image_input).convert("RGB")
        elif len(image_input.shape) == 3:
            # OpenCV BGR to RGB
            if image_input.shape[2] == 3:
                rgb_arr = image_input[:, :, ::-1]
                return Image.fromarray(rgb_arr).convert("RGB")
            elif image_input.shape[2] == 4:
                return Image.fromarray(image_input).convert("RGB")
        return Image.fromarray(image_input).convert("RGB")

    if isinstance(image_input, bytes):
        return Image.open(io.BytesIO(image_input)).convert("RGB")

    if isinstance(image_input, str):
        # 1. Check if it's a file path on disk
        if os.path.exists(image_input) and os.path.isfile(image_input):
            return Image.open(image_input).convert("RGB")

        # 2. Check if it's a data URL (e.g. data:image/jpeg;base64,...)
        raw_b64 = image_input
        if image_input.startswith("data:image"):
            parts = image_input.split(",", 1)
            if len(parts) == 2:
                raw_b64 = parts[1]

        # 3. Decode base64
        try:
            image_bytes = base64.b64decode(raw_b64)
            return Image.open(io.BytesIO(image_bytes)).convert("RGB")
        except Exception as e:
            raise ValueError(f"Failed to decode base64 image string: {e}")

    raise TypeError(f"Unsupported image input type: {type(image_input)}")

def get_embedding(image: Any) -> List[float]:
    """
    Unified embedding function used everywhere (360 scan enrollment AND cart-camera recognition).
    Extracts a 512-dimensional L2-normalized vector using CLIP ViT-B/32.
    """
    proc, model = _load_model()
    pil_image = _preprocess_image_input(image)

    # Validate image dimensions
    if pil_image.width < 10 or pil_image.height < 10:
        raise ValueError(f"Image too small for embedding extraction: {pil_image.width}x{pil_image.height}")

    with torch.no_grad():
        inputs = proc(images=pil_image, return_tensors="pt")
        outputs = model(**inputs)
        image_embeds = outputs.image_embeds
        # L2-normalize
        norm = image_embeds.norm(p=2, dim=-1, keepdim=True)
        if norm > 0:
            image_embeds = image_embeds / norm
        vector = image_embeds.cpu().numpy()[0].tolist()

    return vector

class VisualFeatureExtractor:
    """Wrapper class maintaining backward compatibility while using the unified get_embedding model."""
    def __init__(self, embedding_dim: int = VECTOR_DIM):
        self.embedding_dim = embedding_dim
        self.model_name = MODEL_NAME
        self.model_version = MODEL_VERSION

    def extract_embedding(self, image_input: Any) -> List[float]:
        return get_embedding(image_input)

    @staticmethod
    def cosine_similarity(vec_a: List[float], vec_b: List[float]) -> float:
        """Compute cosine similarity between two normalized vectors."""
        a = np.array(vec_a, dtype=np.float32)
        b = np.array(vec_b, dtype=np.float32)
        dot = float(np.dot(a, b))
        norm_a = float(np.linalg.norm(a))
        norm_b = float(np.linalg.norm(b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return float(dot / (norm_a * norm_b))

feature_extractor = VisualFeatureExtractor()
