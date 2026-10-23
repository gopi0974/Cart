import os
import json
import logging
from datetime import datetime
from typing import List, Dict, Any, Tuple, Optional
import numpy as np
from sqlalchemy.orm import Session
from app.models.product import ProductEmbedding, Product
from app.ai.feature_extractor import VisualFeatureExtractor, MODEL_NAME, MODEL_VERSION, VECTOR_DIM
from app.database import engine
from app.config import settings

logger = logging.getLogger("smartcart.ai.vector_store")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
VECTOR_CACHE_FILE = os.path.join(BASE_DIR, "models_storage", "vector_cache.json")

class VectorStoreMatcher:
    """
    Persistent Vector Store for multi-angle product visual signatures.
    Uses PostgreSQL pgvector when available, and persists an offline disk index
    at models_storage/vector_cache.json that reloads automatically across restarts.
    """

    @classmethod
    def sync_to_disk(cls, db: Session) -> int:
        """Dump all registered embeddings into local persistent disk cache for offline resilience."""
        try:
            records = db.query(ProductEmbedding).all()
            cache_data = []
            for r in records:
                try:
                    vec = r.embedding_vector if isinstance(r.embedding_vector, list) else json.loads(r.embedding_json)
                    cache_data.append({
                        "id": r.id,
                        "product_id": r.product_id,
                        "barcode": r.barcode,
                        "angle_tag": r.angle_tag,
                        "image_path": getattr(r, "image_path", None),
                        "model_name": getattr(r, "model_name", MODEL_NAME),
                        "model_version": getattr(r, "model_version", MODEL_VERSION),
                        "vector_dim": getattr(r, "vector_dim", VECTOR_DIM),
                        "vector": vec,
                        "created_at": r.created_at.isoformat() if r.created_at else None
                    })
                except Exception:
                    continue

            os.makedirs(os.path.dirname(VECTOR_CACHE_FILE), exist_ok=True)
            with open(VECTOR_CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(cache_data, f)
            logger.info(f"Persistent vector disk cache synced with {len(cache_data)} embeddings.")
            return len(cache_data)
        except Exception as e:
            logger.error(f"Failed to sync vector disk cache: {e}")
            return 0

    @classmethod
    def store_embedding(
        cls,
        db: Session,
        product_id: str,
        barcode: str,
        angle_tag: str,
        vector: List[float],
        image_path: Optional[str] = None,
        model_name: str = MODEL_NAME,
        model_version: str = MODEL_VERSION,
        vector_dim: int = VECTOR_DIM,
        commit: bool = True
    ) -> ProductEmbedding:
        """
        Store each embedding with:
        - product barcode
        - image path
        - model name
        - model version
        - vector dimension
        - created time
        """
        emb_json = json.dumps(vector)
        record = ProductEmbedding(
            product_id=product_id,
            barcode=barcode,
            angle_tag=angle_tag,
            embedding_json=emb_json,
            embedding_vector=vector,
            image_path=image_path,
            model_name=model_name,
            model_version=model_version,
            vector_dim=vector_dim,
            created_at=datetime.utcnow()
        )
        db.add(record)
        if commit:
            db.commit()
            db.refresh(record)
            cls.sync_to_disk(db)
        return record

    @classmethod
    def delete_embeddings_for_product(cls, db: Session, product_id: str) -> int:
        """Remove old embeddings for re-scanning or updating a product."""
        count = db.query(ProductEmbedding).filter(ProductEmbedding.product_id == product_id).delete()
        db.commit()
        cls.sync_to_disk(db)
        return count

    @classmethod
    def find_nearest_product(
        cls,
        db: Session,
        query_vector: List[float],
        top_k: int = 3
    ) -> List[Dict[str, Any]]:
        """Search all registered product embeddings and return top-k candidates with similarity score."""
        # 1. Native PostgreSQL pgvector cosine distance search
        if engine.name == "postgresql" and hasattr(ProductEmbedding, "embedding_vector"):
            try:
                nearest = (
                    db.query(ProductEmbedding, ProductEmbedding.embedding_vector.cosine_distance(query_vector).label("distance"))
                    .filter(ProductEmbedding.embedding_vector.isnot(None))
                    .order_by("distance")
                    .limit(top_k * 5)
                    .all()
                )
                if nearest:
                    results = []
                    seen_products = set()
                    for emb, dist in nearest:
                        if emb.product_id in seen_products:
                            continue
                        seen_products.add(emb.product_id)
                        prod = db.query(Product).filter(Product.id == emb.product_id).first()
                        if prod:
                            # pgvector cosine_distance = 1 - cosine_similarity
                            sim = max(0.0, min(1.0, 1.0 - float(dist)))
                            results.append({
                                "product_id": prod.id,
                                "product_name": prod.name,
                                "barcode": prod.barcode,
                                "similarity": round(sim, 4),
                                "matched_angle": emb.angle_tag,
                                "image_path": getattr(emb, "image_path", None)
                            })
                        if len(results) >= top_k:
                            break
                    if results:
                        return results
            except Exception as e:
                logger.warning(f"pgvector query fallback triggered: {e}")

        # 2. Disk cache / in-memory matrix cosine calculation
        embeddings = db.query(ProductEmbedding).all()
        if not embeddings:
            # Try reading from persistent disk cache
            if os.path.exists(VECTOR_CACHE_FILE):
                try:
                    with open(VECTOR_CACHE_FILE, "r", encoding="utf-8") as f:
                        cached = json.load(f)
                    scored = []
                    for c in cached:
                        sim = VisualFeatureExtractor.cosine_similarity(query_vector, c["vector"])
                        scored.append((sim, c["product_id"], c["barcode"], c["angle_tag"], c.get("image_path")))
                    scored.sort(key=lambda x: x[0], reverse=True)
                    results = []
                    seen = set()
                    for sim, pid, bcode, angle, img_p in scored:
                        if pid in seen:
                            continue
                        seen.add(pid)
                        prod = db.query(Product).filter(Product.id == pid).first()
                        prod_name = prod.name if prod else f"Product {bcode}"
                        results.append({
                            "product_id": pid,
                            "product_name": prod_name,
                            "name": prod_name,
                            "barcode": bcode,
                            "similarity": round(float(sim), 4),
                            "matched_angle": angle,
                            "image_path": img_p
                        })
                        if len(results) >= top_k:
                            break
                    return results
                except Exception:
                    pass
            return []

        scored = []
        for emb in embeddings:
            try:
                emb_vec = emb.embedding_vector if isinstance(emb.embedding_vector, list) else json.loads(emb.embedding_json)
                similarity = VisualFeatureExtractor.cosine_similarity(query_vector, emb_vec)
                scored.append((similarity, emb))
            except Exception:
                continue

        scored.sort(key=lambda x: x[0], reverse=True)

        results = []
        seen_products = set()
        for sim, emb in scored:
            if emb.product_id in seen_products:
                continue
            seen_products.add(emb.product_id)

            prod = db.query(Product).filter(Product.id == emb.product_id).first()
            if prod:
                results.append({
                    "product_id": prod.id,
                    "product_name": prod.name,
                    "name": prod.name,
                    "barcode": prod.barcode,
                    "similarity": round(float(sim), 4),
                    "matched_angle": emb.angle_tag,
                    "image_path": getattr(emb, "image_path", None)
                })
            if len(results) >= top_k:
                break

        return results

    @classmethod
    def verify_claimed_barcode(
        cls,
        db: Session,
        claimed_barcode: str,
        query_vector: List[float],
        high_threshold: Optional[float] = None
    ) -> Tuple[bool, float]:
        """
        Verify if the observed item visual embedding matches the barcode claimed by shopper.
        Strict verification: NO fake fallback. If product has no enrolled vectors, returns (False, 0.0).
        """
        threshold = high_threshold if high_threshold is not None else settings.CONFIDENCE_HIGH

        target_embs = db.query(ProductEmbedding).filter(ProductEmbedding.barcode == claimed_barcode).all()
        if not target_embs:
            logger.warning(f"Barcode {claimed_barcode} has no enrolled visual embeddings.")
            return False, 0.0

        best_sim = 0.0
        for emb in target_embs:
            try:
                if isinstance(emb.embedding_vector, list):
                    vec = emb.embedding_vector
                else:
                    vec = json.loads(emb.embedding_json)
                sim = VisualFeatureExtractor.cosine_similarity(query_vector, vec)
                if sim > best_sim:
                    best_sim = sim
            except Exception:
                continue

        is_verified = (best_sim >= threshold)
        return is_verified, round(best_sim, 4)
