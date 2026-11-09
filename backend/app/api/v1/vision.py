import os
import io
import uuid
import json
import base64
import logging
from typing import Optional, List, Tuple
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from PIL import Image, ImageEnhance, ImageFilter
import numpy as np
try:
    import cv2
except Exception:
    cv2 = None


from app.database import get_db
from app.config import settings
from app.models.cart import Cart
from app.models.session import CartSession, CartItem
from app.models.product import Product, ProductImage
from app.models.scan_job import ScanJob
from app.models.user import User
from app.services.session_service import SessionService
from app.services.alert_service import AlertService
from app.services.storage_service import storage_service
from app.ai.feature_extractor import get_embedding, MODEL_NAME, MODEL_VERSION, VECTOR_DIM
from app.ai.vector_store import VectorStoreMatcher
from app.api.v1.auth import get_current_user, require_admin_or_manager

logger = logging.getLogger("smartcart.vision")

router = APIRouter(prefix="/vision", tags=["Vision & AI Real Pipeline"], dependencies=[Depends(get_current_user)])

class SimulateActionRequest(BaseModel):
    cart_id: str
    action_type: str  # PLACE_CORRECT, PLACE_WRONG, PLACE_UNSCANNED, REMOVE_ITEM
    barcode: Optional[str] = None
    detected_barcode: Optional[str] = None
    confidence: Optional[float] = 0.94
    evidence_url: Optional[str] = None

class Scan360Capture(BaseModel):
    angle_tag: str  # FRONT, BACK, LEFT, RIGHT, TOP, BOTTOM, LABEL_CLOSEUP
    image_data_url: str

class Complete360ScanRequest(BaseModel):
    captures: List[Scan360Capture]

class PreviewTestRequest(BaseModel):
    image_data_url: str
    target_barcode: Optional[str] = None

def _remove_background(pil_img: Image.Image) -> Image.Image:
    """Segment object foreground from background using GrabCut."""
    try:
        np_img = np.array(pil_img.convert("RGB"))
        bgr = cv2.cvtColor(np_img, cv2.COLOR_RGB2BGR)
        h, w = bgr.shape[:2]
        if h < 20 or w < 20:
            return pil_img
        mask = np.zeros((h, w), np.uint8)
        rect = (max(1, int(w * 0.08)), max(1, int(h * 0.08)), max(1, int(w * 0.84)), max(1, int(h * 0.84)))
        bgdModel = np.zeros((1, 65), np.float64)
        fgdModel = np.zeros((1, 65), np.float64)
        cv2.grabCut(bgr, mask, rect, bgdModel, fgdModel, 1, cv2.GC_INIT_WITH_RECT)
        mask2 = np.where((mask == 2) | (mask == 0), 0, 1).astype('uint8')
        bgr_fg = bgr * mask2[:, :, np.newaxis] + (1 - mask2[:, :, np.newaxis]) * 240
        return Image.fromarray(cv2.cvtColor(bgr_fg.astype(np.uint8), cv2.COLOR_BGR2RGB))
    except Exception as e:
        logger.warning(f"GrabCut background removal warning: {e}. Using original image.")
        return pil_img

def _generate_augmentations(img: Image.Image) -> List[Tuple[str, Image.Image]]:
    """Produce light realistic augmentations: brightness, rotation, slight blur, and partial crop."""
    w, h = img.size
    variants = [
        ("BASE", img),
        ("BRIGHT_HIGH", ImageEnhance.Brightness(img).enhance(1.15)),
        ("BRIGHT_LOW", ImageEnhance.Brightness(img).enhance(0.85)),
        ("ROT_POS", img.rotate(10, resample=Image.BILINEAR, fillcolor=(240, 240, 240))),
        ("ROT_NEG", img.rotate(-10, resample=Image.BILINEAR, fillcolor=(240, 240, 240))),
        ("BLUR", img.filter(ImageFilter.GaussianBlur(radius=0.8))),
        ("CROP_ZOOM", img.crop((int(w * 0.06), int(h * 0.06), int(w * 0.94), int(h * 0.94))).resize((w, h), Image.BILINEAR)),
    ]
    return variants

