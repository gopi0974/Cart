import base64
import logging
import io
import json
from datetime import datetime
import numpy as np
from PIL import Image
from typing import Dict, Any, Optional, Tuple
from sqlalchemy.orm import Session
from app.config import settings, CURRENT_PREPROCESSING_VERSION
from app.ai.feature_extractor import feature_extractor
from app.ai.vector_store import VectorStoreMatcher
from app.ai.object_detector import object_detector
from app.models.session import VerificationDecision
from app.models.product import Product
from app.services.scan_worker import preprocess_product_image_for_embedding

logger = logging.getLogger("smartcart.verification")

try:
    import cv2
    HAS_CV2 = True
except Exception:
    cv2 = None
    HAS_CV2 = False


class AIVerificationEngine:
    """
    Multi-modal verification engine coordinating OpenCV background differencing,
    identical 224x224 crop preparation (sharing enrollment pipeline), ONNX INT8 CLIP
    visual embeddings, and pgvector/cosine similarity candidate ranking.
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
                img_bgr = cv2.cvtColor(img_rgb, cv2.COLOR_BGR2RGB)
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
        hand_present: bool = False,
        face_present: bool = False,
        cart_id: Optional[str] = None,
        session_id: Optional[str] = None,
        item_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Evaluate physical item placement in cart against claimed barcode using ONNX INT8 CLIP pipeline.
        Tiers & Decision Rules:
          - FACE ON PACKAGING: Face detected in stationary object. Frame withheld, cannot verify.
          - AUTO_APPROVE: Top match == claimed product, similarity >= HIGH, and clear gap to competing second product.
          - REPOSITION_PROMPT: Scanned item recognized but similarity is between LOW and HIGH.
          - WRONG_ITEM: Different catalog product recognized with similarity >= LOW.
          - ESCALATE_ADMIN_REVIEW: Similarity < LOW, multi-object clutter, or low confidence across all products.
          - UNSCANNED_DETECTED: Physical item placed with no pending barcode scan.
        """
        # Read configurable thresholds
        high_thresh = getattr(settings, "CONFIDENCE_HIGH", 0.85)
        low_thresh = getattr(settings, "CONFIDENCE_LOW", 0.65)

        # Scanned product info lookup
        scanned_product = None
        if claimed_barcode and db:
            scanned_product = db.query(Product).filter(Product.barcode == claimed_barcode).first()
        scanned_product_name = scanned_product.name if scanned_product else (f"Barcode {claimed_barcode}" if claimed_barcode else None)

        # 1. Privacy & Hand Gate: Hand or Face presence
        if hand_present:
            decision = "HAND_IN_CART"
            message = "We see a hand in the cart. Please remove your hand so the camera can verify."
            # Never save crop, never embed, never store evidence
            return {
                "decision": decision,
                "status": "WARNING",
                "warning_reason": "HAND_DETECTED",
                "confidence": 0.0,
                "top_match": None,
                "top_candidates": [],
                "evidence_url": None,
                "message": message
            }

        if face_present:
            decision = "FACE_DETECTED_WITHHELD"
            message = "We can't check this item. Please ask staff"
            self._record_decision(
                db=db,
                cart_id=cart_id,
                session_id=session_id,
                item_id=item_id,
                decision=decision,
                scanned_barcode=claimed_barcode,
                scanned_product_name=scanned_product_name,
                matched_product_id=None,
                matched_product_name=None,
                top1_score=0.0,
                top2_score=0.0,
                threshold_high=high_thresh,
                threshold_low=low_thresh,
                evidence_path=None,
                details={"reason": "frame withheld (face detected)"}
            )
            return {
                "decision": decision,
                "status": "WARNING",
                "warning_reason": "FACE_DETECTED",
                "confidence": 0.0,
                "top_match": None,
                "top_candidates": [],
                "evidence_url": None,
                "message": message
            }

        img_bgr, pil_full = self._decode_to_cv2(image_data)

        # 2. Locate placed object via background differencing against empty-cart reference
        det_box = crop_box
        if det_box is None and ref_background is not None:
            motion_box = object_detector.compute_motion_box(ref_background, img_bgr)
            if motion_box:
                det_box = motion_box

        # 3. Crop detected product region (product area only, never wide frames)
        if det_box:
            crop_pil = object_detector.crop_object(img_bgr, det_box)
        else:
            # Fallback: crop central region to prevent full frame storage
            # CRITICAL PRIVACY RULE: Fallback central crop can ONLY be used when NO hand and NO face is present
            if hand_present or face_present:
                return {
                    "decision": "HAND_IN_CART" if hand_present else "FACE_DETECTED_WITHHELD",
                    "status": "WARNING",
                    "warning_reason": "HAND_DETECTED" if hand_present else "FACE_DETECTED",
                    "confidence": 0.0,
                    "top_match": None,
                    "top_candidates": [],
                    "evidence_url": None,
                    "message": "We see a hand in the cart. Please remove your hand so the camera can verify." if hand_present else "We can't check this item. Please ask staff"
                }
            w, h = pil_full.size
            crop_pil = pil_full.crop((int(w * 0.2), int(h * 0.2), int(w * 0.8), int(h * 0.8)))

        # 4. PREPARE CROP WITH EXACTLY THE SAME FUNCTION THAT ENROLLMENT USES
        # scan_worker.preprocess_product_image_for_embedding is the single canonical preparation routine
        # and applies the should_apply_grabcut rule identically on any crop
        preprocessed_crop = preprocess_product_image_for_embedding(crop_pil)

        # 5. Extract 512-dim embedding with ONNX INT8 CLIP ViT-B/32
        query_vector = feature_extractor.get_embedding(preprocessed_crop)

        # 6. Search stored product vectors (cosine similarity, top 3)
        top_candidates = VectorStoreMatcher.find_nearest_product(db, query_vector, top_k=3)
        top1 = top_candidates[0] if len(top_candidates) > 0 else None
        top2 = top_candidates[1] if len(top_candidates) > 1 else None
        top1_score = float(top1["similarity"]) if top1 else 0.0
        top2_score = float(top2["similarity"]) if top2 else 0.0

        # Save private evidence crop (product area only)
        evidence_url = object_detector.save_evidence_snapshot(
            image_bgr=img_bgr,
            box=det_box,
            label=f"{top1['product_name'] if top1 else 'Item'} ({top1_score*100:.1f}%)",
            status="SUCCESS" if top1_score >= high_thresh else "UNCERTAIN",
            hand_present=hand_present,
            face_present=face_present
        )

        # CASE A: No PENDING item scanned (Unscanned item placed in cart)
        if not claimed_barcode:
            decision = "UNSCANNED_DETECTED"
            msg = "We noticed an item was placed that wasn't scanned. Please scan its barcode."
            self._record_decision(
                db=db,
                cart_id=cart_id,
                session_id=session_id,
                item_id=item_id,
                decision=decision,
                scanned_barcode=None,
                scanned_product_name=None,
                matched_product_id=top1["id"] if top1 else None,
                matched_product_name=top1["product_name"] if top1 else None,
                top1_score=top1_score,
                top2_score=top2_score,
                threshold_high=high_thresh,
                threshold_low=low_thresh,
                evidence_path=evidence_url,
                details={"top_candidates": top_candidates}
            )
            return {
                "decision": decision,
                "status": "WARNING",
                "warning_reason": "UNSCANNED",
                "confidence": top1_score,
                "top_match": top1,
                "top_candidates": top_candidates,
                "evidence_url": evidence_url,
                "message": msg
            }

        # CASE B: PENDING item exists (Shopper scanned a barcode)
        top1_matches_claimed = (top1 is not None and top1.get("barcode") == claimed_barcode)
        is_exact_match, sim_exact = VectorStoreMatcher.verify_claimed_barcode(db, claimed_barcode, query_vector)
        is_claimed_match = top1_matches_claimed or is_exact_match
        best_claimed_sim = max(top1_score if top1_matches_claimed else 0.0, sim_exact)

        # Clear gap check: second match is either the same product (different 360 angle) or sufficiently below top1
        competing_diff_product = (top2 is not None and top2.get("barcode") != claimed_barcode)
        gap = (top1_score - top2_score) if competing_diff_product else 0.10

        # Branch 1: Top match == claimed product & similarity >= HIGH & clear gap
        if is_claimed_match and best_claimed_sim >= high_thresh and gap >= 0.02:
            decision = "AUTO_APPROVE"
            status = "VERIFIED"
            msg = f"AI verified '{scanned_product_name}' with {best_claimed_sim*100:.1f}% confidence."
            warning_reason = None

        # Branch 2: Scanned product matches, but similarity is between LOW and HIGH -> Reposition Prompt
        elif is_claimed_match and best_claimed_sim >= low_thresh:
            decision = "REPOSITION_PROMPT"
            status = "WARNING"
            warning_reason = "REPOSITION"
            msg = f"Uncertain confidence ({best_claimed_sim*100:.1f}%). Please reposition the item or show its label."

        # Branch 3: A DIFFERENT catalog product matches above LOW threshold -> WRONG ITEM
        elif top1 and not is_claimed_match and top1_score >= low_thresh:
            decision = "WRONG_ITEM"
            status = "WARNING"
            warning_reason = "MISMATCH"
            wrong_name = top1.get("product_name") or "Different Item"
            msg = f"Wrong item placed: Camera observed '{wrong_name}', but barcode was scanned for '{scanned_product_name}'. Take this out or scan its barcode."

        # Branch 4: Low confidence across all products (< LOW threshold) -> Escalate to Admin Review
        else:
            decision = "ESCALATE_ADMIN_REVIEW"
            status = "WARNING"
            warning_reason = "LOW_CONFIDENCE"
            msg = f"Visual match is low ({best_claimed_sim*100:.1f}%). Forwarded to store staff review queue."

        # Record immutable verification decision audit entry
        self._record_decision(
            db=db,
            cart_id=cart_id,
            session_id=session_id,
            item_id=item_id,
            decision=decision,
            scanned_barcode=claimed_barcode,
            scanned_product_name=scanned_product_name,
            matched_product_id=top1["id"] if top1 else None,
            matched_product_name=top1["product_name"] if top1 else None,
            top1_score=top1_score,
            top2_score=top2_score,
            threshold_high=high_thresh,
            threshold_low=low_thresh,
            evidence_path=evidence_url,
            details={"top_candidates": top_candidates, "gap": round(gap, 4)}
        )

        return {
            "decision": decision,
            "status": status,
            "warning_reason": warning_reason,
            "confidence": best_claimed_sim,
            "top1_score": top1_score,
            "top2_score": top2_score,
            "top_match": top1,
            "top_candidates": top_candidates,
            "evidence_url": evidence_url,
            "message": msg
        }

    def evaluate_item_removal(
        self,
        db: Session,
        target_barcode: str,
        image_data: Optional[Any] = None,
        ref_background: Optional[np.ndarray] = None,
        hand_present: bool = False,
        cart_id: Optional[str] = None,
        session_id: Optional[str] = None,
        item_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Evaluate physical removal of item from cart.
        - Verify that the item was actually removed from the cart (not still inside, not covered by hand).
        - If hand is occluding or frame is not stable: prompt to remove hand.
        - If the item is still in the cart: show: 'We still see this item in the cart. Please take it out.'
        - When departure is confirmed: advances to REMOVED_PENDING_RESCAN.
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

        # 2. Check if the target item is still present in the cart
        motion_box = None
        if ref_background is not None:
            motion_box = object_detector.compute_motion_box(ref_background, img_bgr)

        still_in_cart = False
        max_sim = 0.0
        low_thresh = getattr(settings, "CONFIDENCE_LOW", 0.65)

        if motion_box:
            crop_pil = object_detector.crop_object(img_bgr, motion_box)
            try:
                preproc = preprocess_product_image_for_embedding(crop_pil)
                crop_vec = feature_extractor.get_embedding(preproc)
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
                status="DANGER",
                hand_present=hand_present,
                face_present=False
            )
            return {
                "decision": "STILL_IN_CART",
                "removed": False,
                "confidence": max_sim,
                "evidence_url": evidence_url,
                "message": "We still see this item in the cart. Please take it out."
            }

        # 3. Item is no longer detected in the cart -> Confirmed Removed
        evidence_url = object_detector.save_evidence_snapshot(
            image_bgr=img_bgr,
            label="REMOVAL CONFIRMED",
            status="SUCCESS",
            hand_present=hand_present,
            face_present=False
        )

        self._record_decision(
            db=db,
            cart_id=cart_id,
            session_id=session_id,
            item_id=item_id,
            decision="CONFIRMED_REMOVED",
            scanned_barcode=target_barcode,
            scanned_product_name=None,
            matched_product_id=None,
            matched_product_name=None,
            top1_score=0.95,
            top2_score=0.0,
            threshold_high=getattr(settings, "CONFIDENCE_HIGH", 0.85),
            threshold_low=low_thresh,
            evidence_path=evidence_url,
            details={"action": "ITEM_REMOVAL"}
        )

        return {
            "decision": "CONFIRMED_REMOVED",
            "removed": True,
            "confidence": 0.95,
            "evidence_url": evidence_url,
            "message": "Rescan the barcode to remove this item"
        }

    def _record_decision(
        self,
        db: Optional[Session],
        cart_id: Optional[str],
        session_id: Optional[str],
        item_id: Optional[str],
        decision: str,
        scanned_barcode: Optional[str],
        scanned_product_name: Optional[str],
        matched_product_id: Optional[str],
        matched_product_name: Optional[str],
        top1_score: Optional[float],
        top2_score: Optional[float],
        threshold_high: float,
        threshold_low: float,
        evidence_path: Optional[str],
        details: Optional[Dict[str, Any]] = None,
        preprocessing_version: str = CURRENT_PREPROCESSING_VERSION
    ) -> None:
        """Persist structured decision record with exact scores, thresholds, and evidence."""
        if not db:
            return
        try:
            record = VerificationDecision(
                cart_id=cart_id or "unknown",
                session_id=session_id,
                item_id=item_id,
                decision=decision,
                scanned_barcode=scanned_barcode,
                scanned_product_name=scanned_product_name,
                matched_product_id=matched_product_id,
                matched_product_name=matched_product_name,
                top1_score=top1_score,
                top2_score=top2_score,
                threshold_high=threshold_high,
                threshold_low=threshold_low,
                evidence_path=evidence_path,
                preprocessing_version=preprocessing_version,
                details_json=json.dumps(details or {}),
                created_at=datetime.utcnow()
            )
            db.add(record)
            db.commit()
        except Exception as e:
            logger.warning(f"Failed to persist VerificationDecision: {e}")


verification_engine = AIVerificationEngine()
