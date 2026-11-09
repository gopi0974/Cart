import os
import io
import logging
from typing import Optional
from pathlib import Path
import httpx
from PIL import Image

from app.config import settings
from app.utils.sanitization import sanitize_secrets

logger = logging.getLogger("smartcart.storage")


class StorageService:
    """
    Manages image frame persistence for 360-degree vision scans.
    Prioritizes Supabase Storage (private bucket) to keep Render disk and memory free.
    Falls back gracefully to local disk in offline / local development environments.
    """

    def __init__(self):
        self.supabase_url = (settings.SUPABASE_URL or "").rstrip("/")
        self.service_key = settings.SUPABASE_SERVICE_ROLE_KEY or ""
        self.bucket = settings.SUPABASE_STORAGE_BUCKET or "smartcart-360-scans"
        self.local_dir = settings.UPLOADS_DIR / "scan_frames"
        self.local_dir.mkdir(parents=True, exist_ok=True)

    @property
    def is_supabase_configured(self) -> bool:
        return bool(self.supabase_url and self.service_key)

    def save_frame(self, job_id: str, filename: str, image_bytes: bytes) -> str:
        """
        Saves frame bytes to Supabase Storage or local directory.
        Returns a reference string (e.g., 'supabase://bucket/job_id/filename' or local path).
        """
        if self.is_supabase_configured:
            storage_path = f"{job_id}/{filename}"
            upload_url = f"{self.supabase_url}/storage/v1/object/{self.bucket}/{storage_path}"
            headers = {
                "Authorization": f"Bearer {self.service_key}",
                "apikey": self.service_key,
                "Content-Type": "image/jpeg",
                "x-upsert": "true",
            }
            try:
                with httpx.Client(timeout=30.0) as client:
                    resp = client.post(upload_url, content=image_bytes, headers=headers)
                    if resp.status_code in (200, 201):
                        return f"supabase://{self.bucket}/{storage_path}"
                    else:
                        logger.warning(
                            f"Supabase Storage upload returned {resp.status_code}: {resp.text}. Falling back to disk."
                        )
            except Exception as e:
                logger.warning(f"Supabase Storage upload failed: {sanitize_secrets(e)}. Falling back to disk.")

        # Local disk fallback
        job_dir = self.local_dir / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        file_path = job_dir / filename
        with open(file_path, "wb") as f:
            f.write(image_bytes)
        return str(file_path)

    def load_frame_image(self, frame_ref: str) -> Image.Image:
        """
        Loads a PIL Image from either a Supabase reference or local path.
        """
        if frame_ref.startswith("supabase://"):
            # Format: supabase://{bucket}/{path}
            parts = frame_ref[len("supabase://"):].split("/", 1)
            if len(parts) == 2:
                bucket, path = parts
                url = f"{self.supabase_url}/storage/v1/object/authenticated/{bucket}/{path}"
                headers = {
                    "Authorization": f"Bearer {self.service_key}",
                    "apikey": self.service_key,
                }
                with httpx.Client(timeout=30.0) as client:
                    resp = client.get(url, headers=headers)
                    if resp.status_code == 200:
                        return Image.open(io.BytesIO(resp.content)).convert("RGB")
                    # Fallback to direct object endpoint
                    url_direct = f"{self.supabase_url}/storage/v1/object/{bucket}/{path}"
                    resp_dir = client.get(url_direct, headers=headers)
                    if resp_dir.status_code == 200:
                        return Image.open(io.BytesIO(resp_dir.content)).convert("RGB")
                    raise RuntimeError(f"Failed to fetch frame from Supabase: HTTP {resp.status_code}")

        # Local file path
        if os.path.exists(frame_ref):
            return Image.open(frame_ref).convert("RGB")

        raise FileNotFoundError(f"Frame image not found at reference: {frame_ref}")


storage_service = StorageService()

