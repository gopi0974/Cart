import os
import io
import json
import base64
import uuid
import time
import asyncio
import logging
from typing import List, Dict, Any, Tuple
import numpy as np
import cv2
from PIL import Image, ImageEnhance, ImageFilter
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.models.product import Product, ProductImage, ProductEmbedding
from app.models.scan_job import ScanJob
from app.ai.feature_extractor import (
    get_embeddings_batch,
    get_embedding,
    MODEL_NAME,
    MODEL_VERSION,
    VECTOR_DIM
)
from app.ai.vector_store import VectorStoreMatcher
from app.services.storage_service import storage_service
from app.utils.cache import catalog_cache
from app.utils.sanitization import sanitize_secrets

logger = logging.getLogger("smartcart.scan_worker")

# Process strictly ONE 360-scan job at a time to prevent CPU / memory thrashing on Render
_scan_job_lock = asyncio.Lock()
_cancelled_job_ids = set()


def cancel_job(job_id: str):
    """Signals an active or queued job to cancel immediately."""
    _cancelled_job_ids.add(job_id)


def _downscale_and_remove_background(pil_img: Image.Image) -> Image.Image:
    """
    Downscales frame before running GrabCut background segmentation.
    Downscaling to 224x224 first dramatically reduces memory usage and execution time.
    """
    try:
        # Downscale first
        img_224 = pil_img.resize((224, 224), Image.BILINEAR)
        np_img = np.array(img_224.convert("RGB"))
        bgr = cv2.cvtColor(np_img, cv2.COLOR_RGB2BGR)
        h, w = bgr.shape[:2]
        if h < 20 or w < 20:
            return img_224

        mask = np.zeros((h, w), np.uint8)
        rect = (max(1, int(w * 0.08)), max(1, int(h * 0.08)), max(1, int(w * 0.84)), max(1, int(h * 0.84)))
        bgdModel = np.zeros((1, 65), np.float64)
        fgdModel = np.zeros((1, 65), np.float64)
        cv2.grabCut(bgr, mask, rect, bgdModel, fgdModel, 1, cv2.GC_INIT_WITH_RECT)
        mask2 = np.where((mask == 2) | (mask == 0), 0, 1).astype("uint8")
        bgr_fg = bgr * mask2[:, :, np.newaxis] + (1 - mask2[:, :, np.newaxis]) * 240
        return Image.fromarray(cv2.cvtColor(bgr_fg.astype(np.uint8), cv2.COLOR_BGR2RGB))
    except Exception as e:
        logger.warning(f"Background removal warning: {e}. Using resized frame.")
        return pil_img.resize((224, 224), Image.BILINEAR)


def _generate_variants_224(base_224: Image.Image, matted_224: Image.Image) -> List[Tuple[str, Image.Image]]:
    """Produce realistic variations all resized to 224x224."""
    w, h = base_224.size
    variants = [
        ("BASE", base_224),
        ("MATTED", matted_224),
        ("BRIGHT_HIGH", ImageEnhance.Brightness(base_224).enhance(1.15)),
        ("BRIGHT_LOW", ImageEnhance.Brightness(base_224).enhance(0.85)),
        ("ROT_POS", base_224.rotate(10, resample=Image.BILINEAR, fillcolor=(240, 240, 240))),
        ("ROT_NEG", base_224.rotate(-10, resample=Image.BILINEAR, fillcolor=(240, 240, 240))),
        ("BLUR", base_224.filter(ImageFilter.GaussianBlur(radius=0.8))),
        ("CROP_ZOOM", base_224.crop((int(w * 0.06), int(h * 0.06), int(w * 0.94), int(h * 0.94))).resize((224, 224), Image.BILINEAR)),
    ]
    return variants


