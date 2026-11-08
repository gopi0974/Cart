import os
import sys
import hashlib
import urllib.request
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("download_model")

# Primary and fallback URLs for Xenova INT8 quantized CLIP ViT-B/32 vision encoder
MODEL_URLS = [
    "https://huggingface.co/Xenova/clip-vit-base-patch32/resolve/main/onnx/vision_model_quantized.onnx",
    "https://huggingface.co/Xenova/clip-vit-base-patch32/raw/main/onnx/vision_model_quantized.onnx",
]

# Verified SHA-256 for Xenova/clip-vit-base-patch32 vision_model_quantized.onnx (85.0 MB)
EXPECTED_SHA256 = "583fd1110a514667812fee7d684952aaf82a99b959760c8d7dca7e0ab9839299"
EXPECTED_MIN_BYTES = 50 * 1024 * 1024  # At least 50 MB

# Working directory safety: always resolve to backend/models_storage regardless of where script is invoked
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEST_DIR = os.path.join(SCRIPT_DIR, "models_storage")
DEST_PATH = os.path.join(DEST_DIR, "clip_vision_int8.onnx")

def compute_sha256(file_path: str) -> str:
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(1024 * 1024):
            hasher.update(chunk)
    return hasher.hexdigest().lower()

def download_model() -> bool:
    """
    Download INT8 Quantized CLIP ViT-B/32 ONNX model at build time.
    Verifies SHA-256 checksum against EXPECTED_SHA256.
    Returns True on success, False or raises on failure.
    """
    os.makedirs(DEST_DIR, exist_ok=True)

    if os.path.exists(DEST_PATH):
        size = os.path.getsize(DEST_PATH)
        if size >= EXPECTED_MIN_BYTES:
            logger.info(f"Model already present at {DEST_PATH} ({size / (1024*1024):.1f} MB). Verifying SHA-256...")
            actual_sha = compute_sha256(DEST_PATH)
            if actual_sha == EXPECTED_SHA256:
                logger.info(f"Checksum verified: {actual_sha}")
                return True
            else:
                logger.warning(f"Checksum mismatch for existing file! Expected {EXPECTED_SHA256}, got {actual_sha}. Removing...")
                os.remove(DEST_PATH)
        else:
            logger.warning(f"Existing model file too small ({size} bytes). Removing partial download...")
            try:
                os.remove(DEST_PATH)
            except Exception:
                pass

    logger.info(f"Target model destination: {DEST_PATH}")

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "*/*"
    }

    temp_path = DEST_PATH + ".tmp"

    for url in MODEL_URLS:
        logger.info(f"Attempting download from: {url}")
        try:
            req = urllib.request.Request(url, headers=headers)
            downloaded = 0
            with urllib.request.urlopen(req, timeout=120) as resp, open(temp_path, "wb") as out_file:
                block_size = 512 * 1024  # 512 KB chunks
                while True:
                    chunk = resp.read(block_size)
                    if not chunk:
                        break
                    out_file.write(chunk)
                    downloaded += len(chunk)

            # File is now closed; safe to inspect and rename on all OS platforms
            if downloaded >= EXPECTED_MIN_BYTES:
                computed_sha = compute_sha256(temp_path)
                if computed_sha != EXPECTED_SHA256:
                    os.remove(temp_path)
                    raise ValueError(
                        f"CRITICAL: Checksum verification failed for {url}!\n"
                        f"Expected: {EXPECTED_SHA256}\n"
                        f"Actual:   {computed_sha}"
                    )

                if os.path.exists(DEST_PATH):
                    os.remove(DEST_PATH)
                os.rename(temp_path, DEST_PATH)
                final_size = os.path.getsize(DEST_PATH)
                logger.info(f"Successfully downloaded and verified INT8 model: {DEST_PATH} ({final_size / (1024*1024):.1f} MB).")
                logger.info(f"Verified SHA-256: {computed_sha}")
                return True
            else:
                logger.warning(f"Downloaded stream from {url} too small ({downloaded} bytes). Trying next source...")
                if os.path.exists(temp_path):
                    os.remove(temp_path)

        except ValueError as ve:
            # Fatal checksum failure: do not swallow
            logger.error(str(ve))
            raise ve
        except Exception as e:
            logger.warning(f"Download attempt from {url} failed: {e}")
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception:
                    pass

    logger.error("Build-time model download failed from all candidate URLs.")
    return False

if __name__ == "__main__":
    try:
        success = download_model()
        if success:
            logger.info("download_model: Model ready and checksum verified.")
            sys.exit(0)
        else:
            logger.error("download_model: Model download failed.")
            sys.exit(1)
    except Exception as e:
        logger.error(f"download_model fatal error: {e}")
        # Build MUST fail if download or checksum validation fails
        sys.exit(1)
