from typing import Dict, Any, Optional
from sqlalchemy.orm import Session
from app.config import settings
from app.ai.feature_extractor import feature_extractor
from app.ai.vector_store import VectorStoreMatcher

class AIVerificationEngine:
    """
    Multi-modal verification engine coordinating motion detection, visual embedding extraction,
    and multi-tier confidence classification.
    """
    @staticmethod
    def evaluate_item_placement(
        db: Session,
        claimed_barcode: Optional[str],
        image_data: Any
    ) -> Dict[str, Any]:
        """
        Evaluate physical item placement in cart against claimed barcode.
        Returns tiered decision: AUTO_APPROVE | RESCAN_PROMPT | ESCALATE_ADMIN_REVIEW
        """
        query_vector = feature_extractor.extract_embedding(image_data)
        top_candidates = VectorStoreMatcher.find_nearest_product(db, query_vector, top_k=3)

        if not claimed_barcode:
            # Unscanned addition
            best_match = top_candidates[0] if top_candidates else None
            return {
                "decision": "UNSCANNED_DETECTED",
                "confidence": best_match["similarity"] if best_match else 0.90,
                "detected_product": best_match,
                "message": "Physical item entered cart without prior barcode scan."
            }

        # Check match with claimed barcode
        is_match, similarity = VectorStoreMatcher.verify_claimed_barcode(db, claimed_barcode, query_vector)

        if similarity >= settings.CONFIDENCE_HIGH:
            return {
                "decision": "AUTO_APPROVE",
                "confidence": similarity,
                "status": "VERIFIED",
                "message": "AI confirmed physical item matches scanned barcode."
            }
        elif similarity >= settings.CONFIDENCE_MEDIUM:
            return {
                "decision": "RESCAN_PROMPT",
                "confidence": similarity,
                "status": "WARNING_MISMATCH",
                "message": "Item appearance has low confidence. Please rescan barcode clearly."
            }
        else:
            return {
                "decision": "ESCALATE_ADMIN_REVIEW",
                "confidence": similarity,
                "status": "WARNING_MISMATCH",
                "message": "Discrepancy detected. Forwarded to store staff review queue."
            }

verification_engine = AIVerificationEngine()
