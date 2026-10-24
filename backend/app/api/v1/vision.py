import os
import io
import uuid
import base64
import json
import logging
from typing import Optional, List, Dict, Any, Tuple
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from PIL import Image, ImageEnhance, ImageFilter
import numpy as np
import cv2

from app.database import get_db
from app.config import settings
from app.models.cart import Cart
from app.models.session import CartSession, CartItem
from app.models.product import Product, ProductImage, ProductEmbedding
from app.services.session_service import SessionService
from app.services.alert_service import AlertService
from app.ai.feature_extractor import get_embedding, MODEL_NAME, MODEL_VERSION, VECTOR_DIM
from app.ai.vector_store import VectorStoreMatcher

logger = logging.getLogger("smartcart.vision")

router = APIRouter(prefix="/vision", tags=["Vision & AI Real Pipeline"])

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
async def simulate_cart_camera_action(req: SimulateActionRequest, db: Session = Depends(get_db)):
    """Simulate cart camera detections and physical cart events for testing without hardware."""
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
def save_360_scan_embeddings(product_id: str, req: Complete360ScanRequest, db: Session = Depends(get_db)):
    """
    Ingest real 360-degree camera captures:
    1. Decode real base64 frames and save JPEG files to disk.
    2. Run background removal and augmentations.
    3. Generate real CLIP ViT-B/32 512-dim normalized embeddings.
    4. Persist in pgvector and disk index. Replaces old vectors on re-scan.
    """
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    if not req.captures:
        raise HTTPException(status_code=400, detail="No camera frames provided in 360 scan payload.")

    # Re-scan support: delete existing captures and embeddings
    VectorStoreMatcher.delete_embeddings_for_product(db, product.id)
    db.query(ProductImage).filter(ProductImage.product_id == product.id, ProductImage.is_360_scan == True).delete()

    os.makedirs(settings.CATALOG_DIR, exist_ok=True)
    saved_images_count = 0
    stored_vectors_count = 0
    primary_image_set = False

    for cap in req.captures:
        # Decode base64 image data URL
        raw_b64 = cap.image_data_url
        if raw_b64.startswith("data:image"):
            parts = raw_b64.split(",", 1)
            if len(parts) == 2:
                raw_b64 = parts[1]

        try:
            image_bytes = base64.b64decode(raw_b64)
            pil_img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        except Exception as e:
            logger.warning(f"Failed to decode frame for angle {cap.angle_tag}: {e}")
            continue

        # Save primary real image to disk
        filename = f"{product.barcode}_{cap.angle_tag}_{uuid.uuid4().hex[:8]}.jpg"
        file_path = os.path.join(settings.CATALOG_DIR, filename)
        pil_img.save(file_path, "JPEG", quality=92)
        saved_images_count += 1

        # Generate optimized persistent data URL for database storage
        thumb_img = pil_img.copy()
        thumb_img.thumbnail((400, 400))
        thumb_buffer = io.BytesIO()
        thumb_img.save(thumb_buffer, format="JPEG", quality=80)
        persistent_image_url = f"data:image/jpeg;base64,{base64.b64encode(thumb_buffer.getvalue()).decode('utf-8')}"

        prod_img = ProductImage(
            product_id=product.id,
            image_url=persistent_image_url,
            angle_tag=cap.angle_tag,
            is_360_scan=True
        )
        db.add(prod_img)

        # Set as primary image if Front view or not yet set
        if not primary_image_set or cap.angle_tag.upper() == "FRONT":
            product.primary_image_url = persistent_image_url
            primary_image_set = True

        # Generate background-removed image
        matted_img = _remove_background(pil_img)

        # Generate light realistic augmentations
        augmented_set = _generate_augmentations(pil_img)
        augmented_set.append(("MATTED", matted_img))

        for aug_tag, variant_img in augmented_set:
            try:
                # Real CLIP ViT-B/32 embedding
                vec = get_embedding(variant_img)
                full_tag = f"{cap.angle_tag}_{aug_tag}"
                VectorStoreMatcher.store_embedding(
                    db=db,
                    product_id=product.id,
                    barcode=product.barcode,
                    angle_tag=full_tag,
                    vector=vec,
                    image_path=file_path,
                    model_name=MODEL_NAME,
                    model_version=MODEL_VERSION,
                    vector_dim=VECTOR_DIM,
                    commit=False
                )
                stored_vectors_count += 1
            except Exception as e:
                logger.error(f"Error computing embedding for {product.barcode} ({full_tag}): {e}")

    db.commit()
    db.refresh(product)
    VectorStoreMatcher.sync_to_disk(db)

    return {
        "status": "SUCCESS",
        "message": f"Successfully enrolled real 360-degree embeddings for '{product.name}'.",
        "product_id": product.id,
        "barcode": product.barcode,
        "product_status": "AI Enrolled",
        "real_frames_saved": saved_images_count,
        "total_embeddings_stored": stored_vectors_count,
        "model_name": MODEL_NAME,
        "vector_dim": VECTOR_DIM,
        "product": {
            "id": product.id,
            "barcode": product.barcode,
            "name": product.name,
            "brand": product.brand,
            "category": product.category,
            "price": product.price,
            "discount_price": product.discount_price,
            "weight_grams": product.weight_grams,
            "tax_rate": product.tax_rate,
            "stock_quantity": product.stock_quantity,
            "primary_image_url": product.primary_image_url,
            "is_active": product.is_active,
            "has_embeddings": True
        }
    }

@router.post("/products/preview-test")
def preview_recognition_test(req: PreviewTestRequest, db: Session = Depends(get_db)):
    """
    Live real camera preview test:
    Admin holds product in front of webcam, system computes real CLIP embedding
    and returns top-3 nearest catalog matches with real cosine similarity scores.
    """
    if not req.image_data_url or len(req.image_data_url) < 100:
        raise HTTPException(status_code=400, detail="Invalid camera frame received. Please point your webcam at the product.")

    try:
        # Real CLIP ViT-B/32 embedding of the live camera frame
        query_vector = get_embedding(req.image_data_url)
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
