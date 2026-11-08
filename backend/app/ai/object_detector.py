import os
import uuid
import logging
import numpy as np
from PIL import Image
from typing import Dict, Any, Tuple, Optional, List
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
        Save real annotated evidence image to uploads/evidence/ and return URL.
        """
        filename = f"{status.lower()}_{uuid.uuid4().hex[:10]}.jpg"
        filepath = os.path.join(settings.EVIDENCE_DIR, filename)

        if HAS_CV2 and isinstance(image_bgr, np.ndarray):
            annotated = image_bgr.copy()
            if box:
                x1, y1, x2, y2 = box
                color = (34, 197, 94) if status == "SUCCESS" else (59, 130, 246) if status == "UNCERTAIN" else (239, 68, 68)
                cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)
                cv2.putText(
                    annotated,
                    label[:32],
                    (max(10, x1), max(25, y1 - 10)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6,
                    color,
                    2
                )
            cv2.imwrite(filepath, annotated, [cv2.IMWRITE_JPEG_QUALITY, 85])
        else:
            if isinstance(image_bgr, np.ndarray):
                pil_img = Image.fromarray(image_bgr)
            elif isinstance(image_bgr, Image.Image):
                pil_img = image_bgr
            else:
                pil_img = Image.new("RGB", (640, 480), (30, 30, 30))
            pil_img.save(filepath, "JPEG", quality=85)

        return f"/uploads/evidence/{filename}"

object_detector = ObjectDetector()