@router.post("/simulate-action")
async def simulate_cart_camera_action(
    req: SimulateActionRequest,
    current_user: User = Depends(require_admin_or_manager),
    db: Session = Depends(get_db)
):
    """
    Simulate cart camera detections and physical cart events for testing without hardware.
    Restricted to Admin and Manager roles.
    Disabled unless USE_MOCK=true is configured.
    """
    if not settings.USE_MOCK:
        raise HTTPException(
            status_code=403,
            detail="Hardware vision simulation is disabled. Set USE_MOCK=true to enable mock camera simulation."
        )
    cart = db.query(Cart).filter((Cart.id == req.cart_id) | (Cart.cart_number == req.cart_id.upper())).first()
    if not cart:
        raise HTTPException(status_code=404, detail="Cart not found")

    active_session = db.query(CartSession).filter(
        CartSession.cart_id == cart.id,
        CartSession.status == "ACTIVE"
    ).first()

    if not active_session:
        raise HTTPException(status_code=400, detail="No active session found on this cart.")

    default_evidence = req.evidence_url or "/uploads/evidence/sample_cart_detection.jpg"

    if req.action_type in ["PLACE_CORRECT", "CONFIRM_BARCODE"]:
        barcode = req.barcode or req.detected_barcode or "8901262010053"
        item = db.query(CartItem).join(Product).filter(
            CartItem.session_id == active_session.id,
            Product.barcode == barcode,
            CartItem.status == "PENDING"
        ).first()

        if not item:
            item = db.query(CartItem).filter(
                CartItem.session_id == active_session.id,
                CartItem.status == "PENDING"
            ).first()

        if not item:
            item = db.query(CartItem).filter(
                CartItem.session_id == active_session.id
            ).first()

        if item:
            item.status = "VERIFIED"
            item.confidence_score = req.confidence or 0.95
            item.verification_evidence_url = default_evidence
            db.commit()
            prod_name = item.product.name if item.product else "Item"
            return {"status": "SUCCESS", "event": "ITEM_VERIFIED", "item_name": prod_name}
        else:
            raise HTTPException(status_code=400, detail="Item not found in shopper cart for verification.")

    elif req.action_type == "PLACE_WRONG":
        item = db.query(CartItem).filter(
            CartItem.session_id == active_session.id,
            CartItem.status == "PENDING"
        ).first()

        if item:
            item.status = "WARNING_MISMATCH"
            item.confidence_score = req.confidence or 0.88
            item.verification_evidence_url = default_evidence
            db.commit()

            detected_name = "Wrong Item Detected"
            if req.detected_barcode:
                detected_prod = db.query(Product).filter(Product.barcode == req.detected_barcode).first()
                if detected_prod:
                    detected_name = detected_prod.name

            scanned_bcode = item.product.barcode if item.product else "UNKNOWN"
            await AlertService.create_alert(
                db=db,
                cart_id=cart.id,
                session_id=active_session.id,
                alert_type="MISMATCH_ITEM",
                severity="HIGH",
                message=f"Shopper scanned barcode {scanned_bcode} but camera observed {detected_name}.",
                evidence_url=default_evidence,
                create_review_case=True,
                scanned_barcode=scanned_bcode,
                confidence=req.confidence or 0.88
            )
            return {"status": "SUCCESS", "event": "MISMATCH_ALERT_RAISED", "detected_as": detected_name}
        else:
            raise HTTPException(status_code=400, detail="No pending item in cart to trigger mismatch against.")

    elif req.action_type == "PLACE_UNSCANNED":
        detected_prod = db.query(Product).filter(Product.barcode == req.detected_barcode).first() if req.detected_barcode else None
        await SessionService.flag_unscanned_item(
            db=db,
            cart_id=cart.id,
            detected_product_id=detected_prod.id if detected_prod else None,
            evidence_url=default_evidence
        )
        return {"status": "SUCCESS", "event": "UNSCANNED_ALERT_RAISED"}

    elif req.action_type == "REMOVE_ITEM":
        await AlertService.create_alert(
            db=db,
            cart_id=cart.id,
            session_id=active_session.id,
            alert_type="ITEM_REMOVAL",
            severity="MEDIUM",
            message=f"Item with barcode {req.barcode or 'unknown'} was removed from cart.",
            evidence_url=default_evidence
        )
        return {"status": "SUCCESS", "event": "ITEM_REMOVAL_DETECTED"}

    else:
        raise HTTPException(status_code=400, detail=f"Unknown action type: {req.action_type}")

