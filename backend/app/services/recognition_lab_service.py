import io
import uuid
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any
from PIL import Image
import numpy as np
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.models.product import Product, RecognitionLabSample
from app.services.scan_worker import preprocess_product_image_for_embedding
from app.services.storage_service import storage_service
from app.ai.feature_extractor import get_embedding
from app.ai.vector_store import VectorStoreMatcher

logger = logging.getLogger("smartcart.recognition_lab")


class StorageNotConfiguredError(RuntimeError):
    """Raised when private bucket smartcart-evidence is required but not configured."""


class RecognitionLabService:
    """
    Recognition Lab measurement service for store Admin/Managers.
    Stores sample thumbnails in private Supabase bucket `smartcart-evidence` and
    sample metadata in PostgreSQL `recognition_lab_samples` table (never local disk or
    base64 thumbnails in memory).
    """

    @staticmethod
    def _row_to_dict(row: RecognitionLabSample) -> Dict[str, Any]:
        return {
            "id": row.id,
            "filename": row.filename,
            "source": row.source,
            "expected_barcode": row.expected_barcode,
            "expected_product_name": row.expected_product_name,
            "expected_product_id": row.expected_product_id,
            "angle_label": row.angle_label,
            "image_path": row.image_path,
            "top1_product_name": row.top1_product_name,
            "top1_barcode": row.top1_barcode,
            "top1_score": round(float(row.top1_score or 0.0), 4),
            "top2_product_name": row.top2_product_name,
            "top2_barcode": row.top2_barcode,
            "top2_score": round(float(row.top2_score or 0.0), 4),
            "score_scanned": round(float(row.score_scanned or 0.0), 4),
            "best_other": round(float(row.best_other or 0.0), 4),
            "best_other_product_name": row.best_other_product_name,
            "best_other_barcode": row.best_other_barcode,
            "margin": round(float(row.margin or 0.0), 4),
            "is_correct_top1": bool(row.is_correct_top1),
            "recorded_at": row.recorded_at.strftime("%Y-%m-%d %H:%M:%S") if row.recorded_at else "",
        }

    def evaluate_and_record_photo(
        self,
        db: Session,
        image_pil: Image.Image,
        expected_barcode: str,
        filename: str = "live_photo.jpg",
        angle_label: Optional[str] = "OVERHEAD",
        source: str = "upload"
    ) -> Dict[str, Any]:
        if not settings.DEMO_MODE and not storage_service.is_supabase_configured:
            raise StorageNotConfiguredError(
                "Evidence storage (Supabase smartcart-evidence) is not configured."
            )

        clean_barcode = str(expected_barcode).strip()
        expected_prod = db.query(Product).filter(
            (Product.barcode == clean_barcode) | (Product.barcode.ilike(clean_barcode))
        ).first()

        expected_name = expected_prod.name if expected_prod else f"Product {clean_barcode}"
        expected_id = expected_prod.id if expected_prod else None

        preprocessed_img = preprocess_product_image_for_embedding(image_pil)
        query_vector = get_embedding(preprocessed_img)

        # Upload lightweight 160x160 JPEG thumbnail to smartcart-evidence (never local disk or base64 in memory)
        sample_id = str(uuid.uuid4())[:8]
        thumb_pil = image_pil.copy()
        thumb_pil.thumbnail((160, 160))
        thumb_buf = io.BytesIO()
        thumb_pil.save(thumb_buf, format="JPEG", quality=75)
        image_path = storage_service.upload_bytes(
            object_path=f"recognition_lab/{sample_id}.jpg",
            data=thumb_buf.getvalue(),
            content_type="image/jpeg",
        )
        if not settings.DEMO_MODE and not image_path:
            raise StorageNotConfiguredError(
                "Failed to upload Recognition Lab sample to smartcart-evidence bucket."
            )

        top_matches = VectorStoreMatcher.find_nearest_product(db, query_vector, top_k=10)
        top1 = top_matches[0] if len(top_matches) > 0 else None
        top2 = top_matches[1] if len(top_matches) > 1 else None

        top1_score = float(top1["similarity"]) if top1 else 0.0
        top2_score = float(top2["similarity"]) if top2 else 0.0
        top1_barcode = str(top1["barcode"]).strip() if (top1 and top1.get("barcode")) else None
        top1_name = top1.get("product_name", "No Match") if top1 else "No Match"
        top2_barcode = str(top2["barcode"]).strip() if (top2 and top2.get("barcode")) else None
        top2_name = top2.get("product_name", "None") if top2 else "None"

        _, target_sim = VectorStoreMatcher.verify_claimed_barcode(
            db=db,
            claimed_barcode=clean_barcode,
            query_vector=query_vector
        )
        score_scanned = float(target_sim)

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

        margin = round(score_scanned - best_other_score, 4)
        is_correct = bool(top1 and top1_barcode == clean_barcode)

        row = RecognitionLabSample(
            id=sample_id,
            filename=filename,
            source=source,
            expected_barcode=clean_barcode,
            expected_product_name=expected_name,
            expected_product_id=expected_id,
            angle_label=angle_label or "OVERHEAD",
            image_path=image_path,
            top1_product_name=top1_name,
            top1_barcode=top1_barcode,
            top1_score=round(top1_score, 4),
            top2_product_name=top2_name,
            top2_barcode=top2_barcode,
            top2_score=round(top2_score, 4),
            score_scanned=round(score_scanned, 4),
            best_other=round(best_other_score, 4),
            best_other_product_name=best_other_name,
            best_other_barcode=best_other_barcode,
            margin=margin,
            is_correct_top1=is_correct,
            recorded_at=datetime.utcnow(),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return self._row_to_dict(row)

    def get_analysis_report(self, db: Optional[Session] = None) -> Dict[str, Any]:
        own_db = False
        if db is None:
            if not SessionLocal:
                return self._empty_report()
            db = SessionLocal()
            own_db = True
        try:
            rows = db.query(RecognitionLabSample).order_by(RecognitionLabSample.recorded_at.asc()).all()
            samples = [self._row_to_dict(r) for r in rows]
        finally:
            if own_db:
                db.close()

        total_samples = len(samples)
        if total_samples == 0:
            return self._empty_report()

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

        threshold_list = [0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90]
        margin_list = [0.05, 0.08, 0.10, 0.12, 0.15]
        sensitivity_matrix = []
        true_positives = [s for s in samples if s["is_correct_top1"]]
        true_negatives = [s for s in samples if not s["is_correct_top1"]]
        total_tp = len(true_positives)
        total_tn = len(true_negatives)

        for thresh in threshold_list:
            for m_val in margin_list:
                ta_count = sum(1 for s in true_positives if s["score_scanned"] >= thresh and s["margin"] >= m_val)
                fr_count = sum(1 for s in true_positives if s["score_scanned"] < thresh or s["margin"] < m_val)
                fa_count = sum(1 for s in true_negatives if s["score_scanned"] >= thresh and s["margin"] >= m_val)
                tr_count = sum(1 for s in true_negatives if s["score_scanned"] < thresh or s["margin"] < m_val)

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

        all_expected_names = sorted(list({s["expected_product_name"] for s in samples}))
        all_predicted_names = sorted(list({s["top1_product_name"] for s in samples}))
        all_labels = sorted(list(set(all_expected_names + all_predicted_names)))
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
                {"expected": exp, "predictions": [confusion_table[exp][pred] for pred in all_labels]}
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

    @staticmethod
    def _empty_report() -> Dict[str, Any]:
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

    def delete_sample(self, sample_id: str, db: Optional[Session] = None) -> bool:
        own_db = False
        if db is None:
            if not SessionLocal:
                return False
            db = SessionLocal()
            own_db = True
        try:
            row = db.query(RecognitionLabSample).filter(RecognitionLabSample.id == sample_id).first()
            if not row:
                return False
            if row.image_path:
                storage_service.delete_object(row.image_path)
            db.delete(row)
            db.commit()
            return True
        finally:
            if own_db:
                db.close()

    def reset_all(self, db: Optional[Session] = None) -> int:
        own_db = False
        if db is None:
            if not SessionLocal:
                return 0
            db = SessionLocal()
            own_db = True
        try:
            rows = db.query(RecognitionLabSample).all()
            count = len(rows)
            for r in rows:
                if r.image_path:
                    storage_service.delete_object(r.image_path)
                db.delete(r)
            db.commit()
            return count
        finally:
            if own_db:
                db.close()


recognition_lab_service = RecognitionLabService()
