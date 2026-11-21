import io
import json
import base64
import uuid
import logging
import threading
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any
from PIL import Image
import numpy as np
from sqlalchemy.orm import Session

from app.config import settings
from app.models.product import Product
from app.services.scan_worker import preprocess_product_image_for_embedding
from app.ai.feature_extractor import get_embedding
from app.ai.vector_store import VectorStoreMatcher

logger = logging.getLogger("smartcart.recognition_lab")


class RecognitionLabService:
    """
    Recognition Lab measurement service for store Admin/Managers.
    Evaluates real user test photos (from uploads or /cart-device webcam captures)
    through the identical cart camera embedding pipeline.
    
    Generates empirical metrics:
    - Expected vs top-1 & top-2 scores
    - score_scanned, best_other, and margin
    - Per-product classification accuracy
    - False Accept and False Reject rates across thresholds (0.50 - 0.90) and margins (0.05 - 0.15)
    - Empirical confusion matrix
    
    Rule: Never uses synthetic data. All evaluations reflect real user photos.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._samples: List[Dict[str, Any]] = []
        self._storage_dir: Path = settings.UPLOADS_DIR / "recognition_lab"
        self._storage_file: Path = self._storage_dir / "samples.json"
        self._load_persisted_samples()

    def _load_persisted_samples(self) -> None:
        try:
            self._storage_dir.mkdir(parents=True, exist_ok=True)
            if self._storage_file.exists():
                with open(self._storage_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        self._samples = data
                        logger.info(f"Loaded {len(self._samples)} persisted Recognition Lab samples.")
        except Exception as e:
            logger.warning(f"Could not load persisted Recognition Lab samples: {e}")
            self._samples = []

    def _persist_samples(self) -> None:
        try:
            self._storage_dir.mkdir(parents=True, exist_ok=True)
            with open(self._storage_file, "w", encoding="utf-8") as f:
                json.dump(self._samples, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to persist Recognition Lab samples to disk: {e}")

    def evaluate_and_record_photo(
        self,
        db: Session,
        image_pil: Image.Image,
        expected_barcode: str,
        filename: str = "live_photo.jpg",
        angle_label: Optional[str] = "OVERHEAD",
        source: str = "upload"
    ) -> Dict[str, Any]:
        """
        Evaluates a real photo crop through the exact cart camera pipeline.
        Preprocesses with standard neutral grey GrabCut composite on 320px,
        extracts ONNX INT8 CLIP ViT-B/32 embedding, queries vector store,
        and computes score_scanned, best_other, margin, and candidate rankings.
        """
        clean_barcode = str(expected_barcode).strip()
        expected_prod = db.query(Product).filter(
            (Product.barcode == clean_barcode) | (Product.barcode.ilike(clean_barcode))
        ).first()

        expected_name = expected_prod.name if expected_prod else f"Product {clean_barcode}"
        expected_id = expected_prod.id if expected_prod else None

        # 1. Run exact cart camera preprocessing (GrabCut on 320px, composited on neutral grey 128,128,128)
        preprocessed_img = preprocess_product_image_for_embedding(image_pil)

        # 2. Extract real ONNX INT8 CLIP ViT-B/32 vector embedding
        query_vector = get_embedding(preprocessed_img)

        # 3. Create lightweight thumbnail for instant display in report (80x80 max)
        thumb_pil = image_pil.copy()
        thumb_pil.thumbnail((80, 80))
        thumb_buf = io.BytesIO()
        thumb_pil.save(thumb_buf, format="JPEG", quality=75)
        thumbnail_url = "data:image/jpeg;base64," + base64.b64encode(thumb_buf.getvalue()).decode("utf-8")

        # 4. Search nearest products in persistent catalog vector store
        top_matches = VectorStoreMatcher.find_nearest_product(db, query_vector, top_k=10)

        top1 = top_matches[0] if len(top_matches) > 0 else None
        top2 = top_matches[1] if len(top_matches) > 1 else None

        top1_score = float(top1["similarity"]) if top1 else 0.0
        top2_score = float(top2["similarity"]) if top2 else 0.0
        top1_barcode = str(top1["barcode"]).strip() if (top1 and top1.get("barcode")) else None
        top1_name = top1.get("product_name", "No Match") if top1 else "No Match"
        top2_barcode = str(top2["barcode"]).strip() if (top2 and top2.get("barcode")) else None
        top2_name = top2.get("product_name", "None") if top2 else "None"

        # 5. Determine similarity to the expected (scanned) product
        is_target_match, target_sim = VectorStoreMatcher.verify_claimed_barcode(
            db=db,
            claimed_barcode=clean_barcode,
            query_vector=query_vector
        )
        score_scanned = float(target_sim)

        # 6. Find best other product (highest similarity among products other than expected_barcode)
        best_other_score = 0.0
        best_other_name = "None"
        best_other_barcode = None

        for match in top_matches:
            m_barcode = str(match.get("barcode", "")).strip()
            if m_barcode != clean_barcode:
                best_other_score = float(match.get("similarity", 0.0))
                best_other_name = match.get("product_name", "Other")
                best_other_barcode = m_barcode
                break

        # 7. Compute margin: difference between scanned product score and best other product score
        margin = round(score_scanned - best_other_score, 4)

        # 8. Check if Top-1 match is the expected product
        is_correct = bool(top1 and top1_barcode == clean_barcode)

        sample_id = str(uuid.uuid4())[:8]
        sample_record = {
            "id": sample_id,
            "filename": filename,
            "source": source,
            "expected_barcode": clean_barcode,
            "expected_product_name": expected_name,
            "expected_product_id": expected_id,
            "angle_label": angle_label or "OVERHEAD",
            "top1_product_name": top1_name,
            "top1_barcode": top1_barcode,
            "top1_score": round(top1_score, 4),
            "top2_product_name": top2_name,
            "top2_barcode": top2_barcode,
            "top2_score": round(top2_score, 4),
            "score_scanned": round(score_scanned, 4),
            "best_other": round(best_other_score, 4),
            "best_other_product_name": best_other_name,
            "best_other_barcode": best_other_barcode,
            "margin": margin,
            "is_correct_top1": is_correct,
            "thumbnail_url": thumbnail_url,
            "recorded_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        }

        with self._lock:
            self._samples.append(sample_record)
            self._persist_samples()

        return sample_record

    def get_analysis_report(self) -> Dict[str, Any]:
        """
        Computes comprehensive recognition performance analysis across all recorded test photos:
        - Per-product accuracy, mean score, and mean margin
        - Threshold & Margin sensitivity matrix (thresholds 0.50 to 0.90, margins 0.05 to 0.15)
        - Confusion table mapping expected product to predicted top-1 product
        - Explicit statement of data origin (real photos, no synthetic data)
        """
        with self._lock:
            samples = list(self._samples)

        total_samples = len(samples)
        if total_samples == 0:
            return {
                "total_samples": 0,
                "unique_products_count": 0,
                "overall_top1_accuracy": 0.0,
                "samples": [],
                "per_product_accuracy": [],
                "sensitivity_matrix": [],
                "confusion_matrix": {"labels": [], "matrix": []},
                "data_origin_statement": (
                    "All metrics, scores, and confusion statistics are derived directly "
                    "from real user-uploaded or webcam-captured photos evaluated via the "
                    "cart camera ONNX ViT-B/32 pipeline. No synthetic data is used."
                )
            }

        # 1. Per-Product Accuracy Breakdown
        products_map: Dict[str, Dict[str, Any]] = {}
        for s in samples:
            b = s["expected_barcode"]
            if b not in products_map:
                products_map[b] = {
                    "barcode": b,
                    "product_name": s["expected_product_name"],
                    "total": 0,
                    "correct": 0,
                    "scores_scanned": [],
                    "margins": []
                }
            entry = products_map[b]
            entry["total"] += 1
            if s["is_correct_top1"]:
                entry["correct"] += 1
            entry["scores_scanned"].append(s["score_scanned"])
            entry["margins"].append(s["margin"])

        per_product_stats = []
        for b, data in products_map.items():
            tot = data["total"]
            corr = data["correct"]
            acc = round((corr / tot) * 100.0, 1) if tot > 0 else 0.0
            avg_score = round(float(np.mean(data["scores_scanned"])), 4) if data["scores_scanned"] else 0.0
            avg_margin = round(float(np.mean(data["margins"])), 4) if data["margins"] else 0.0
            per_product_stats.append({
                "barcode": b,
                "product_name": data["product_name"],
                "sample_count": tot,
                "correct_top1_count": corr,
                "accuracy_percent": acc,
                "avg_score_scanned": avg_score,
                "avg_margin": avg_margin
            })

        total_correct = sum(1 for s in samples if s["is_correct_top1"])
        overall_top1_acc = round((total_correct / total_samples) * 100.0, 1)

        # 2. Threshold (0.50 to 0.90) and Margin (0.05 to 0.15) Sensitivity Matrix
        threshold_list = [0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90]
        margin_list = [0.05, 0.08, 0.10, 0.12, 0.15]
        sensitivity_matrix = []

        for thresh in threshold_list:
            for m_val in margin_list:
                # Rule: A placement is accepted if score_scanned >= thresh AND margin >= m_val
                # True Accept: is_correct_top1 is True, and accepted
                # False Reject: is_correct_top1 is True, but score_scanned < thresh or margin < m_val
                # False Accept: is_correct_top1 is False, but scored >= thresh and margin >= m_val
                # True Reject: is_correct_top1 is False, and rejected
                true_positives = [s for s in samples if s["is_correct_top1"]]
                true_negatives = [s for s in samples if not s["is_correct_top1"]]

                ta_count = sum(1 for s in true_positives if s["score_scanned"] >= thresh and s["margin"] >= m_val)
                fr_count = sum(1 for s in true_positives if s["score_scanned"] < thresh or s["margin"] < m_val)

                fa_count = sum(1 for s in true_negatives if s["score_scanned"] >= thresh and s["margin"] >= m_val)
                tr_count = sum(1 for s in true_negatives if s["score_scanned"] < thresh or s["margin"] < m_val)

                total_tp = len(true_positives)
                total_tn = len(true_negatives)

                fr_rate = round((fr_count / total_tp) * 100.0, 1) if total_tp > 0 else 0.0
                fa_rate = round((fa_count / total_tn) * 100.0, 1) if total_tn > 0 else 0.0

                sensitivity_matrix.append({
                    "threshold": thresh,
                    "margin": m_val,
                    "true_accepts": ta_count,
                    "false_rejects": fr_count,
                    "false_reject_rate": fr_rate,
                    "false_accepts": fa_count,
                    "false_accept_rate": fa_rate,
                    "true_rejects": tr_count,
                    "total_samples_evaluated": total_samples
                })

        # 3. Confusion Matrix: Rows = Expected Product, Columns = Predicted Top-1 Product
        all_expected_names = sorted(list({s["expected_product_name"] for s in samples}))
        all_predicted_names = sorted(list({s["top1_product_name"] for s in samples}))
        all_labels = sorted(list(set(all_expected_names + all_predicted_names)))

        # Build 2D frequency table
        confusion_table: Dict[str, Dict[str, int]] = {
            exp: {pred: 0 for pred in all_labels} for exp in all_labels
        }

        for s in samples:
            exp = s["expected_product_name"]
            pred = s["top1_product_name"]
            if exp in confusion_table and pred in confusion_table[exp]:
                confusion_table[exp][pred] += 1

        confusion_matrix_result = {
            "labels": all_labels,
            "matrix": [
                {
                    "expected": exp,
                    "predictions": [confusion_table[exp][pred] for pred in all_labels]
                }
                for exp in all_labels
            ]
        }

        return {
            "total_samples": total_samples,
            "unique_products_count": len(per_product_stats),
            "overall_top1_accuracy": overall_top1_acc,
            "samples": samples,
            "per_product_accuracy": per_product_stats,
            "sensitivity_matrix": sensitivity_matrix,
            "confusion_matrix": confusion_matrix_result,
            "data_origin_statement": (
                "All metrics, scores, and confusion statistics are derived directly "
                "from real user-uploaded or webcam-captured photos evaluated via the "
                "cart camera ONNX ViT-B/32 pipeline. No synthetic data is used."
            )
        }

    def delete_sample(self, sample_id: str) -> bool:
        with self._lock:
            original_len = len(self._samples)
            self._samples = [s for s in self._samples if s.get("id") != sample_id]
            if len(self._samples) != original_len:
                self._persist_samples()
                return True
            return False

    def reset_all(self) -> int:
        with self._lock:
            count = len(self._samples)
            self._samples.clear()
            self._persist_samples()
            return count


# Singleton instance
recognition_lab_service = RecognitionLabService()
