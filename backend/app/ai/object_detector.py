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

    def detect_all_objects(
        self,
        ref_bgr: Optional[np.ndarray],
        curr_bgr: np.ndarray,
        min_area: int = 1200
    ) -> list[Tuple[int, int, int, int]]:
        """
        Compute all distinct foreground bounding boxes against reference cart background (R4).
        Returns list of (min_x, min_y, max_x, max_y) for each detected object in the cart.
        """
        if ref_bgr is None or curr_bgr is None or not HAS_CV2:
            return []

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

            return valid_boxes
        except Exception as e:
            logger.warning(f"Error detecting all objects: {e}")
            return []

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
        valid_boxes = self.detect_all_objects(ref_bgr, curr_bgr, min_area=min_area)
        if not valid_boxes:
            return None

        min_x = min(b[0] for b in valid_boxes)
        min_y = min(b[1] for b in valid_boxes)
        max_x = max(b[2] for b in valid_boxes)
        max_y = max(b[3] for b in valid_boxes)

        return (min_x, min_y, max_x, max_y)

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
        status: str = "SUCCESS",
        hand_present: bool = False,
        face_present: bool = False
    ) -> Optional[str]:
        """
        Save evidence snapshot crop to private Supabase bucket smartcart-evidence and return object path.
        Never falls back to local disk.
        Privacy Enforcement:
        - CROPS OF PRODUCT AREA ONLY (never full camera frames, never faces).
        - If hand_present or face_present: NEVER save snapshot, return None.
        """
        if hand_present or face_present:
            return None

        import io
        from app.services.storage_service import storage_service

        filename = f"{status.lower()}_{uuid.uuid4().hex[:10]}.jpg"
        object_path = f"evidence/{filename}"
        jpeg_bytes: Optional[bytes] = None

        if HAS_CV2 and isinstance(image_bgr, np.ndarray):
            h, w = image_bgr.shape[:2]
            if box:
                x1, y1, x2, y2 = box
                x1 = max(0, min(w - 1, x1))
                y1 = max(0, min(h - 1, y1))
                x2 = max(x1 + 1, min(w, x2))
                y2 = max(y1 + 1, min(h, y2))
                cropped_product = image_bgr[y1:y2, x1:x2].copy()
            else:
                cx1 = int(w * 0.20)
                cy1 = int(h * 0.20)
                cx2 = int(w * 0.80)
                cy2 = int(h * 0.80)
                cropped_product = image_bgr[cy1:cy2, cx1:cx2].copy()

            if cropped_product.size == 0:
                cropped_product = np.zeros((120, 120, 3), dtype=np.uint8)

            ok, buf = cv2.imencode(".jpg", cropped_product, [cv2.IMWRITE_JPEG_QUALITY, 85])
            if ok:
                jpeg_bytes = buf.tobytes()
        else:
            if isinstance(image_bgr, Image.Image):
                pil_img = image_bgr
            elif isinstance(image_bgr, np.ndarray):
                pil_img = Image.fromarray(image_bgr)
            else:
                pil_img = Image.new("RGB", (224, 224), (30, 30, 30))

            if box:
                x1, y1, x2, y2 = box
                pil_crop = pil_img.crop((x1, y1, x2, y2))
            else:
                pw, ph = pil_img.size
                pil_crop = pil_img.crop((int(pw * 0.2), int(ph * 0.2), int(pw * 0.8), int(ph * 0.8)))
            buf_io = io.BytesIO()
            pil_crop.save(buf_io, "JPEG", quality=85)
            jpeg_bytes = buf_io.getvalue()

        if not jpeg_bytes:
            return None

        uploaded_ref = storage_service.upload_bytes(
            object_path=object_path,
            data=jpeg_bytes,
            content_type="image/jpeg",
        )
        if not uploaded_ref:
            logger.warning("Evidence crop not saved: smartcart-evidence storage is not configured or upload failed.")
        return uploaded_ref


def cleanup_expired_evidence(db=None, retention_days: Optional[int] = None) -> int:
    """
    Automatic cleanup job: deletes expired evidence snapshot crops from smartcart-evidence bucket
    AND clears database references (Alert.evidence_path / evidence_snapshot_url and
    CartItem.last_known_crop_path / verification_evidence_url) together.
    """
    from datetime import datetime, timedelta
    from app.services.storage_service import storage_service
    from app.database import SessionLocal

    days = retention_days if retention_days is not None else getattr(settings, "EVIDENCE_RETENTION_DAYS", 14)
    cutoff_dt = datetime.utcnow() - timedelta(days=days)
    deleted_count = 0

    own_db = False
    if db is None:
        if not SessionLocal:
            return 0
        db = SessionLocal()
        own_db = True

    try:
        from app.models.alert import Alert
        from app.models.session import CartItem, CartSession

        expired_alerts = db.query(Alert).filter(
            Alert.created_at < cutoff_dt,
            (Alert.evidence_path.isnot(None)) | (Alert.evidence_snapshot_url.isnot(None)),
        ).all()
        for al in expired_alerts:
            for ref in {al.evidence_path, al.evidence_snapshot_url}:
                if ref and str(ref).startswith("supabase://"):
                    if storage_service.delete_object(ref):
                        deleted_count += 1
            al.evidence_path = None
            al.evidence_snapshot_url = None

        expired_items = (
            db.query(CartItem)
            .join(CartSession, CartItem.session_id == CartSession.id)
            .filter(
                CartSession.status != "ACTIVE",
                CartItem.scanned_at < cutoff_dt,
                (CartItem.last_known_crop_path.isnot(None)) | (CartItem.verification_evidence_url.isnot(None)),
            )
            .all()
        )
        for itm in expired_items:
            for ref in {itm.last_known_crop_path, itm.verification_evidence_url}:
                if ref and str(ref).startswith("supabase://"):
                    if storage_service.delete_object(ref):
                        deleted_count += 1
            itm.last_known_crop_path = None
            itm.verification_evidence_url = None

        db.commit()
    except Exception as e:
        logger.error(f"Error during evidence retention cleanup: {e}")
        try:
            db.rollback()
        except Exception:
            pass
    finally:
        if own_db and db is not None:
            db.close()

    return deleted_count


object_detector = ObjectDetector()
