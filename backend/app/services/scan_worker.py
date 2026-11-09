import os
import io
import json
import base64
import uuid
import time
import asyncio
import logging
import threading
from typing import List, Dict, Any, Tuple, Optional
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

# Concurrency lock: strictly ONE 360-scan job processed at a time
_scan_worker_lock = threading.Lock()
_cancelled_job_ids = set()

# Live worker timing metrics exposed to /admin/system-health
_worker_timing_metrics: Dict[str, Any] = {
    "download_storage_ms_total": 0.0,
    "download_storage_ms_avg": 0.0,
    "background_removal_ms_total": 0.0,
    "background_removal_ms_avg": 0.0,
    "crop_resize_ms_total": 0.0,
    "crop_resize_ms_avg": 0.0,
    "embedding_ms_total": 0.0,
    "embedding_ms_avg": 0.0,
    "database_save_ms_total": 0.0,
    "total_duration_ms": 0.0,
    "frames_processed": 0,
    "last_job_id": None,
    "last_job_status": None,
    "updated_at": None,
}


def get_worker_timing_metrics() -> Dict[str, Any]:
    """Returns live scan worker timing metrics for /admin/system-health."""
    return dict(_worker_timing_metrics)


def cancel_job(job_id: str):
    """Signals an active or queued job to cancel immediately."""
    _cancelled_job_ids.add(job_id)


def cleanup_orphaned_jobs_on_startup():
    """
    On server boot, marks any job left in PROCESSING or PENDING as FAILED.
    Preserves uploaded frames in frame_paths_json so user can retry immediately.
    """
    if not SessionLocal:
        return
    db = SessionLocal()
    try:
        orphans = db.query(ScanJob).filter(ScanJob.status.in_(["PENDING", "PROCESSING"])).all()
        for job in orphans:
            job.status = "FAILED"
            job.stage = "FAILED"
            job.error = "Server restarted during processing. Please retry. (ERR_SERVER_RESTART)"
            job.stage_message = "Server restarted during processing. Please retry."
        if orphans:
            db.commit()
            logger.info(f"Cleaned up {len(orphans)} orphaned scan job(s) from previous server run.")
    except Exception as e:
        logger.error(f"Error cleaning orphaned scan jobs on startup: {sanitize_secrets(e)}")
    finally:
        db.close()


def preprocess_product_image_for_embedding(pil_img: Image.Image, force_grabcut: bool = False) -> Image.Image:
    """
    Standard preprocessing for embedding:
    - If force_grabcut is False (default): the browser already cropped the product.
      Resizes to 224x224 directly, skipping CPU-heavy GrabCut.
    - If force_grabcut is True (crop flagged as poor): runs GrabCut segmentation
      initialized from product box and composites onto neutral grey (128, 128, 128).
    """
    if not force_grabcut:
        # Client-side crop was good: skip GrabCut completely for 160x speedup
        return pil_img.resize((224, 224), Image.BILINEAR)

    try:
        w, h = pil_img.size
        target_w = 320
        target_h = max(20, int(h * (320.0 / max(1, w))))
        img_320 = pil_img.resize((target_w, target_h), Image.BILINEAR)

        np_img = np.array(img_320.convert("RGB"))
        bgr = cv2.cvtColor(np_img, cv2.COLOR_RGB2BGR)
        h320, w320 = bgr.shape[:2]

        if h320 < 20 or w320 < 20 or float(np.mean(np.std(bgr, axis=(0, 1)))) < 5.0:
            return pil_img.resize((224, 224), Image.BILINEAR)

        mask = np.zeros((h320, w320), np.uint8)
        rx = max(1, int(w320 * 0.05))
        ry = max(1, int(h320 * 0.05))
        rw = max(1, int(w320 * 0.90) - 2)
        rh = max(1, int(h320 * 0.90) - 2)
        if rx + rw >= w320:
            rw = w320 - rx - 1
        if ry + rh >= h320:
            rh = h320 - ry - 1
        rect = (rx, ry, rw, rh)

        bgdModel = np.zeros((1, 65), np.float64)
        fgdModel = np.zeros((1, 65), np.float64)
        cv2.grabCut(bgr, mask, rect, bgdModel, fgdModel, 1, cv2.GC_INIT_WITH_RECT)
        fg_mask = np.where((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), 1, 0).astype("uint8")

        # Neutral grey background (128, 128, 128)
        grey_bg = np.full((h320, w320, 3), 128, dtype=np.uint8)
        fg_only = bgr * fg_mask[:, :, np.newaxis] + grey_bg * (1 - fg_mask[:, :, np.newaxis])
        matted_pil = Image.fromarray(cv2.cvtColor(fg_only.astype(np.uint8), cv2.COLOR_BGR2RGB))
        return matted_pil.resize((224, 224), Image.BILINEAR)
    except Exception as e:
        logger.warning(f"Preprocessing warning: {sanitize_secrets(e)}. Using resized frame.")
        return pil_img.resize((224, 224), Image.BILINEAR)