async def _execute_scan_job_internal(job_id: str):
    """Internal processing pipeline with stage updates, batch embedding, and atomic single-transaction commit."""
    db: Session = SessionLocal()
    try:
        job = db.query(ScanJob).filter(ScanJob.id == job_id).first()
        if not job:
            logger.error(f"ScanJob {job_id} not found.")
            return

        # Check early cancellation
        if job_id in _cancelled_job_ids or job.status == "CANCELLED":
            job.status = "CANCELLED"
            job.stage = "CANCELLED"
            job.stage_message = "Scan processing was cancelled by user."
            db.commit()
            _cancelled_job_ids.discard(job_id)
            logger.info(f"ScanJob {job_id} cancelled before processing began.")
            return

        product = db.query(Product).filter(Product.id == job.product_id).first()
        if not product:
            job.status = "FAILED"
            job.stage = "FAILED"
            job.error = "Target product not found."
            job.stage_message = "Failed: Target product not found."
            db.commit()
            return

        frame_data: List[Dict[str, str]] = []
        if job.frame_paths_json:
            try:
                frame_data = json.loads(job.frame_paths_json)
            except Exception:
                frame_data = []

        if not frame_data:
            job.status = "FAILED"
            job.stage = "FAILED"
            job.error = "No saved frames available for this job."
            job.stage_message = "Failed: No saved frames available."
            db.commit()
            return

        total_frames = len(frame_data)
        job.status = "PROCESSING"
        job.stage = "SAVING_FRAMES"
        job.stage_message = f"Frames verified ({total_frames} frames)."
        job.done = 0
        job.total = total_frames
        job.error = None
        db.commit()

        # Step 2: Downscale to 224x224 and run background removal
        job.stage = "REMOVING_BACKGROUND"
        all_variants: List[Tuple[str, str, Image.Image, str]] = []  # (angle_tag, variant_tag, pil_img, frame_ref)
        primary_frame_url = None

        for idx, item in enumerate(frame_data):
            # Check cancellation between frames
            if job_id in _cancelled_job_ids:
                job.status = "CANCELLED"
                job.stage = "CANCELLED"
                job.stage_message = "Scan processing was cancelled by user."
                db.commit()
                _cancelled_job_ids.discard(job_id)
                logger.info(f"ScanJob {job_id} cancelled during frame processing.")
                return

            angle_tag = item["angle_tag"]
            frame_ref = item["frame_ref"]

            job.stage_message = f"Removing background {idx + 1}/{total_frames}"
            job.done = idx + 1
            db.commit()

            pil_img = storage_service.load_frame_image(frame_ref)

            # Generate thumbnail for primary image
            if primary_frame_url is None or angle_tag.upper() == "FRONT":
                thumb = pil_img.copy()
                thumb.thumbnail((400, 400))
                thumb_buf = io.BytesIO()
                thumb.save(thumb_buf, format="JPEG", quality=80)
                primary_frame_url = f"data:image/jpeg;base64,{base64.b64encode(thumb_buf.getvalue()).decode('utf-8')}"

            # Downscale frame to 224x224 first, then remove background
            base_224 = pil_img.resize((224, 224), Image.BILINEAR)
            matted_224 = _downscale_and_remove_background(pil_img)

            variants = _generate_variants_224(base_224, matted_224)
            for v_tag, v_img in variants:
                all_variants.append((angle_tag, v_tag, v_img, frame_ref))

            # Small yield to let event loop breathe
            await asyncio.sleep(0.01)

        # Cap vectors at 100 per product as required
        MAX_VECTORS = 100
        if len(all_variants) > MAX_VECTORS:
            step = len(all_variants) / MAX_VECTORS
            selected_indices = [int(i * step) for i in range(MAX_VECTORS)]
            all_variants = [all_variants[i] for i in selected_indices]

        total_vectors = len(all_variants)
        job.stage = "COMPUTING_VECTORS"
        job.done = 0
        job.total = total_vectors
        job.stage_message = f"Computing vectors 0/{total_vectors}"
        db.commit()

        # Step 3: Embed in batches of 8 to 16
        BATCH_SIZE = 16
        computed_embeddings: List[Tuple[str, str, List[float], str]] = []

        for b_idx in range(0, total_vectors, BATCH_SIZE):
            # Check cancellation between vector batches
            if job_id in _cancelled_job_ids:
                job.status = "CANCELLED"
                job.stage = "CANCELLED"
                job.stage_message = "Scan processing was cancelled by user."
                db.commit()
                _cancelled_job_ids.discard(job_id)
                logger.info(f"ScanJob {job_id} cancelled during vector extraction.")
                return

            batch = all_variants[b_idx: b_idx + BATCH_SIZE]
            batch_images = [item[2] for item in batch]

            # Batch ONNX INT8 inference
            vectors = get_embeddings_batch(batch_images)

            for i, vec in enumerate(vectors):
                angle_tag, v_tag, _, frame_ref = batch[i]
                computed_embeddings.append((angle_tag, v_tag, vec, frame_ref))

            done_count = min(b_idx + len(batch), total_vectors)
            job.done = done_count
            job.stage_message = f"Computing vectors {done_count}/{total_vectors}"
            db.commit()

            await asyncio.sleep(0.01)

        # Step 4: Single-transaction commit
        job.stage = "SAVING_TO_DATABASE"
        job.stage_message = "Saving to database..."
        db.commit()

        # Clean existing embeddings and 360-scan images
        VectorStoreMatcher.delete_embeddings_for_product(db, product.id)
        db.query(ProductImage).filter(
            ProductImage.product_id == product.id,
            ProductImage.is_360_scan == True
        ).delete(synchronize_session=False)

        # Set primary image if available
        if primary_frame_url:
            product.primary_image_url = primary_frame_url
        product.is_active = True

        # Insert new ProductEmbedding records
        for angle_tag, v_tag, vec, frame_ref in computed_embeddings:
            full_tag = f"{angle_tag}_{v_tag}"
            VectorStoreMatcher.store_embedding(
                db=db,
                product_id=product.id,
                barcode=product.barcode,
                angle_tag=full_tag,
                vector=vec,
                image_path=frame_ref,
                model_name=MODEL_NAME,
                model_version=MODEL_VERSION,
                vector_dim=VECTOR_DIM,
                commit=False
            )

        # Mark job as ENROLLED
        job.status = "ENROLLED"
        job.stage = "COMPLETED"
        job.stage_message = f"Successfully enrolled {len(computed_embeddings)} vectors."
        job.done = total_vectors
        job.error = None

        db.commit()
        db.refresh(product)
        VectorStoreMatcher.sync_to_disk(db)
        catalog_cache.invalidate()

        logger.info(f"ScanJob {job_id} successfully enrolled {len(computed_embeddings)} vectors for {product.name}.")

    except Exception as e:
        logger.error(f"ScanJob {job_id} failed: {sanitize_secrets(e)}")
        db.rollback()
        try:
            job = db.query(ScanJob).filter(ScanJob.id == job_id).first()
            if job:
                job.status = "FAILED"
                job.stage = "FAILED"
                job.error = sanitize_secrets(str(e))
                job.stage_message = f"Failed: {job.error}"
                db.commit()
        except Exception:
            pass
        raise
    finally:
        db.close()


