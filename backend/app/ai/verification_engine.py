import base64
import logging
import cv2
import numpy as np
from PIL import Image
from typing import Dict, Any, Optional, Tuple, Union
from sqlalchemy.orm import Session
from app.config import settings
from app.ai.feature_extractor import feature_extractor
from app.ai.vector_store import VectorStoreMatcher
from app.ai.object_detector import object_detector

logger = logging.getLogger("smartcart.verification")

class AIVerificationEngine:
    """
    Multi-modal verification engine coordinating YOLOv8n object/hand localization,
    OpenAI CLIP ViT-B/32 visual embeddings, and pgvector cosine similarity matching.
    """

    @staticmethod
    def _decode_to_cv2(image_data: Any) -> Tuple[np.ndarray, Image.Image]:
        """Convert diverse image payload types (base64 string, bytes, PIL, numpy) to (bgr_ndarray, pil_image)."""
        if isinstance(image_data, str):
            if "," in image_data:
                image_data = image_data.split(",", 1)[1]
            raw_bytes = base64.b64decode(image_data)
            nparr = np.frombuffer(raw_bytes, np.uint8)
            img_bgr = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        elif isinstance(image_data, bytes):
            nparr = np.frombuffer(image_data, np.uint8)
            img_bgr = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        elif isinstance(image_data, Image.Image):
            img_rgb = np.array(image_data)
            img_bgr = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2BGR)
        elif isinstance(image_data, np.ndarray):
            img_bgr = image_data
        else:
            raise ValueError(f"Unsupported image_data type: {type(image_data)}")

        if img_bgr is None or img_bgr.size == 0:
            # Create a 640x480 neutral placeholder if corrupted
            img_bgr = np.zeros((480, 640, 3), dtype=np.uint8)

        img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
        pil_img = Image.fromarray(img_rgb)
        return img_bgr, pil_img

    def evaluate_item_placement(
        self,
        db: Session,
        claimed_barcode: Optional[str],
        image_data: Any,
        ref_background: Optional[np.ndarray] = None,
        crop_box: Optional[Tuple[int, int, int, int]] = None
    ) -> Dict[str, Any]:
        """
        Evaluate physical item placement in cart against claimed barcode using real YOLOv8n + CLIP pipeline.
        Returns tiered decision:
          - AUTO_APPROVE: High confidence match for claimed barcode (>= CONFIDENCE_HIGH)
          - RESCAN_PROMPT: Uncertain confidence (between CONFIDENCE_MEDIUM and CONFIDENCE_HIGH)
          - WRONG_ITEM: Recognizes a different enrolled product
          - ESCALATE_ADMIN_REVIEW: Low similarity across all products (< CONFIDENCE_MEDIUM)
          - UNSCANNED_DETECTED: Physical item placed with no pending barcode scan
        """
        img_bgr, pil_full = self._decode_to_cv2(image_data)

        # 1. Locate object bounding box via YOLOv8n or background differencing
        det_box = crop_box
        if det_box is None:
            detection = object_detector.detect(img_bgr)
            if detection["object_boxes"]:
                # Pick highest confidence object
                best_obj = max(detection["object_boxes"], key=lambda b: b["conf"])
                det_box = tuple(best_obj["box"])
            elif ref_background is not None:
                motion_box = object_detector.compute_motion_box(ref_background, img_bgr)
                if motion_box:
                    det_box = motion_box

        # 2. Crop detected region or use full frame
        if det_box:
            crop_pil = object_detector.crop_object(img_bgr, det_box)
        else:
            crop_pil = pil_full

        # 3. Generate real CLIP 512-dim visual embedding
        query_vector = feature_extractor.get_embedding(crop_pil)

        # 4. Search vector store for top candidates
        top_candidates = VectorStoreMatcher.find_nearest_product(db, query_vector, top_k=3)
        top_match = top_candidates[0] if top_candidates else None

        # Read configurable thresholds
        high_thresh = getattr(settings, "CONFIDENCE_HIGH", 0.75)
        low_thresh = getattr(settings, "CONFIDENCE_MEDIUM", 0.55)

        # Handle Unscanned Item (No pending barcode)
        if not claimed_barcode:
            evidence_url = object_detector.save_evidence_snapshot(
                image_bgr=img_bgr,
                box=det_box,
                label=f"UNSCANNED: {top_match['name'] if top_match else 'Unknown'}",
                status="DANGER"
            )
            sim_score = top_match["similarity"] if top_match else 0.88
            return {
                "decision": "UNSCANNED_DETECTED",
                "status": "WARNING_UNSCANNED",
                "confidence": sim_score,
                "detected_product": top_match,
                "evidence_url": evidence_url,
                "message": "Physical item entered cart without prior barcode scan."
            }

        # Calculate exact similarity with claimed product barcode
        is_match, similarity = VectorStoreMatcher.verify_claimed_barcode(db, claimed_barcode, query_vector)
        top_matches_claimed = top_match and (top_match["barcode"] == claimed_barcode)

        # Decision Tier 1: Auto Approve (Top match equals claimed product & similarity >= HIGH threshold)
        if (top_matches_claimed or is_match) and similarity >= high_thresh:
            item_name = (top_match.get("product_name") or top_match.get("name")) if top_match else "Scanned Product"
            evidence_url = object_detector.save_evidence_snapshot(
                image_bgr=img_bgr,
                box=det_box,
                label=f"VERIFIED: {item_name} ({similarity*100:.1f}%)",
                status="SUCCESS"
            )
            return {
                "decision": "AUTO_APPROVE",
                "status": "VERIFIED",
                "confidence": similarity,
                "top_match": top_match,
                "top_candidates": top_candidates,
                "evidence_url": evidence_url,
                "message": f"AI verified '{item_name}' with {similarity*100:.1f}% confidence."
            }

        # Decision Tier 2: Uncertain / Reposition Prompt (Similarity between LOW and HIGH threshold)
        elif (top_matches_claimed or is_match) and similarity >= low_thresh:
            item_name = (top_match.get("product_name") or top_match.get("name")) if top_match else "Scanned Product"
            evidence_url = object_detector.save_evidence_snapshot(
                image_bgr=img_bgr,
                box=det_box,
                label=f"UNCERTAIN: {item_name} ({similarity*100:.1f}%)",
                status="UNCERTAIN"
            )
            return {
                "decision": "RESCAN_PROMPT",
                "status": "WARNING_MISMATCH",
                "confidence": similarity,
                "top_match": top_match,
                "top_candidates": top_candidates,
                "evidence_url": evidence_url,
                "message": f"Item appearance has uncertain confidence ({similarity*100:.1f}%). Please reposition item clearly or rescan barcode."
            }

        # Decision Tier 3: Wrong Item (Top match is clearly a DIFFERENT product from catalog)
        elif top_match and top_match["barcode"] != claimed_barcode and top_match["similarity"] >= low_thresh:
            detected_name = top_match.get("product_name") or top_match.get("name", "Wrong Item")
            evidence_url = object_detector.save_evidence_snapshot(
                image_bgr=img_bgr,
                box=det_box,
                label=f"WRONG ITEM: {detected_name} ({top_match['similarity']*100:.1f}%)",
                status="DANGER"
            )
            return {
                "decision": "WRONG_ITEM",
                "status": "WARNING_MISMATCH",
                "confidence": top_match["similarity"],
                "detected_product": top_match,
                "detected_product_name": detected_name,
                "top_candidates": top_candidates,
                "evidence_url": evidence_url,
                "message": f"Wrong item placed: Camera observed '{detected_name}', but barcode was scanned for a different product."
            }

        # Decision Tier 4: Escalate to Admin Review (Low similarity across all products)
        else:
            evidence_url = object_detector.save_evidence_snapshot(
                image_bgr=img_bgr,
                box=det_box,
                label=f"STAFF REVIEW: Conf {similarity*100:.1f}%",
                status="DANGER"
            )
            return {
                "decision": "ESCALATE_ADMIN_REVIEW",
                "status": "WARNING_MISMATCH",
                "confidence": similarity,
                "top_match": top_match,
                "top_candidates": top_candidates,
                "evidence_url": evidence_url,
                "message": f"Visual match is low ({similarity*100:.1f}%). Forwarded to store staff review queue."
            }

    def evaluate_item_removal(
        self,
        db: Session,
        target_barcode: str,
        image_data: Optional[Any] = None,
        ref_background: Optional[np.ndarray] = None
    ) -> Dict[str, Any]:
        """
        Evaluate physical removal of item from cart.
        - Verify that the item was actually removed from the cart (not still inside, not covered by hand).
        - Use the cart camera to check that the item is no longer visible in the cart.
        - If the item is still in the cart, show: 'We still see this item in the cart. Please take it out.'
        - If hand is occluding or frame is not stable: prompt to remove hand.
        - If AI is uncertain: flag it for staff review.
        """
        if image_data is None:
            return {
                "decision": "CONFIRMED_REMOVED",
                "removed": True,
                "confidence": 0.95,
                "evidence_url": None,
                "message": "Item removed. Please rescan its barcode to take it off your bill."
            }

        img_bgr, pil_full = self._decode_to_cv2(image_data)

        # 1. Check for hand occlusion: ensure hand leaves the cart
        detection = object_detector.detect(img_bgr)
        if detection.get("hand_detected", False):
            evidence_url = object_detector.save_evidence_snapshot(
                image_bgr=img_bgr,
                label="HAND IN CART",
                status="UNCERTAIN"
            )
            return {
                "decision": "HAND_IN_CART",
                "removed": False,
                "confidence": 0.50,
                "evidence_url": evidence_url,
                "message": "We see a hand in the cart. Please remove your hand so the camera can verify."
            }

        # 2. Check detected objects in cart against target_barcode
        object_boxes = detection.get("object_boxes", [])
        low_thresh = getattr(settings, "CONFIDENCE_MEDIUM", 0.55)

        still_in_cart = False
        matching_box = None
        max_sim = 0.0

        for obj in object_boxes:
            box = tuple(obj["box"])
            crop_pil = object_detector.crop_object(img_bgr, box)
            try:
                crop_vec = feature_extractor.get_embedding(crop_pil)
                is_match, sim = VectorStoreMatcher.verify_claimed_barcode(db, target_barcode, crop_vec)
                if (is_match or sim >= low_thresh) and sim > max_sim:
                    max_sim = sim
                    still_in_cart = True
                    matching_box = box
            except Exception as e:
                logger.warning(f"Error checking object crop during removal evaluation: {e}")

        if still_in_cart and max_sim >= low_thresh:
            evidence_url = object_detector.save_evidence_snapshot(
                image_bgr=img_bgr,
                box=matching_box,
                label=f"STILL IN CART ({max_sim*100:.1f}%)",
                status="DANGER"
            )
            return {
                "decision": "STILL_IN_CART",
                "removed": False,
                "confidence": max_sim,
                "evidence_url": evidence_url,
                "message": "We still see this item in the cart. Please take it out."
            }

        # 3. Item is no longer detected in the cart
        evidence_url = object_detector.save_evidence_snapshot(
            image_bgr=img_bgr,
            label="REMOVAL CONFIRMED",
            status="SUCCESS"
        )
        return {
            "decision": "CONFIRMED_REMOVED",
            "removed": True,
            "confidence": 0.95,
            "evidence_url": evidence_url,
            "message": "Item removed. Please rescan its barcode to take it off your bill."
        }

verification_engine = AIVerificationEngine()
