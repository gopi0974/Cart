import os
import io
import time
import base64
import logging
import threading
from typing import List, Any, Optional
import numpy as np
from PIL import Image

logger = logging.getLogger("smartcart.ai.feature_extractor")

MODEL_NAME = "openai/clip-vit-base-patch32-int8"
MODEL_VERSION = "v1.1.0-onnx-int8"
VECTOR_DIM = 512

# Determine local models storage path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ONNX_MODEL_PATH = os.path.join(BASE_DIR, "models_storage", "clip_vision_int8.onnx")

# Global ONNX Inference Session and initialization flag
_onnx_session = None
_model_loading: bool = False
_model_loaded: bool = False
_model_error: Optional[str] = None
_lock = threading.Lock()

# Real inference latency metrics (populated ONLY on real embeddings, never warmup)
_embed_ms_last: Optional[float] = None
_embed_count: int = 0
_embed_total_ms: float = 0.0

def get_embedding_metrics() -> dict:
    """Return latest and average embedding inference latencies in milliseconds from REAL embeddings."""
    with _lock:
        if _embed_count == 0 or _embed_ms_last is None:
            return {
                "embed_ms_last": None,
                "embed_ms_avg": None,
                "embed_count": 0
            }
        avg = round(_embed_total_ms / _embed_count, 1)
        return {
            "embed_ms_last": round(_embed_ms_last, 1),
            "embed_ms_avg": avg,
            "embed_count": _embed_count
        }

# CLIP ViT-B/32 normalization constants
CLIP_MEAN = np.array([0.48145466, 0.4578275, 0.40821073], dtype=np.float32)
CLIP_STD = np.array([0.26862954, 0.26130258, 0.27577711], dtype=np.float32)

def is_model_ready() -> bool:
    """Return True if ONNX INT8 CLIP model is loaded and ready for inference."""
    return _model_loaded and _onnx_session is not None

def get_model_load_status() -> dict:
    """Return current model loading status and diagnostics."""
    return {
        "model_loaded": _model_loaded,
        "model_name": MODEL_NAME,
        "model_version": MODEL_VERSION,
        "vector_dimension": VECTOR_DIM,
        "model_path": ONNX_MODEL_PATH,
        "model_file_exists": os.path.exists(ONNX_MODEL_PATH),
        "error": _model_error
    }

def load_onnx_model():
    """Load ONNX Runtime inference session for INT8 CLIP vision encoder."""
    global _onnx_session, _model_loaded, _model_loading, _model_error

    with _lock:
        if _model_loaded and _onnx_session is not None:
            return _onnx_session

        _model_loading = True

        if not os.path.exists(ONNX_MODEL_PATH):
            err_msg = (
                f"Model file not found at {ONNX_MODEL_PATH}. "
                "Run `python download_model.py` at build time to fetch clip_vision_int8.onnx."
            )
            logger.warning(err_msg)
            _model_error = err_msg
            _model_loading = False
            _model_loaded = False
            return None

        try:
            import onnxruntime as ort

            # Tune session options for low memory and fast single/shared CPU execution
            opts = ort.SessionOptions()
            opts.intra_op_num_threads = 1
            opts.inter_op_num_threads = 1
            opts.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
            opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL

            logger.info(f"Loading INT8 CLIP ViT-B/32 ONNX session from {ONNX_MODEL_PATH}...")
            session = ort.InferenceSession(
                ONNX_MODEL_PATH,
                sess_options=opts,
                providers=["CPUExecutionProvider"]
            )

            # Warm up ONNX session without recording latency metrics
            input_name = session.get_inputs()[0].name
            dummy_tensor = np.zeros((1, 3, 224, 224), dtype=np.float32)
            t_warm_0 = time.perf_counter()
            _ = session.run(None, {input_name: dummy_tensor})
            warmup_ms = round((time.perf_counter() - t_warm_0) * 1000, 2)

            _onnx_session = session
            _model_loaded = True
            _model_loading = False
            _model_error = None
            logger.info(f"ONNX INT8 CLIP ViT-B/32 model loaded and ready (session warmup: {warmup_ms} ms).")
            return _onnx_session
        except Exception as e:
            err_msg = f"Failed to initialize ONNX Runtime session: {e}"
            logger.error(err_msg)
            _onnx_session = None
            _model_loaded = False
            _model_loading = False
            _model_error = str(e)
            return None

def start_background_model_loader():
    """
    Start asynchronous background thread to load the ONNX model at boot.
    Allows Uvicorn to bind immediately to 0.0.0.0:$PORT so the health check passes immediately.
    """
    if _model_loaded or _model_loading:
        return
    thread = threading.Thread(target=load_onnx_model, name="ONNXModelLoader", daemon=True)
    thread.start()

