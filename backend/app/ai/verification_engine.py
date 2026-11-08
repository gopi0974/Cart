import base64
import logging
import io
import numpy as np
from PIL import Image
from typing import Dict, Any, Optional, Tuple, Union
from sqlalchemy.orm import Session
from app.config import settings
from app.ai.feature_extractor import feature_extractor
from app.ai.vector_store import VectorStoreMatcher
from app.ai.object_detector import object_detector

logger = logging.getLogger("smartcart.verification")

try:
    import cv2
    HAS_CV2 = True
except Exception:
    cv2 = None
    HAS_CV2 = False

class AIVerificationEngine:
    """
    Multi-modal verification engine coordinating OpenCV frame differencing,
    ONNX INT8 CLIP ViT-B/32 visual embeddings, and pgvector cosine similarity matching.
    """

    @staticmethod
    def _decode_to_cv2(image_data: Any) -> Tuple[np.ndarray, Image.Image]:
        """Convert diverse image payload types (base64 string, bytes, PIL, numpy) to (bgr_ndarray, pil_image)."""
        if isinstance(image_data, str):
            if "," in image_data:
                image_data = image_data.split(",", 1)[1]
            raw_bytes = base64.b64decode(image_data)
            if HAS_CV2:
                nparr = np.frombuffer(raw_bytes, np.uint8)
                img_bgr = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                if img_bgr is None or img_bgr.size == 0:
                    raise ValueError("Could not decode image from base64 buffer.")
                img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
                pil_img = Image.fromarray(img_rgb)
                return img_bgr, pil_img
            else:
                pil_img = Image.open(io.BytesIO(raw_bytes)).convert("RGB")
                img_rgb = np.array(pil_img)
                return img_rgb, pil_img

        elif isinstance(image_data, bytes):
            if HAS_CV2:
                nparr = np.frombuffer(image_data, np.uint8)
                img_bgr = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                if img_bgr is None or img_bgr.size == 0:
                    raise ValueError("Could not decode image from raw bytes.")
                img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
                pil_img = Image.fromarray(img_rgb)
                return img_bgr, pil_img
            else:
                pil_img = Image.open(io.BytesIO(image_data)).convert("RGB")
                img_rgb = np.array(pil_img)
                return img_rgb, pil_img

        elif isinstance(image_data, Image.Image):
            pil_img = image_data.convert("RGB")
            img_rgb = np.array(pil_img)
            if HAS_CV2:
                img_bgr = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2BGR)
                return img_bgr, pil_img
            return img_rgb, pil_img

        elif isinstance(image_data, np.ndarray):
            img_bgr = image_data
            if img_bgr.size == 0:
                raise ValueError("Received empty image ndarray.")
            if HAS_CV2:
                img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
                pil_img = Image.fromarray(img_rgb)
            else:
                pil_img = Image.fromarray(img_bgr)
            return img_bgr, pil_img
        else:
            raise ValueError(f"Unsupported image_data type: {type(image_data)}")

    def evaluate_item_placement(
        self,
        db: Session,
        claimed_barcode: Optional[str],
        image_data: Any,
        ref_background: Optional[np.ndarray] = None,
        crop_box: Optional[Tuple[int, int, int, int]] = None,
        hand_present: bool = False
    ) -> Dict[str, Any]:
        """
        Evaluate physical item placement in cart against claimed barcode using ONNX INT8 CLIP pipeline.
        Returns tiered decision:
          - AUTO_APPROVE: High confidence match for claimed barcode (>= CONFIDENCE_HIGH)
          - RESCAN_PROMPT: Uncertain confidence (between CONFIDENCE_MEDIUM and CONFIDENCE_HIGH)
          - WRONG_ITEM: Recognizes a different enrolled product
          - ESCALATE_ADMIN_REVIEW: Low similarity across all products (< CONFIDENCE_MEDIUM)
          - UNSCANNED_DETECTED: Physical item placed with no pending barcode scan
        """
        img_bgr, pil_full = self._decode_to_cv2(image_data)

        # 1. Locate placed object via background differencing or provided box
        det_box = crop_box
        if det_box is None and ref_background is not None:
            motion_box = object_detector.compute_motion_box(ref_background, img_bgr)
            if motion_box:
                det_box = motion_box

        # 2. Crop detected region or use full frame
        if det_box:
            crop_pil = object_detector.crop_object(img_bgr, det_box)
        else:
            crop_pil = pil_full

        # 3. Generate real ONNX INT8 CLIP 512-dim visual embedding
        query_vector = feature_extractor.get_embedding(crop_pil)

        # 4. Search vector store for top candidates
        top_candidates = VectorStoreMatcher.find_nearest_product(db, query_vector, top_k=3)
        top_match = top_candidates[0] if top_candidates else None

        # Read configurable thresholds
        high_thresh = getattr(settings, "CONFIDENCE_HIGH", 0.75)
        low_thresh = getattr(settings, "CONFIDENCE_MEDIUM", 0.55)

        # Handle Unscanned Item (No pending barcode)
        if not claimed_barcode:
            sim_score = top_match["similarity"] if top_match else 0.0
            evidence_url = object_detector.save_evidence_snapshot(
                image_bgr=img_bgr,
                box=det_box,
                label=f"UNSCANNED: {top_match['product_name'] if top_match else 'Unknown'}",
                status="DANGER"
            )
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
        ref_background: Optional[np.ndarray] = None,
        hand_present: bool = False
    ) -> Dict[str, Any]:
        """
        Evaluate physical removal of item from cart.
        - Verify that the item was actually removed from the cart (not still inside, not covered by hand).
        - If hand is occluding or frame is not stable: prompt to remove hand.
        - If the item is still in the cart: show: 'We still see this item in the cart. Please take it out.'
        """
        if image_data is None:
            return {
                "decision": "CAMERA_FEED_REQUIRED",
                "removed": False,
                "confidence": 0.0,
                "evidence_url": None,
                "message": "Cart camera feed required to verify item removal."
            }

        img_bgr, pil_full = self._decode_to_cv2(image_data)

        # 1. Check for hand occlusion
        if hand_present:
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

        # 2. Check if a motion/item box exists against reference
        motion_box = None
        if ref_background is not None:
            motion_box = object_detector.compute_motion_box(ref_background, img_bgr)

        still_in_cart = False
        max_sim = 0.0
        low_thresh = getattr(settings, "CONFIDENCE_MEDIUM", 0.55)

        if motion_box:
            crop_pil = object_detector.crop_object(img_bgr, motion_box)
            try:
                crop_vec = feature_extractor.get_embedding(crop_pil)
                is_match, sim = VectorStoreMatcher.verify_claimed_barcode(db, target_barcode, crop_vec)
                if (is_match or sim >= low_thresh) and sim > max_sim:
                    max_sim = sim
                    still_in_cart = True
            except Exception as e:
                logger.warning(f"Error checking object crop during removal evaluation: {e}")

        if still_in_cart and max_sim >= low_thresh:
            evidence_url = object_detector.save_evidence_snapshot(
                image_bgr=img_bgr,
                box=motion_box,
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
