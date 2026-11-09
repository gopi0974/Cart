import io
import uuid
import json
import base64
import logging
from typing import Optional, List, Tuple, Dict, Any
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, File, UploadFile, Form
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
from app.models.product import Product
from app.models.scan_job import ScanJob
from app.models.user import User
from app.services.session_service import SessionService
from app.services.alert_service import AlertService
from app.services.storage_service import storage_service
from app.ai.feature_extractor import get_embedding
from app.ai.vector_store import VectorStoreMatcher
from app.api.v1.auth import get_current_user, require_admin_or_manager
from app.utils.sanitization import sanitize_secrets

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
    angle_tag: str  # FRONT, BACK, LEFT, RIGHT, TOP, BOTTOM, LABEL_CLOSEUP, TILT_UP, TILT_DOWN
    image_data_url: str  # Cropped product box frame
    original_image_data_url: Optional[str] = None  # Full uncropped camera frame
    poor_crop: Optional[bool] = False

class Complete360ScanRequest(BaseModel):
    captures: Optional[List[Scan360Capture]] = None
    job_id: Optional[str] = None
    frames: Optional[List[Dict[str, Any]]] = None

class InitUploadFileItem(BaseModel):
    angle_tag: str
    filename: str
    poor_crop: Optional[bool] = False

class InitUploadRequest(BaseModel):
    files: List[InitUploadFileItem]

class RetryJobRequest(BaseModel):
    confirm_partial: bool = False

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

@router.post("/products/{product_id}/360-scan/init-upload")
def init_360_scan_upload(
    product_id: str,
    req: InitUploadRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_manager)
):
    """
    Initializes direct client-side upload to Supabase Storage:
    1. Generates a new ScanJob in the database.
    2. Requests HMAC-signed upload URLs from Supabase Storage for each file.
    3. If Supabase signed URLs are generated, client uploads JPEGs (max 640px) directly,
       bypassing the backend server memory/bandwidth entirely.
    4. If Supabase is offline/unconfigured, falls back to server-side base64 upload.
    """
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    if len(req.files) > 40:
        raise HTTPException(status_code=400, detail="Exceeded maximum limit of 40 frames per scan.")

    # Validate filenames strictly belong to this product prefix and contain no directory traversal
    allowed_prefixes = (product.barcode, product.id)
    for f in req.files:
        if ".." in f.filename or "/" in f.filename or "\\" in f.filename:
            raise HTTPException(status_code=400, detail=f"Invalid filename '{f.filename}': path traversal not permitted.")
        if not any(f.filename.startswith(p) for p in allowed_prefixes):
            raise HTTPException(
                status_code=400,
                detail=f"Invalid filename '{f.filename}': filename must start with product barcode ({product.barcode}) or ID prefix."
            )

    job_id = str(uuid.uuid4())
    upload_items = []
    direct_available = storage_service.is_supabase_configured

    if direct_available:
        for f in req.files:
            signed_data = storage_service.create_signed_upload_url(job_id, f.filename)
            if signed_data:
                upload_items.append({
                    "angle_tag": f.angle_tag,
                    "filename": f.filename,
                    "upload_url": signed_data["upload_url"],
                    "frame_ref": signed_data["frame_ref"],
                    "poor_crop": bool(f.poor_crop),
                })
            else:
                direct_available = False
                break

    # Instantiate placeholder job
    scan_job = ScanJob(
        id=job_id,
        product_id=product.id,
        status="PENDING",
        stage="AWAITING_UPLOAD",
        stage_message="Awaiting client upload of frames...",
        done=0,
        total=len(req.files),
        frame_paths_json=None
    )
    db.add(scan_job)
    db.commit()

    logger.info(
        f"[init-upload] product_id={product.id} barcode={product.barcode} "
        f"files_requested={len(req.files)} direct_available={direct_available} job_id={job_id}"
    )

    return {
        "job_id": job_id,
        "product_id": product.id,
        "direct_upload": direct_available and len(upload_items) == len(req.files),
        "upload_items": upload_items if direct_available else [],
    }


