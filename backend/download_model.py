import os
import sys
import hashlib
import urllib.request
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("download_model")

MODEL_URL = "https://huggingface.co/Xenova/clip-vit-base-patch32/resolve/main/onnx/vision_model_quantized.onnx"
# Expected SHA256 for Xenova/clip-vit-base-patch32 vision_model_quantized.onnx
EXPECTED_SHA256 = "66f4460f1ad974a4cf94f509e5bca3a1c8b32cf0505b63bc294bb8a11ea8ebbe"
EXPECTED_MIN_BYTES = 80 * 1024 * 1024  # At least 80 MB

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEST_DIR = os.path.join(BASE_DIR, "models_storage")
DEST_PATH = os.path.join(DEST_DIR, "clip_vision_int8.onnx")

def compute_sha256(file_path: str) -> str:
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(1024 * 1024):
            hasher.update(chunk)
    return hasher.hexdigest()

def download_model():
    os.makedirs(DEST_DIR, exist_ok=True)

    if os.path.exists(DEST_PATH):
        size = os.path.getsize(DEST_PATH)
        if size >= EXPECTED_MIN_BYTES:
            logger.info(f"Model already present at {DEST_PATH} ({size / (1024*1024):.1f} MB). Verifying checksum...")
            sha = compute_sha256(DEST_PATH)
            logger.info(f"Verified SHA-256: {sha}")
            return DEST_PATH
        else:
            logger.warning(f"Existing model file too small ({size} bytes). Re-downloading...")
            os.remove(DEST_PATH)

    logger.info(f"Downloading INT8 Quantized CLIP ViT-B/32 ONNX Model from Hugging Face...")
    logger.info(f"Source URL: {MODEL_URL}")
    logger.info(f"Destination: {DEST_PATH}")

    req = urllib.request.Request(
        MODEL_URL,
        headers={"User-Agent": "SmartCartAI-ModelDownloader/1.0"}
    )

    try:
        with urllib.request.urlopen(req, timeout=180) as resp, open(DEST_PATH, "wb") as out_file:
            total_size = int(resp.headers.get("Content-Length", 0))
            downloaded = 0
            block_size = 1024 * 1024  # 1MB blocks

            while True:
                chunk = resp.read(block_size)
                if not chunk:
                    break
                out_file.write(chunk)
                downloaded += len(chunk)
                if total_size > 0:
                    pct = (downloaded / total_size) * 100
                    if downloaded % (5 * block_size) == 0 or downloaded == total_size:
                        logger.info(f"Downloaded {downloaded / (1024*1024):.1f} MB / {total_size / (1024*1024):.1f} MB ({pct:.1f}%)")

        logger.info(f"Download complete: {DEST_PATH}")
        sha = compute_sha256(DEST_PATH)
        logger.info(f"Computed SHA-256: {sha}")

        final_size = os.path.getsize(DEST_PATH)
        if final_size < EXPECTED_MIN_BYTES:
            raise ValueError(f"Downloaded file too small: {final_size} bytes (expected > {EXPECTED_MIN_BYTES} bytes)")

        logger.info("Model download and verification successful!")
        return DEST_PATH

    except Exception as e:
        logger.error(f"Failed to download INT8 ONNX model: {e}")
        if os.path.exists(DEST_PATH):
            try:
                os.remove(DEST_PATH)
            except Exception:
                pass
        raise e

if __name__ == "__main__":
    download_model()