def _preprocess_image_for_clip(image_input: Any) -> np.ndarray:
    """
    Standard CLIP ViT-B/32 image preprocessor using pure PIL + NumPy.
    1. Convert input to RGB PIL Image.
    2. Resize shortest edge to 224 with bicubic interpolation.
    3. Center crop 224x224.
    4. Rescale to [0, 1] and normalize with CLIP mean and std.
    5. Transpose to CHW (1, 3, 224, 224) float32 tensor.
    """
    # 1. Standardize to PIL Image
    if isinstance(image_input, Image.Image):
        pil_img = image_input.convert("RGB")
    elif isinstance(image_input, np.ndarray):
        if len(image_input.shape) == 2:
            pil_img = Image.fromarray(image_input).convert("RGB")
        elif len(image_input.shape) == 3:
            # OpenCV BGR -> RGB
            if image_input.shape[2] == 3:
                rgb_arr = image_input[:, :, ::-1]
                pil_img = Image.fromarray(rgb_arr).convert("RGB")
            else:
                pil_img = Image.fromarray(image_input).convert("RGB")
        else:
            raise ValueError(f"Invalid numpy array shape: {image_input.shape}")
    elif isinstance(image_input, bytes):
        pil_img = Image.open(io.BytesIO(image_input)).convert("RGB")
    elif isinstance(image_input, str):
        if os.path.exists(image_input) and os.path.isfile(image_input):
            pil_img = Image.open(image_input).convert("RGB")
        else:
            raw_b64 = image_input
            if image_input.startswith("data:image"):
                parts = image_input.split(",", 1)
                if len(parts) == 2:
                    raw_b64 = parts[1]
            try:
                image_bytes = base64.b64decode(raw_b64)
                pil_img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
            except Exception as e:
                raise ValueError(f"Failed to decode base64 image string: {e}")
    else:
        raise TypeError(f"Unsupported image input type: {type(image_input)}")

    if pil_img.width < 10 or pil_img.height < 10:
        raise ValueError(f"Image too small: {pil_img.width}x{pil_img.height}")

    # 2. Resize shortest dimension to 224 (Bicubic)
    w, h = pil_img.size
    if w < h:
        new_w = 224
        new_h = int(round(h * (224.0 / w)))
    else:
        new_h = 224
        new_w = int(round(w * (224.0 / h)))

    resized = pil_img.resize((new_w, new_h), resample=Image.BICUBIC)

    # 3. Center Crop 224x224
    left = (new_w - 224) // 2
    top = (new_h - 224) // 2
    right = left + 224
    bottom = top + 224
    cropped = resized.crop((left, top, right, bottom))

    # 4. Normalize & Transpose
    arr = np.array(cropped, dtype=np.float32) / 255.0
    normalized = (arr - CLIP_MEAN) / CLIP_STD
    chw = np.transpose(normalized, (2, 0, 1))
    batched = np.expand_dims(chw, axis=0).astype(np.float32)

    return batched

def get_embedding(image: Any) -> List[float]:
    """
    Unified CLIP ViT-B/32 embedding extraction function.
    Extracts a 512-dimensional L2-normalized vector using ONNX INT8 vision model.
    NO silent fallback to fake vectors: raises RuntimeError if model is unavailable.
    """
    session = load_onnx_model()
    if session is None:
        raise RuntimeError(
            "AI Vision Model Unavailable: ONNX INT8 CLIP model is not loaded. "
            "Please ensure `download_model.py` ran at build time."
        )

    t0 = time.perf_counter()

    # Preprocess image into (1, 3, 224, 224) float32 tensor
    tensor = _preprocess_image_for_clip(image)

    # Run ONNX inference
    input_name = session.get_inputs()[0].name
    outputs = session.run(None, {input_name: tensor})

    # Output is (1, 512) image embedding
    raw_vector = np.array(outputs[0][0], dtype=np.float32)

    # L2 Normalization for Cosine Similarity
    norm = np.linalg.norm(raw_vector)
    if norm > 0:
        normalized_vector = raw_vector / norm
    else:
        normalized_vector = raw_vector

    elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
    global _embed_ms_last, _embed_count, _embed_total_ms
    with _lock:
        _embed_ms_last = elapsed_ms
        _embed_count += 1
        _embed_total_ms += elapsed_ms

    return normalized_vector.tolist()

class VisualFeatureExtractor:
    """Wrapper maintaining backward compatibility while enforcing strict ONNX INT8 inference."""
    def __init__(self, embedding_dim: int = VECTOR_DIM):
        self.embedding_dim = embedding_dim
        self.model_name = MODEL_NAME
        self.model_version = MODEL_VERSION

    def extract_embedding(self, image_input: Any) -> List[float]:
        return get_embedding(image_input)

feature_extractor = VisualFeatureExtractor()
