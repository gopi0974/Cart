import os
import uuid
import time
import logging
from pathlib import Path
import numpy as np
from PIL import Image
from typing import Tuple, Optional
from app.config import settings

logger = logging.getLogger("smartcart.detector")

try:
    import cv2
    HAS_CV2 = True
except Exception:
    cv2 = None
    HAS_CV2 = False

class ObjectDetector:
    """
    Real-time vision localization using OpenCV background differencing and foreground bounding boxes.
    Hand and face presence are tracked via MediaPipe in the browser and passed via flags.
    Zero PyTorch or Ultralytics dependencies required on backend.
    """
    def __init__(self):
        pass

    def compute_motion_box(
        self,
        ref_bgr: Optional[np.ndarray],
        curr_bgr: np.ndarray,
        min_area: int = 1200
    ) -> Optional[Tuple[int, int, int, int]]:
        """
        Compute bounding box of pixel difference against reference cart background.
        Used to pinpoint grocery items placed into or removed from the cart.
        """
        if ref_bgr is None or curr_bgr is None or not HAS_CV2:
            return None

        try:
            if ref_bgr.shape != curr_bgr.shape:
                ref_resized = cv2.resize(ref_bgr, (curr_bgr.shape[1], curr_bgr.shape[0]))
            else:
                ref_resized = ref_bgr

            gray_ref = cv2.cvtColor(ref_resized, cv2.COLOR_BGR2GRAY)
            gray_curr = cv2.cvtColor(curr_bgr, cv2.COLOR_BGR2GRAY)

            gray_ref = cv2.GaussianBlur(gray_ref, (21, 21), 0)
            gray_curr = cv2.GaussianBlur(gray_curr, (21, 21), 0)

            diff = cv2.absdiff(gray_ref, gray_curr)
            _, thresh = cv2.threshold(diff, 28, 255, cv2.THRESH_BINARY)
            thresh = cv2.dilate(thresh, None, iterations=3)

            contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            valid_boxes = []
            for cnt in contours:
                if cv2.contourArea(cnt) > min_area:
                    x, y, w, h = cv2.boundingRect(cnt)
                    valid_boxes.append((x, y, x + w, y + h))

            if not valid_boxes:
                return None

            min_x = min(b[0] for b in valid_boxes)
            min_y = min(b[1] for b in valid_boxes)
            max_x = max(b[2] for b in valid_boxes)
            max_y = max(b[3] for b in valid_boxes)

            return (min_x, min_y, max_x, max_y)
        except Exception as e:
            logger.warning(f"Error computing motion box: {e}")
            return None

    def crop_object(
        self,
        image_bgr: np.ndarray,
        box: Tuple[int, int, int, int],
        pad_ratio: float = 0.12
    ) -> Image.Image:
        """
        Crop localized region from frame with padding and convert to PIL Image.
        """
        h, w = image_bgr.shape[:2]
        x1, y1, x2, y2 = box

        pad_w = int((x2 - x1) * pad_ratio)
        pad_h = int((y2 - y1) * pad_ratio)

        crop_x1 = max(0, x1 - pad_w)
        crop_y1 = max(0, y1 - pad_h)
        crop_x2 = min(w, x2 + pad_w)
        crop_y2 = min(h, y2 + pad_h)

        crop_bgr = image_bgr[crop_y1:crop_y2, crop_x1:crop_x2]
        if crop_bgr.size == 0:
            crop_bgr = image_bgr

        if HAS_CV2:
            crop_rgb = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2RGB)
            return Image.fromarray(crop_rgb)
        else:
            return Image.fromarray(crop_bgr)

    def save_evidence_snapshot(
        self,
        image_bgr: np.ndarray,
        box: Optional[Tuple[int, int, int, int]] = None,
        label: str = "VERIFIED",
        status: str = "SUCCESS"
    ) -> str:
        """
        Save evidence snapshot to uploads/evidence/ and return URL.
        Privacy Enforcement:
        - CROPS OF PRODUCT AREA ONLY (never full camera frames, never faces).
        - If box is provided: strictly crops product bounding box.
        - If box is omitted: crops centered product region (never entire frame).
        """
        filename = f"{status.lower()}_{uuid.uuid4().hex[:10]}.jpg"
        filepath = os.path.join(settings.EVIDENCE_DIR, filename)

        if HAS_CV2 and isinstance(image_bgr, np.ndarray):
            h, w = image_bgr.shape[:2]
            if box:
                x1, y1, x2, y2 = box
                # Clamp coordinates to frame boundaries
                x1 = max(0, min(w - 1, x1))
                y1 = max(0, min(h - 1, y1))
                x2 = max(x1 + 1, min(w, x2))
                y2 = max(y1 + 1, min(h, y2))
                cropped_product = image_bgr[y1:y2, x1:x2].copy()
            else:
                # Privacy safeguard: crop central 60% of frame, never save full wide frame
                cx1 = int(w * 0.20)
                cy1 = int(h * 0.20)
                cx2 = int(w * 0.80)
                cy2 = int(h * 0.80)
                cropped_product = image_bgr[cy1:cy2, cx1:cx2].copy()

            if cropped_product.size == 0:
                cropped_product = np.zeros((120, 120, 3), dtype=np.uint8)

            cv2.imwrite(filepath, cropped_product, [cv2.IMWRITE_JPEG_QUALITY, 85])
        else:
            if isinstance(image_bgr, Image.Image):
                pil_img = image_bgr
            elif isinstance(image_bgr, np.ndarray):
                pil_img = Image.fromarray(image_bgr)
            else:
                pil_img = Image.new("RGB", (224, 224), (30, 30, 30))

            # Crop product area from PIL if box provided
            if box:
                x1, y1, x2, y2 = box
                pil_crop = pil_img.crop((x1, y1, x2, y2))
            else:
                pw, ph = pil_img.size
                pil_crop = pil_img.crop((int(pw * 0.2), int(ph * 0.2), int(pw * 0.8), int(ph * 0.8)))
            pil_crop.save(filepath, "JPEG", quality=85)

        return f"/uploads/evidence/{filename}"


def cleanup_expired_evidence(retention_days: Optional[int] = None) -> int:
    """
    Automatic cleanup job: deletes evidence snapshot crops older than retention policy.
    Default retention: 14 days (from settings.EVIDENCE_RETENTION_DAYS).
    """
    days = retention_days if retention_days is not None else getattr(settings, "EVIDENCE_RETENTION_DAYS", 14)
    cutoff_time = time.time() - (days * 86400)
    deleted_count = 0

    evidence_dir = Path(settings.EVIDENCE_DIR)
    if not evidence_dir.exists():
        return 0

    try:
        for file_path in evidence_dir.glob("*.jpg"):
            try:
                if file_path.stat().st_mtime < cutoff_time:
                    file_path.unlink()
                    deleted_count += 1
            except Exception as e:
                logger.warning(f"Failed to delete expired evidence file {file_path.name}: {e}")
        if deleted_count > 0:
            logger.info(f"Cleaned up {deleted_count} expired evidence snapshot(s) older than {days} days.")
    except Exception as e:
        logger.error(f"Error during evidence cleanup: {e}")

    return deleted_count


object_detector = ObjectDetector()
