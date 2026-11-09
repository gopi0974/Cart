import os
import io
import logging
from typing import Optional
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

    def create_signed_upload_url(self, job_id: str, filename: str) -> Optional[dict]:
        """
        Generates a signed upload URL in Supabase Storage allowing direct client-side upload.
        Returns dict with upload_url and frame_ref, or None if Supabase is unavailable.
        """
        if not self.is_supabase_configured:
            return None

        storage_path = f"{job_id}/{filename}"
        sign_endpoint = f"{self.supabase_url}/storage/v1/object/upload/sign/{self.bucket}/{storage_path}"
        headers = {
            "Authorization": f"Bearer {self.service_key}",
            "apikey": self.service_key,
            "Content-Type": "application/json",
        }
        try:
            with httpx.Client(timeout=10.0) as client:
                # Supabase storage accepts upsert parameter
                resp = client.post(sign_endpoint, json={"upsert": True}, headers=headers)
                if resp.status_code not in (200, 201):
                    # Fallback attempt with empty payload
                    resp = client.post(sign_endpoint, json={}, headers=headers)

                if resp.status_code in (200, 201):
                    data = resp.json()
                    relative_url = data.get("url")
                    if relative_url:
                        # Ensure /storage/v1 is present if relative url begins with /object/
                        if relative_url.startswith("/object/"):
                            full_upload_url = f"{self.supabase_url}/storage/v1{relative_url}"
                        elif relative_url.startswith("/"):
                            full_upload_url = f"{self.supabase_url}{relative_url}"
                        else:
                            full_upload_url = f"{self.supabase_url}/{relative_url}"

                        return {
                            "upload_url": full_upload_url,
                            "frame_ref": f"supabase://{self.bucket}/{storage_path}",
                            "storage_path": storage_path,
                        }
                else:
                    logger.warning(
                        f"Supabase create_signed_upload_url returned HTTP {resp.status_code}: {resp.text}"
                    )
        except Exception as e:
            logger.warning(f"Failed to generate Supabase signed upload URL: {sanitize_secrets(e)}")

        return None

    def check_frame_exists(self, frame_ref: str) -> bool:
        """
        Checks whether a single frame reference actually exists in storage.
        Supports both supabase:// URIs and local filesystem paths.
        """
        if not frame_ref:
            return False

        if frame_ref.startswith("supabase://"):
            parts = frame_ref[len("supabase://"):].split("/", 1)
            if len(parts) == 2:
                bucket, path = parts
                url = f"{self.supabase_url}/storage/v1/object/{bucket}/{path}"
                headers = {
                    "Authorization": f"Bearer {self.service_key}",
                    "apikey": self.service_key,
                    "Range": "bytes=0-0"
                }
                try:
                    with httpx.Client(timeout=5.0) as client:
                        resp = client.get(url, headers=headers)
                        return resp.status_code in (200, 206)
                except Exception as e:
                    logger.warning(f"Frame check error for {sanitize_secrets(frame_ref)}: {sanitize_secrets(e)}")
                    return False
            return False

        # Local file reference
        return os.path.isfile(frame_ref)

    def check_frames_exist(self, frame_refs: list) -> tuple:
        """
        Verifies existence for a batch of frame references.
        Optimized to use bucket list API per folder for Supabase frames to avoid N roundtrips.
        Returns (existing_refs, missing_refs).
        """
        if not frame_refs:
            return [], []

        existing: list = []
        missing: list = []

        # Group Supabase frames by bucket and folder prefix
        supabase_by_prefix: dict = {}
        local_refs: list = []

        for ref in frame_refs:
            if not ref:
                missing.append(ref)
            elif ref.startswith("supabase://"):
                parts = ref[len("supabase://"):].split("/", 1)
                if len(parts) == 2:
                    bucket, path = parts
                    folder = path.split("/", 1)[0] if "/" in path else ""
                    filename = path.split("/", 1)[1] if "/" in path else path
                    key = (bucket, folder)
                    if key not in supabase_by_prefix:
                        supabase_by_prefix[key] = []
                    supabase_by_prefix[key].append((filename, ref))
                else:
                    missing.append(ref)
            else:
                local_refs.append(ref)

        # 1. Batch query Supabase Storage per folder prefix
        for (bucket, folder), items in supabase_by_prefix.items():
            list_url = f"{self.supabase_url}/storage/v1/object/list/{bucket}"
            headers = {
                "Authorization": f"Bearer {self.service_key}",
                "apikey": self.service_key,
                "Content-Type": "application/json",
            }
            found_names = set()
            try:
                prefix = f"{folder}/" if folder else ""
                with httpx.Client(timeout=10.0) as client:
                    resp = client.post(
                        list_url,
                        json={"prefix": prefix, "limit": 100},
                        headers=headers
                    )
                    if resp.status_code == 200:
                        files = resp.json()
                        for f in files:
                            found_names.add(f.get("name"))
                    else:
                        logger.warning(f"Supabase list objects returned {resp.status_code}. Falling back to individual checks.")
            except Exception as e:
                logger.warning(f"Supabase list failed for prefix {folder}: {sanitize_secrets(e)}. Falling back.")

            for filename, ref in items:
                if filename in found_names:
                    existing.append(ref)
                else:
                    # Fallback individual check (in case list was paginated or prefix differed)
                    if self.check_frame_exists(ref):
                        existing.append(ref)
                    else:
                        missing.append(ref)

        # 2. Check local files
        for ref in local_refs:
            if os.path.isfile(ref):
                existing.append(ref)
            else:
                missing.append(ref)

        return existing, missing

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