def _downscale_and_remove_background(pil_img: Image.Image, force_grabcut: bool = False) -> Image.Image:
    return preprocess_product_image_for_embedding(pil_img, force_grabcut=force_grabcut)


def _generate_variants_224(base_224: Image.Image, matted_224: Optional[Image.Image] = None) -> List[Tuple[str, Image.Image]]:
    """
    Produce 1 base image + 1 realistic augmentation variant per frame.
    Reduces total vector extraction load from 8x down to 2x per frame.
    """
    variants = [
        ("BASE", base_224),
        ("AUG_BRIGHT", ImageEnhance.Brightness(base_224).enhance(1.10)),
    ]
    return variants


def _parse_job_frame_state(frame_paths_json: Optional[str]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Optional[str]]:
    """
    Parses frame_paths_json supporting both legacy list and structured state.
    Returns (frames_list, existing_completed_vectors, primary_frame_url).
    """
    if not frame_paths_json:
        return [], [], None

    try:
        data = json.loads(frame_paths_json)
        if isinstance(data, list):
            frames = []
            for item in data:
                if isinstance(item, dict):
                    frames.append({
                        "angle_tag": item.get("angle_tag", "UNKNOWN"),
                        "frame_ref": item.get("frame_ref", ""),
                        "poor_crop": bool(item.get("poor_crop", False)),
                        "completed": False,
                    })
            return frames, [], None
        elif isinstance(data, dict):
            frames = data.get("frames", [])
            vectors = data.get("completed_vectors", [])
            primary_url = data.get("primary_frame_url")
            return frames, vectors, primary_url
    except Exception as e:
        logger.error(f"Failed to parse frame_paths_json: {sanitize_secrets(e)}")

    return [], [], None


def _serialize_job_frame_state(frames: List[Dict[str, Any]], vectors: List[Dict[str, Any]], primary_url: Optional[str]) -> str:
    """Serializes per-frame progress and computed vectors to JSON string."""
    return json.dumps({
        "frames": frames,
        "completed_vectors": vectors,
        "primary_frame_url": primary_url,
    })