@router.post("/products/{product_id}/360-scan/complete")
async def save_360_scan_embeddings(
    product_id: str,
    req: Complete360ScanRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_manager)
):
    """
    Asynchronous 360-degree camera capture enrollment:
    Accepts either:
    1. Pre-uploaded frames (direct upload via signed URLs with job_id and frames list).
    2. Direct camera captures (base64 fallback for offline/local environments).
    Queues background worker and immediately returns job_id (<200ms).
    """
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    # Path A: Direct upload was used (client sent list of stored frame refs)
    if req.frames is not None:
        if len(req.frames) == 0:
            raise HTTPException(
                status_code=400,
                detail="No frames provided in direct upload payload. (ERR_NO_FRAMES)"
            )

        if len(req.frames) > 40:
            raise HTTPException(
                status_code=400,
                detail="Exceeded maximum limit of 40 frames per scan."
            )

        if not req.job_id:
            raise HTTPException(status_code=400, detail="job_id is required for direct upload.")

        job = db.query(ScanJob).filter(ScanJob.id == req.job_id).first()
        if not job:
            raise HTTPException(status_code=404, detail=f"ScanJob '{req.job_id}' not found.")
        if job.product_id != product.id:
            raise HTTPException(status_code=400, detail=f"ScanJob '{req.job_id}' does not belong to product '{product.id}'.")

        # Validate that each frame_ref belongs to this job and product prefix
        allowed_prefixes = (product.barcode, product.id)
        frame_refs = []
        for item in req.frames:
            ref = item.get("frame_ref", "")
            if not ref:
                continue
            if f"/{req.job_id}/" not in ref:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid frame reference '{ref}': frame does not belong to job '{req.job_id}'."
                )
            if ".." in ref:
                raise HTTPException(status_code=400, detail="Invalid frame reference: path traversal detected.")
            ref_filename = ref.split("/")[-1]
            if not any(ref_filename.startswith(p) for p in allowed_prefixes):
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid frame reference '{ref}': filename must start with product barcode ({product.barcode}) or ID prefix."
                )
            frame_refs.append(ref)

        if not frame_refs:
            raise HTTPException(
                status_code=400,
                detail="No valid frame references provided in payload. (ERR_NO_FRAMES)"
            )

        logger.info(f"[upload-check] Verifying storage presence for {len(frame_refs)} frames (job_id={req.job_id})...")
        existing_refs, missing_refs = storage_service.check_frames_exist(frame_refs)
        logger.info(f"[upload-check] Storage verify result: {len(existing_refs)} verified, {len(missing_refs)} missing.")

        if missing_refs:
            missing_names = [ref.split("/")[-1] for ref in missing_refs]
            summary = ", ".join(missing_names[:5]) + ("..." if len(missing_names) > 5 else "")
            err_msg = f"Missing {len(missing_refs)} frames in storage: {summary} (ERR_MISSING_FRAMES)"
            logger.error(f"[upload-check] {err_msg}")

            job.status = "FAILED"
            job.stage = "FAILED"
            job.error = err_msg
            job.stage_message = err_msg
            db.commit()

            raise HTTPException(status_code=400, detail=err_msg)

        clean_frames = []
        for item in req.frames:
            clean_frames.append({
                "angle_tag": item.get("angle_tag", "UNKNOWN"),
                "frame_ref": item.get("frame_ref", ""),
                "poor_crop": bool(item.get("poor_crop", False)),
                "completed": False,
            })

        job.status = "PENDING"
        job.stage = "QUEUED"
        job.stage_message = f"Enqueued {len(clean_frames)} verified frames for processing."
        job.total = len(clean_frames)
        job.done = 0
        job.error = None
        job.frame_paths_json = json.dumps({"frames": clean_frames, "completed_vectors": [], "primary_frame_url": None})
        db.commit()

        logger.info(f"[scan-complete] Enqueuing background worker for job_id={job.id} with {len(clean_frames)} verified frames.")
        from app.services.scan_worker import enqueue_scan_job
        enqueue_scan_job(job.id)

        return {
            "status": "PENDING",
            "job_id": job.id,
            "product_id": product.id,
            "total_frames": len(clean_frames),
            "message": "360-scan frames received and verified. Background processing started."
        }

    # Path B: Fallback base64 captures
    if not req.captures:
        raise HTTPException(status_code=400, detail="No camera frames provided in 360 scan payload. (ERR_NO_FRAMES)")

    # Size limits: max 40 frames and max 5MB per frame
    if len(req.captures) > 40:
        raise HTTPException(status_code=400, detail="Exceeded maximum limit of 40 frames per scan.")

    MAX_BYTES_PER_FRAME = 5 * 1024 * 1024
    MAX_B64_LEN = (MAX_BYTES_PER_FRAME * 4 // 3) + 200

    job_id = req.job_id or str(uuid.uuid4())
    saved_frames = []

    for idx, cap in enumerate(req.captures):
        raw_b64 = cap.image_data_url
        if len(raw_b64) > MAX_B64_LEN:
            raise HTTPException(status_code=400, detail=f"Frame {cap.angle_tag} exceeds maximum allowed size of 5MB.")

        if raw_b64.startswith("data:image"):
            parts = raw_b64.split(",", 1)
            if len(parts) == 2:
                raw_b64 = parts[1]

        try:
            image_bytes = base64.b64decode(raw_b64)
            if len(image_bytes) > MAX_BYTES_PER_FRAME:
                raise HTTPException(status_code=400, detail=f"Frame {cap.angle_tag} exceeds maximum allowed size of 5MB.")

            filename = f"{product.barcode}_{cap.angle_tag}_{idx}_{uuid.uuid4().hex[:6]}.jpg"
            frame_ref = storage_service.save_frame(job_id, filename, image_bytes)

            # Low memory footprint: release buffer immediately
            del image_bytes
            cap.image_data_url = ""

            saved_frames.append({
                "angle_tag": cap.angle_tag,
                "frame_ref": frame_ref,
                "poor_crop": bool(cap.poor_crop),
                "completed": False,
            })
        except HTTPException:
            raise
        except Exception as e:
            logger.warning(f"Error saving frame {cap.angle_tag}: {sanitize_secrets(e)}")

    if not saved_frames:
        raise HTTPException(status_code=400, detail="Failed to decode or store any valid image frames.")

    scan_job = None
    if req.job_id:
        scan_job = db.query(ScanJob).filter(ScanJob.id == req.job_id).first()

    if not scan_job:
        scan_job = ScanJob(
            id=job_id,
            product_id=product.id,
            status="PENDING",
            stage="SAVING_FRAMES",
            stage_message=f"Uploaded {len(saved_frames)} frames. Enqueuing background processing...",
            done=0,
            total=len(saved_frames),
            frame_paths_json=json.dumps({"frames": saved_frames, "completed_vectors": [], "primary_frame_url": None})
        )
        db.add(scan_job)
    else:
        scan_job.status = "PENDING"
        scan_job.stage = "SAVING_FRAMES"
        scan_job.stage_message = f"Uploaded {len(saved_frames)} frames. Enqueuing background processing..."
        scan_job.done = 0
        scan_job.total = len(saved_frames)
        scan_job.error = None
        scan_job.frame_paths_json = json.dumps({"frames": saved_frames, "completed_vectors": [], "primary_frame_url": None})

    db.commit()
    db.refresh(scan_job)

    logger.info(f"[scan-complete] Base64 fallback enqueued for job_id={scan_job.id} with {len(saved_frames)} frames.")
    from app.services.scan_worker import enqueue_scan_job
    enqueue_scan_job(scan_job.id)

    return {
        "status": "PENDING",
        "job_id": scan_job.id,
        "product_id": product.id,
        "total_frames": len(saved_frames),
        "message": "360-scan frames saved successfully. Background processing started."
    }


@router.post("/products/{product_id}/360-scan/upload-frame")
async def upload_single_frame_server(
    product_id: str,
    job_id: str = Form(...),
    angle_tag: str = Form(...),
    file: UploadFile = File(...),
    poor_crop: bool = Form(False),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_manager)
):
    """
    Streaming single-frame upload endpoint through the backend server.
    Low-memory footprint: streams one frame at a time without buffering all frames in RAM.
    Limits: Max 5MB per frame. Requires Admin or Manager.
    """
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    job = db.query(ScanJob).filter(ScanJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail=f"ScanJob '{job_id}' not found.")
    if job.product_id != product.id:
        raise HTTPException(status_code=400, detail="ScanJob does not belong to this product.")

    MAX_BYTES_PER_FRAME = 5 * 1024 * 1024
    content = await file.read(MAX_BYTES_PER_FRAME + 1024)
    if len(content) > MAX_BYTES_PER_FRAME:
        raise HTTPException(status_code=400, detail="Frame exceeds maximum allowed size of 5MB.")

    clean_angle = angle_tag.strip().replace(" ", "_").upper()
    filename = f"{product.barcode}_{clean_angle}_{uuid.uuid4().hex[:6]}.jpg"
    frame_ref = storage_service.save_frame(job_id, filename, content)
    del content

    return {
        "job_id": job_id,
        "angle_tag": angle_tag,
        "filename": filename,
        "frame_ref": frame_ref,
        "poor_crop": poor_crop
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
    req: Optional[RetryJobRequest] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_manager)
):
    """
    Retries a failed or cancelled scan job using previously saved frames without re-uploading.
    Re-verifies frames exist in storage, only reuses valid existing frames, and resumes from
    the last completed frame. If no frames exist, rejects retry with clear ERR_NO_FRAMES error.
    If some frames are missing, warns and requires explicit confirmation before partial enrollment.
    """
    job = db.query(ScanJob).filter(ScanJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Scan job not found.")

    if job.status == "PROCESSING":
        raise HTTPException(status_code=400, detail="Scan job is currently being processed.")

    from app.services.scan_worker import _parse_job_frame_state, _serialize_job_frame_state, _cancelled_job_ids, enqueue_scan_job
    frames, completed_vectors, primary_url = _parse_job_frame_state(job.frame_paths_json)

    if not frames:
        job.status = "FAILED"
        job.stage = "FAILED"
        job.error = "This scan has no saved frames. Please scan again. (ERR_NO_FRAMES)"
        job.stage_message = job.error
        db.commit()
        raise HTTPException(
            status_code=400,
            detail="This scan has no saved frames. Please scan again. (ERR_NO_FRAMES)"
        )

    # Check which frames actually exist in storage
    frame_refs = [f["frame_ref"] for f in frames if f.get("frame_ref")]
    existing_refs, missing_refs = storage_service.check_frames_exist(frame_refs)

    if not existing_refs:
        job.status = "FAILED"
        job.stage = "FAILED"
        job.error = "This scan has no saved frames in storage. Please scan again. (ERR_NO_FRAMES)"
        job.stage_message = job.error
        db.commit()
        raise HTTPException(
            status_code=400,
            detail="This scan has no saved frames in storage. Please scan again. (ERR_NO_FRAMES)"
        )

    # Filter to only surviving frames and vectors
    existing_set = set(existing_refs)
    surviving_frames = [f for f in frames if f.get("frame_ref") in existing_set]
    surviving_vectors = [v for v in completed_vectors if v.get("frame_ref") in existing_set]

    # If only some frames survived, inform admin and require confirmation before proceeding
    if len(surviving_frames) < len(frames):
        missing_angles = [
            f.get("angle_tag", f"frame_{idx}")
            for idx, f in enumerate(frames)
            if f.get("frame_ref") not in existing_set
        ]
        if not (req and req.confirm_partial):
            return {
                "status": "CONFIRMATION_REQUIRED",
                "requires_confirmation": True,
                "surviving_count": len(surviving_frames),
                "total_count": len(frames),
                "missing_angles": missing_angles,
                "message": f"Only {len(surviving_frames)} of {len(frames)} frames found, some angles will be missing: {', '.join(missing_angles)}."
            }

    _cancelled_job_ids.discard(job.id)

    job.status = "PENDING"
    job.stage = "QUEUED"
    job.stage_message = f"Retry enqueued with {len(surviving_frames)} available frames. Resuming from last completed frame..."
    job.total = len(surviving_frames)
    job.done = len(surviving_vectors)
    job.frame_paths_json = _serialize_job_frame_state(surviving_frames, surviving_vectors, primary_url)
    job.error = None
    db.commit()

    logger.info(f"[scan_retry] Enqueueing retry for job_id={job.id} with {len(surviving_frames)} frames.")
    enqueue_scan_job(job.id)

    return {
        "status": "PENDING",
        "job_id": job.id,
        "total_frames": len(surviving_frames),
        "message": "Job re-queued successfully."
    }


@router.delete("/jobs/{job_id}")
def delete_scan_job(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_manager)
):
    """
    Deletes a scan job from the database.
    If the job is currently processing, it is cancelled first.
    Admin or Manager only.
    """
    job = db.query(ScanJob).filter(ScanJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Scan job not found.")

    from app.services.scan_worker import cancel_job
    cancel_job(job.id)

    db.delete(job)
    db.commit()

    return {
        "status": "DELETED",
        "job_id": job_id,
        "message": "Scan job successfully deleted."
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
        # Preprocess identically to enrollment (GrabCut on ~320px with neutral grey background 128,128,128)
        from app.services.scan_worker import preprocess_product_image_for_embedding
        raw_b64 = req.image_data_url
        if raw_b64.startswith("data:image"):
            raw_b64 = raw_b64.split(",", 1)[1]
        raw_pil = Image.open(io.BytesIO(base64.b64decode(raw_b64))).convert("RGB")
        preprocessed_img = preprocess_product_image_for_embedding(raw_pil)

        # Real ONNX INT8 CLIP ViT-B/32 embedding of the preprocessed camera frame
        query_vector = get_embedding(preprocessed_img)
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
    top_2 = top_matches[1] if len(top_matches) > 1 else None

    matched = False
    if req.target_barcode and top_1:
        matched = (top_1["barcode"] == req.target_barcode and top_1["similarity"] >= settings.CONFIDENCE_HIGH)
    elif top_1:
        matched = (top_1["similarity"] >= settings.CONFIDENCE_HIGH)

    scan_quality_recommendation = None
    if req.target_barcode:
        is_top1 = bool(top_1 and top_1.get("barcode") == req.target_barcode)
        margin = (top_1["similarity"] - top_2["similarity"]) if (top_1 and top_2) else 1.0
        if not is_top1 or margin < 0.10:
            scan_quality_recommendation = "Scan quality is low. Please rescan angles FRONT and LABEL_CLOSEUP."

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
        "message": message,
        "scan_quality_recommendation": scan_quality_recommendation
    }
