import os
import cv2
import uuid
import logging
import numpy as np
from PIL import Image
from typing import Dict, Any, Tuple, Optional, List
from ultralytics import YOLO
from app.config import settings

logger = logging.getLogger("smartcart.detector")

class ObjectDetector:
    """
    Real-time vision localization using YOLOv8n and background motion differencing.
    Locates hand/person occlusion (COCO class 0) to ensure image stabilization before judging,
    and isolates placed objects for high-precision CLIP visual embedding matching.
    """
    def __init__(self):
        self.model_path = os.path.join(settings.MODELS_DIR, "yolov8n.pt")
        if not os.path.exists(self.model_path):
            logger.info("YOLOv8n weights not found in models_storage. Downloading yolov8n.pt...")
            model = YOLO("yolov8n.pt")
            if os.path.exists("yolov8n.pt"):
                import shutil
                shutil.move("yolov8n.pt", self.model_path)
            self.model = model
        else:
            self.model = YOLO(self.model_path)
        logger.info(f"YOLOv8n object detector loaded successfully from {self.model_path}")

    def detect(self, image_bgr: np.ndarray) -> Dict[str, Any]:
        """
        Run YOLOv8n inference on image.
        Returns detected hands/persons and object bounding boxes.
        """
        results = self.model(image_bgr, verbose=False)
        boxes = results[0].boxes

        hand_detected = False
        hand_boxes = []
        object_boxes = []

        for b in boxes:
            cls_id = int(b.cls[0])
            conf = float(b.conf[0])
            xyxy = [int(v) for v in b.xyxy[0].tolist()]

            # Class 0 in COCO is person (hands, arms, shopper reaching in)
            if cls_id == 0 and conf > 0.35:
                hand_detected = True
                hand_boxes.append({"box": xyxy, "conf": conf, "label": "person_hand"})
            elif conf > 0.20:
                cls_name = self.model.names.get(cls_id, "object")
                object_boxes.append({"box": xyxy, "conf": conf, "label": cls_name})

        return {
            "hand_detected": hand_detected,
            "hand_boxes": hand_boxes,
            "object_boxes": object_boxes,
            "total_detections": len(boxes)
        }

    def compute_motion_box(
        self,
        ref_bgr: Optional[np.ndarray],
        curr_bgr: np.ndarray,
        min_area: int = 1200
    ) -> Optional[Tuple[int, int, int, int]]:
        """
        Compute bounding box of pixel change against reference cart background.
        Used to pinpoint grocery items that COCO YOLO does not natively recognize.
        """
        if ref_bgr is None or curr_bgr is None:
            return None

        try:
            # Ensure matching shapes
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

            # Merge bounding boxes
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
        Crop localized region from frame with padding and convert to PIL Image for CLIP.
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

        crop_rgb = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2RGB)
        return Image.fromarray(crop_rgb)

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
        annotated = image_bgr.copy()
        h, w = annotated.shape[:2]

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

        # Save JPEG
        filename = f"{status.lower()}_{uuid.uuid4().hex[:10]}.jpg"
        filepath = os.path.join(settings.EVIDENCE_DIR, filename)
        cv2.imwrite(filepath, annotated, [cv2.IMWRITE_JPEG_QUALITY, 85])

        return f"/uploads/evidence/{filename}"

object_detector = ObjectDetector()