@router.post("/products/{product_id}/360-scan/complete")
async def save_360_scan_embeddings(
    product_id: str,
    req: Complete360ScanRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_manager)
):
    """
    Asynchronous 360-degree camera capture enrollment:
    1. Saves incoming camera frames to Supabase Storage (or local storage fallback).
    2. Instantiates a ScanJob in the database with status PENDING.
    3. Queues the background worker to process frames without blocking the client.
    4. Immediately returns job_id (<200ms) for real-time polling by the UI.
    """
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    if not req.captures:
        raise HTTPException(status_code=400, detail="No camera frames provided in 360 scan payload.")

    job_id = str(uuid.uuid4())
    saved_frames = []

    for idx, cap in enumerate(req.captures):
        raw_b64 = cap.image_data_url
        if raw_b64.startswith("data:image"):
            parts = raw_b64.split(",", 1)
            if len(parts) == 2:
                raw_b64 = parts[1]

        try:
            image_bytes = base64.b64decode(raw_b64)
            filename = f"{product.barcode}_{cap.angle_tag}_{idx}_{uuid.uuid4().hex[:6]}.jpg"
            frame_ref = storage_service.save_frame(job_id, filename, image_bytes)
            saved_frames.append({
                "angle_tag": cap.angle_tag,
                "frame_ref": frame_ref
            })
        except Exception as e:
            logger.warning(f"Error saving frame {cap.angle_tag}: {e}")

    if not saved_frames:
        raise HTTPException(status_code=400, detail="Failed to decode or store any valid image frames.")

    scan_job = ScanJob(
        id=job_id,
        product_id=product.id,
        status="PENDING",
        stage="SAVING_FRAMES",
        stage_message=f"Uploaded {len(saved_frames)} frames. Enqueuing background processing...",
        done=0,
        total=len(saved_frames),
        frame_paths_json=json.dumps(saved_frames)
    )
    db.add(scan_job)
    db.commit()
    db.refresh(scan_job)

    # Enqueue background processing
    from app.services.scan_worker import enqueue_scan_job
    enqueue_scan_job(scan_job.id)

    return {
        "status": "PENDING",
        "job_id": scan_job.id,
        "product_id": product.id,
        "total_frames": len(saved_frames),
        "message": "360-scan frames saved successfully. Background processing started."
    }