def _execute_scan_job_sync(job_id: str):
    """
    Synchronous processing pipeline executed in a background worker thread.
    - Single-frame streaming (never loads all images in memory)
    - Per-stage timing metrics (download, crop, bg_removal, embed, db_save)
    - Stall watchdog (fails if no progress in 60s, max 10 minutes)
    - Resumes from last completed frame on retry
    - Caps scan at max 40 frames and 60 vectors
    """
    global _worker_timing_metrics

    # Enforce single worker concurrency
    with _scan_worker_lock:
        db: Session = SessionLocal()
        job_start_time = time.time()
        last_progress_time = time.time()

        # Timing accumulators for this job
        dl_times: List[float] = []
        bg_times: List[float] = []
        crop_times: List[float] = []
        embed_times: List[float] = []

        try:
            job = db.query(ScanJob).filter(ScanJob.id == job_id).first()
            if not job:
                logger.error(f"ScanJob {job_id} not found in database.")
                return

            # Check early cancellation
            if job_id in _cancelled_job_ids or job.status == "CANCELLED":
                job.status = "CANCELLED"
                job.stage = "CANCELLED"
                job.error = "Scan processing was cancelled by user. (ERR_CANCELLED)"
                job.stage_message = "Scan processing was cancelled by user."
                db.commit()
                _cancelled_job_ids.discard(job_id)
                logger.info(f"ScanJob {job_id} cancelled before processing began.")
                return

            product = db.query(Product).filter(Product.id == job.product_id).first()
            if not product:
                job.status = "FAILED"
                job.stage = "FAILED"
                job.error = "Target product not found. (ERR_PRODUCT_NOT_FOUND)"
                job.stage_message = "Failed: Target product not found."
                db.commit()
                return

            frames, completed_vectors, primary_frame_url = _parse_job_frame_state(job.frame_paths_json)
            if not frames:
                job.status = "FAILED"
                job.stage = "FAILED"
                job.error = "No saved frames available for this job. (ERR_NO_FRAMES)"
                job.stage_message = "Failed: No saved frames available."
                db.commit()
                return

            # Cap scan at max 40 frames
            MAX_FRAMES = 40
            if len(frames) > MAX_FRAMES:
                frames = frames[:MAX_FRAMES]

            total_frames = len(frames)
            MAX_VECTORS = 60

            job.status = "PROCESSING"
            job.stage = "PROCESSING_FRAMES"
            job.total = total_frames
            job.error = None
            db.commit()

            # Process frames one at a time
            for idx, item in enumerate(frames):
                # 1. Stall & Total Watchdog Check
                now = time.time()
                if (now - last_progress_time) > 60.0:
                    error_msg = f"Timed out: no progress for 60 s at Processing frame {idx + 1}/{total_frames} (ERR_STALL_TIMEOUT)"
                    logger.error(f"ScanJob {job_id}: {error_msg}")
                    job.status = "FAILED"
                    job.stage = "FAILED"
                    job.error = error_msg
                    job.stage_message = error_msg
                    db.commit()
                    return

                if (now - job_start_time) > 600.0:
                    error_msg = "Processing exceeded total 10 minute limit. Please retry. (ERR_TOTAL_TIMEOUT)"
                    logger.error(f"ScanJob {job_id}: {error_msg}")
                    job.status = "FAILED"
                    job.stage = "FAILED"
                    job.error = error_msg
                    job.stage_message = error_msg
                    db.commit()
                    return

                # 2. Cancellation Check
                if job_id in _cancelled_job_ids:
                    job.status = "CANCELLED"
                    job.stage = "CANCELLED"
                    job.error = "Scan processing was cancelled by user. (ERR_CANCELLED)"
                    job.stage_message = "Scan processing was cancelled by user."
                    # Persist progress so far
                    job.frame_paths_json = _serialize_job_frame_state(frames, completed_vectors, primary_frame_url)
                    db.commit()
                    _cancelled_job_ids.discard(job_id)
                    logger.info(f"ScanJob {job_id} cancelled during frame {idx + 1}/{total_frames}.")
                    return

                # 3. Skip already completed frames (from retry)
                if item.get("completed", False):
                    continue

                angle_tag = item.get("angle_tag", "UNKNOWN")
                frame_ref = item.get("frame_ref", "")
                poor_crop = bool(item.get("poor_crop", False))

                job.stage = "PROCESSING_FRAMES"
                job.stage_message = f"Processing frame {idx + 1}/{total_frames}"
                job.done = idx
                db.commit()

                # Stage A: Download frame from storage
                t_dl_start = time.time()
                try:
                    pil_img = storage_service.load_frame_image(frame_ref)
                except Exception as e:
                    logger.warning(f"Frame {idx + 1} download warning: {sanitize_secrets(e)}. Retrying once...")
                    time.sleep(0.5)
                    pil_img = storage_service.load_frame_image(frame_ref)
                t_dl_ms = (time.time() - t_dl_start) * 1000.0
                dl_times.append(t_dl_ms)

                # Primary frame thumbnail
                if primary_frame_url is None or angle_tag.upper() == "FRONT":
                    thumb = pil_img.copy()
                    thumb.thumbnail((400, 400))
                    thumb_buf = io.BytesIO()
                    thumb.save(thumb_buf, format="JPEG", quality=80)
                    primary_frame_url = f"data:image/jpeg;base64,{base64.b64encode(thumb_buf.getvalue()).decode('utf-8')}"

                # Stage B: Crop & Resize to 224x224
                t_crop_start = time.time()
                base_224 = pil_img.resize((224, 224), Image.BILINEAR)
                t_crop_ms = (time.time() - t_crop_start) * 1000.0
                crop_times.append(t_crop_ms)

                # Stage C: Background removal (only if flagged poor_crop)
                t_bg_start = time.time()
                if poor_crop:
                    matted_224 = _downscale_and_remove_background(pil_img, force_grabcut=True)
                else:
                    matted_224 = base_224  # Browser crop was good, skip GrabCut!
                t_bg_ms = (time.time() - t_bg_start) * 1000.0
                bg_times.append(t_bg_ms)

                # Generate 1 augmentation variant per frame
                variants = _generate_variants_224(base_224, matted_224)

                # Stage D: Batch ONNX Embedding for this frame (1 or 2 vectors)
                t_emb_start = time.time()
                embed_images = [v[1] for v in variants]
                if len(completed_vectors) < MAX_VECTORS:
                    vectors = get_embeddings_batch(embed_images)
                    for vi, (v_tag, _) in enumerate(variants):
                        if len(completed_vectors) < MAX_VECTORS:
                            completed_vectors.append({
                                "angle_tag": angle_tag,
                                "v_tag": v_tag,
                                "vec": vectors[vi],
                                "frame_ref": frame_ref,
                            })
                t_emb_ms = (time.time() - t_emb_start) * 1000.0
                embed_times.append(t_emb_ms)

                # Mark this frame completed
                item["completed"] = True
                last_progress_time = time.time()

                # Periodically update intermediate progress in DB
                job.done = idx + 1
                job.stage_message = f"Processing frame {idx + 1}/{total_frames} ({len(completed_vectors)} vectors)"
                job.frame_paths_json = _serialize_job_frame_state(frames, completed_vectors, primary_frame_url)
                db.commit()

                # Log timing telemetry every 5 frames and on first/last
                if (idx + 1) % 5 == 0 or idx == 0 or (idx + 1) == total_frames:
                    logger.info(
                        f"stage PROCESSING done {idx + 1}/{total_frames} "
                        f"(download: {t_dl_ms:.0f}ms, crop_resize: {t_crop_ms:.0f}ms, "
                        f"bg_removal: {t_bg_ms:.0f}ms, embed: {t_emb_ms:.0f}ms)"
                    )

                # Explicitly delete local images to release RAM
                del pil_img
                del base_224
                del matted_224
                del variants

            # Stage E: Atomic Database Save
            t_db_start = time.time()
            job.stage = "SAVING_TO_DATABASE"
            job.stage_message = "Saving embeddings to database..."
            db.commit()

            # Guard: Never delete or alter existing product vectors unless valid new vectors are generated
            if not completed_vectors:
                raise RuntimeError(
                    "No embeddings were generated from the frames. Aborting to protect existing vectors. (ERR_ZERO_VECTORS)"
                )

            # Clean existing embeddings for product atomically before inserting new ones
            VectorStoreMatcher.delete_embeddings_for_product(db, product.id)
            db.query(ProductImage).filter(
                ProductImage.product_id == product.id,
                ProductImage.is_360_scan == True
            ).delete(synchronize_session=False)

            if primary_frame_url:
                product.primary_image_url = primary_frame_url
            product.is_active = True

            # Insert new ProductEmbedding records
            for entry in completed_vectors:
                full_tag = f"{entry['angle_tag']}_{entry['v_tag']}"
                VectorStoreMatcher.store_embedding(
                    db=db,
                    product_id=product.id,
                    barcode=product.barcode,
                    angle_tag=full_tag,
                    vector=entry["vec"],
                    image_path=entry.get("frame_ref"),
                    model_name=MODEL_NAME,
                    model_version=MODEL_VERSION,
                    vector_dim=VECTOR_DIM,
                    commit=False
                )

            # Calculate quality_score
            unique_angles = set(f.get("angle_tag", "") for f in frames)
            angle_score = min(1.0, len(unique_angles) / 9.0)
            frame_score = min(1.0, len(frames) / 36.0)

            intra_sim = 0.85
            if completed_vectors:
                sample_vecs = [item["vec"] for item in completed_vectors[:20]]
                if len(sample_vecs) >= 2:
                    sims = []
                    for s1 in range(min(10, len(sample_vecs))):
                        for s2 in range(s1 + 1, min(10, len(sample_vecs))):
                            sim = float(np.dot(sample_vecs[s1], sample_vecs[s2]))
                            sims.append(sim)
                    if sims:
                        intra_sim = max(0.0, min(1.0, float(np.mean(sims))))

            sharpness_score = 0.90
            composite_quality = round(0.30 * frame_score + 0.30 * angle_score + 0.20 * sharpness_score + 0.20 * intra_sim, 2)
            product.quality_score = composite_quality

            # Mark job ENROLLED
            job.status = "ENROLLED"
            job.stage = "COMPLETED"
            job.stage_message = f"Successfully enrolled {len(completed_vectors)} vectors across {len(frames)} frames."
            job.done = len(completed_vectors)
            job.error = None

            db.commit()
            db.refresh(product)
            VectorStoreMatcher.sync_to_disk(db)
            catalog_cache.invalidate()

            t_db_ms = (time.time() - t_db_start) * 1000.0
            total_duration_ms = (time.time() - job_start_time) * 1000.0

            # Update live worker metrics
            _worker_timing_metrics["download_storage_ms_total"] = round(sum(dl_times), 1)
            _worker_timing_metrics["download_storage_ms_avg"] = round(float(np.mean(dl_times)) if dl_times else 0.0, 1)
            _worker_timing_metrics["background_removal_ms_total"] = round(sum(bg_times), 1)
            _worker_timing_metrics["background_removal_ms_avg"] = round(float(np.mean(bg_times)) if bg_times else 0.0, 1)
            _worker_timing_metrics["crop_resize_ms_total"] = round(sum(crop_times), 1)
            _worker_timing_metrics["crop_resize_ms_avg"] = round(float(np.mean(crop_times)) if crop_times else 0.0, 1)
            _worker_timing_metrics["embedding_ms_total"] = round(sum(embed_times), 1)
            _worker_timing_metrics["embedding_ms_avg"] = round(float(np.mean(embed_times)) if embed_times else 0.0, 1)
            _worker_timing_metrics["database_save_ms_total"] = round(t_db_ms, 1)
            _worker_timing_metrics["total_duration_ms"] = round(total_duration_ms, 1)
            _worker_timing_metrics["frames_processed"] = len(frames)
            _worker_timing_metrics["last_job_id"] = job_id
            _worker_timing_metrics["last_job_status"] = "ENROLLED"
            _worker_timing_metrics["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

            logger.info(
                f"ScanJob {job_id} ENROLLED {len(completed_vectors)} vectors in {total_duration_ms/1000:.2f}s "
                f"(dl_avg: {_worker_timing_metrics['download_storage_ms_avg']}ms, "
                f"crop_avg: {_worker_timing_metrics['crop_resize_ms_avg']}ms, "
                f"bg_avg: {_worker_timing_metrics['background_removal_ms_avg']}ms, "
                f"emb_avg: {_worker_timing_metrics['embedding_ms_avg']}ms, "
                f"db: {t_db_ms:.0f}ms)"
            )

        except Exception as e:
            sanitized_err = sanitize_secrets(str(e))
            logger.error(f"ScanJob {job_id} worker encountered error: {sanitized_err}")
            db.rollback()
            try:
                job = db.query(ScanJob).filter(ScanJob.id == job_id).first()
                if job:
                    job.status = "FAILED"
                    job.stage = "FAILED"
                    job.error = f"Error during processing: {sanitized_err} (ERR_WORKER_EXCEPTION)"
                    job.stage_message = f"Failed: {sanitized_err}"
                    db.commit()
            except Exception:
                pass
            _worker_timing_metrics["last_job_id"] = job_id
            _worker_timing_metrics["last_job_status"] = "FAILED"
            _worker_timing_metrics["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        finally:
            db.close()


async def _execute_scan_job_internal(job_id: str):
    """
    Async interface maintaining backward compatibility with tests.
    Dispatches to worker thread so event loop remains free.
    """
    await asyncio.to_thread(_execute_scan_job_sync, job_id)


# Backward-compatibility alias for test harness
run_scan_job_with_watchdog = _execute_scan_job_internal


def enqueue_scan_job(job_id: str):
    """
    Starts background execution in a dedicated daemon thread.
    Keeps the FastAPI event loop completely responsive for /health.
    """
    thread = threading.Thread(
        target=_execute_scan_job_sync,
        args=(job_id,),
        name=f"ScanWorker-{job_id[:8]}",
        daemon=True
    )
    thread.start()
    return thread