async def run_scan_job_with_watchdog(job_id: str):
    """
    Enforces concurrency lock (1 job at a time) and 120s timeout watchdog.
    If timeout is exceeded, sets job.status = FAILED and keeps uploaded frames.
    """
    async with _scan_job_lock:
        try:
            await asyncio.wait_for(_execute_scan_job_internal(job_id), timeout=120.0)
        except asyncio.TimeoutError:
            logger.error(f"ScanJob {job_id} timed out after 120s.")
            db = SessionLocal()
            try:
                job = db.query(ScanJob).filter(ScanJob.id == job_id).first()
                if job:
                    job.status = "FAILED"
                    job.stage = "FAILED"
                    job.error = "Processing timed out after 120 seconds limit. Please retry."
                    job.stage_message = "Failed: 120s timeout limit exceeded."
                    db.commit()
            finally:
                db.close()
        except Exception as e:
            logger.error(f"ScanJob {job_id} worker encountered error: {sanitize_secrets(e)}")


def enqueue_scan_job(job_id: str):
    """Schedules background task execution in the running event loop."""
    try:
        loop = asyncio.get_running_loop()
        return loop.create_task(run_scan_job_with_watchdog(job_id))
    except RuntimeError:
        # If called when no event loop is running in the current thread (e.g. sync tests)
        import threading
        thread = threading.Thread(
            target=lambda: asyncio.run(run_scan_job_with_watchdog(job_id)),
            daemon=True
        )
        thread.start()
        return thread