@router.get("/jobs/{job_id}")
def get_scan_job_status(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Polls real-time state of an ongoing or completed 360-degree scan job.
    Never returns fake progress or hardcoded steps.
    """
    job = db.query(ScanJob).filter(ScanJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Scan job not found.")

    return {
        "job_id": job.id,
        "product_id": job.product_id,
        "status": job.status,
        "stage": job.stage,
        "stage_message": job.stage_message,
        "done": job.done,
        "total": job.total,
        "error": job.error,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "updated_at": job.updated_at.isoformat() if job.updated_at else None
    }


@router.post("/jobs/{job_id}/cancel")
def cancel_scan_job(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_manager)
):
    """
    Cancels an active or pending scan job.
    Admin or Manager only.
    Worker checks cancel flag between batches, stops immediately,
    sets status CANCELLED, and preserves frames for potential retry.
    """
    job = db.query(ScanJob).filter(ScanJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Scan job not found.")

    if job.status in ("ENROLLED", "COMPLETED"):
        raise HTTPException(status_code=400, detail="Cannot cancel a job that has already completed.")

    from app.services.scan_worker import cancel_job
    cancel_job(job.id)

    job.status = "CANCELLED"
    job.stage = "CANCELLED"
    job.stage_message = "Scan processing was cancelled by user."
    db.commit()

    return {
        "status": "CANCELLED",
        "job_id": job.id,
        "message": "Scan job cancellation requested."
    }


@router.get("/products/{product_id}/active-job")
def get_product_active_job(
    product_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Returns the latest scan job for a product to enable reopening the progress popup
    from the product catalog view if closed during execution.
    """
    job = db.query(ScanJob).filter(
        ScanJob.product_id == product_id
    ).order_by(ScanJob.created_at.desc()).first()

    if not job:
        return {"has_active_job": False, "job": None}

    is_active = job.status in ("PENDING", "PROCESSING")
    return {
        "has_active_job": is_active,
        "job": {
            "job_id": job.id,
            "product_id": job.product_id,
            "status": job.status,
            "stage": job.stage,
            "stage_message": job.stage_message,
            "done": job.done,
            "total": job.total,
            "error": job.error,
            "created_at": job.created_at.isoformat() if job.created_at else None,
            "updated_at": job.updated_at.isoformat() if job.updated_at else None
        }
    }


@router.post("/jobs/{job_id}/retry")
def retry_scan_job(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_manager)
):
    """
    Retries a failed or cancelled scan job using previously saved frames without re-uploading.
    """
    job = db.query(ScanJob).filter(ScanJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Scan job not found.")

    if job.status == "PROCESSING":
        raise HTTPException(status_code=400, detail="Scan job is currently being processed.")

    from app.services.scan_worker import _cancelled_job_ids, enqueue_scan_job
    _cancelled_job_ids.discard(job.id)

    job.status = "PENDING"
    job.stage = "QUEUED"
    job.stage_message = "Retry enqueued. Waiting for worker..."
    job.error = None
    job.done = 0
    db.commit()

    enqueue_scan_job(job.id)

    return {
        "status": "PENDING",
        "job_id": job.id,
        "message": "Job re-queued successfully."
    }

@router.post("/products/preview-test")
def preview_recognition_test(
    req: PreviewTestRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_manager)
):
    """
    Live real camera preview test:
    Admin holds product in front of webcam, system computes real CLIP embedding
    and returns top-3 nearest catalog matches with real cosine similarity scores.
    """
    if not req.image_data_url or len(req.image_data_url) < 100:
        raise HTTPException(status_code=400, detail="Invalid camera frame received. Please point your webcam at the product.")

    try:
        # Real ONNX INT8 CLIP ViT-B/32 embedding of the live camera frame
        query_vector = get_embedding(req.image_data_url)
    except RuntimeError as re:
        logger.error(f"AI model unavailable during preview test: {re}")
        raise HTTPException(status_code=503, detail="AI Vision Service Unavailable: ONNX INT8 model is still loading or unavailable.")
    except Exception as e:
        logger.error(f"Failed to extract embedding from preview camera frame: {e}")
        raise HTTPException(status_code=400, detail=f"Failed to process camera frame: {str(e)}")

    # Retrieve top-3 nearest products from persistent vector store (pgvector or disk cache)
    top_matches = VectorStoreMatcher.find_nearest_product(db, query_vector, top_k=3)

    target_similarity = 0.0
    if req.target_barcode:
        is_target_match, target_similarity = VectorStoreMatcher.verify_claimed_barcode(
            db=db,
            claimed_barcode=req.target_barcode,
            query_vector=query_vector,
            high_threshold=settings.CONFIDENCE_HIGH
        )

    top_1 = top_matches[0] if top_matches else None
    matched = False
    if req.target_barcode and top_1:
        matched = (top_1["barcode"] == req.target_barcode and top_1["similarity"] >= settings.CONFIDENCE_HIGH)
    elif top_1:
        matched = (top_1["similarity"] >= settings.CONFIDENCE_HIGH)

    message = f"Top match: {top_1['product_name']} ({top_1['similarity'] * 100:.1f}%)" if top_1 else "No enrolled products found."

    return {
        "matched": matched,
        "confidence": top_1["similarity"] if top_1 else 0.0,
        "product_name": top_1["product_name"] if top_1 else None,
        "barcode": top_1["barcode"] if top_1 else None,
        "top_matches": top_matches,
        "target_barcode": req.target_barcode,
        "target_confidence": target_similarity,
        "threshold_high": settings.CONFIDENCE_HIGH,
        "message": message
    }
