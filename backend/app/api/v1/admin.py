from datetime import datetime, date
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.database import get_db
from app.models.cart import Cart
from app.models.session import CartSession, CartItem
from app.models.alert import Alert, ReviewCase
from app.models.transaction import Transaction, ModelVersion, AuditLog
from app.models.product import Product
import secrets
import hashlib
import hmac
from app.config import settings
from app.schemas.cart import CartResponse, CartCreate, CartRegistrationResponse, CartStatusUpdate
from app.schemas.alert import AlertResponse, AlertResolutionRequest, ReviewCaseResponse, ReviewDecisionRequest
from app.services.alert_service import AlertService
from app.services.session_service import SessionService
from app.websocket.manager import ws_manager

router = APIRouter(prefix="/admin", tags=["Admin Portal"])

@router.get("/overview")
def get_overview(db: Session = Depends(get_db)):
    """Executive KPI metrics and live operational status."""
    total_carts = db.query(Cart).count()
    active_carts = db.query(Cart).filter(Cart.status.in_(["ACTIVE", "ALERT"])).count()
    open_incidents = db.query(Alert).filter(Alert.status == "OPEN").count()
    
    # Revenue today
    today_start = datetime.combine(date.today(), datetime.min.time())
    today_txs = db.query(Transaction).filter(
        Transaction.created_at >= today_start,
        Transaction.status == "SUCCESS"
    ).all()
    revenue_today = sum(tx.amount for tx in today_txs)
    
    # Active model accuracy
    active_model = db.query(ModelVersion).filter(ModelVersion.is_active == True).first()
    ai_accuracy = round(active_model.accuracy * 100, 1) if active_model else 98.4

    # Latest 5 incidents
    recent_alerts = db.query(Alert).order_by(Alert.created_at.desc()).limit(5).all()

    return {
        "active_carts": active_carts,
        "total_carts": total_carts,
        "revenue_today": round(revenue_today, 2),
        "open_incidents": open_incidents,
        "ai_accuracy": ai_accuracy,
        "recent_alerts": [
            {
                "id": a.id,
                "cart_number": a.cart.cart_number if a.cart else "N/A",
                "alert_type": a.alert_type,
                "severity": a.severity,
                "message": a.message,
                "status": a.status,
                "created_at": a.created_at
            }
            for a in recent_alerts
        ]
    }

def generate_cart_hmac(cart_number: str, qr_token: str) -> str:
    """Generate cryptographic HMAC signature for cart QR pairing link."""
    msg = f"{cart_number}:{qr_token}".encode("utf-8")
    return hmac.new(settings.QR_SIGNING_SECRET.encode("utf-8"), msg, hashlib.sha256).hexdigest()[:16]

def build_signed_connect_url(cart_number: str, qr_token: str) -> str:
    """Build full live public URL for shopper QR pairing with HMAC verification signature."""
    sig = generate_cart_hmac(cart_number, qr_token)
    return f"{settings.BASE_URL}/user/connect?cart={cart_number}&token={qr_token}&sig={sig}"

@router.get("/carts", response_model=List[CartResponse])
def list_carts(db: Session = Depends(get_db)):
    """Retrieve all physical carts with health, battery, camera, and signed connect URLs."""
    carts = db.query(Cart).order_by(Cart.cart_number.asc()).all()
    results = []
    for c in carts:
        active_sess = db.query(CartSession).filter(
            CartSession.cart_id == c.id,
            CartSession.status == "ACTIVE"
        ).first()
        
        # Ensure signed connect url is populated
        signed_url = c.signed_connect_url or build_signed_connect_url(c.cart_number, c.qr_code_token)
        if not c.signed_connect_url:
            c.signed_connect_url = signed_url
            db.commit()

        results.append(CartResponse(
            id=c.id,
            cart_number=c.cart_number,
            qr_code_token=c.qr_code_token,
            is_enabled=c.is_enabled,
            signed_connect_url=signed_url,
            status=c.status,
            battery_level=c.battery_level,
            camera_status=c.camera_status,
            last_heartbeat=c.last_heartbeat,
            active_session_id=active_sess.id if active_sess else None,
            item_count=active_sess.item_count if active_sess else 0,
            total_amount=active_sess.total_amount if active_sess else 0.0
        ))
    return results

@router.post("/carts", response_model=CartRegistrationResponse)
def register_cart(cart_in: CartCreate, db: Session = Depends(get_db)):
    """
    Register new smart cart in the fleet.
    Generates a secure random device token, stores ONLY its SHA-256 hash,
    and returns the raw device token once for configuration.
    """
    cart_num = cart_in.cart_number.upper().strip()
    existing = db.query(Cart).filter(Cart.cart_number == cart_num).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"Cart '{cart_num}' is already registered.")

    # 1. Generate secure random device token (shown ONCE, stored only as hash)
    raw_device_token = secrets.token_hex(16)
    token_hash = hashlib.sha256(raw_device_token.encode("utf-8")).hexdigest()

    # 2. Generate signed connect URL with HMAC
    qr_token = f"QR-{cart_num}"
    signed_url = build_signed_connect_url(cart_num, qr_token)

    new_cart = Cart(
        cart_number=cart_num,
        qr_code_token=qr_token,
        device_token_hash=token_hash,
        is_enabled=True,
        signed_connect_url=signed_url,
        status="IDLE",
        battery_level=100,
        camera_status="ONLINE"
    )
    db.add(new_cart)
    db.commit()
    db.refresh(new_cart)

    return CartRegistrationResponse(
        id=new_cart.id,
        cart_number=new_cart.cart_number,
        qr_code_token=new_cart.qr_code_token,
        is_enabled=new_cart.is_enabled,
        signed_connect_url=new_cart.signed_connect_url,
        status=new_cart.status,
        battery_level=new_cart.battery_level,
        camera_status=new_cart.camera_status,
        last_heartbeat=new_cart.last_heartbeat,
        device_token=raw_device_token
    )

@router.post("/carts/{cart_id}/regenerate-qr", response_model=CartResponse)
def regenerate_cart_qr(cart_id: str, db: Session = Depends(get_db)):
    """Regenerate cart QR token and HMAC signature, invalidating the previous QR code."""
    cart = db.query(Cart).filter((Cart.id == cart_id) | (Cart.cart_number == cart_id.upper())).first()
    if not cart:
        raise HTTPException(status_code=404, detail="Cart not found.")

    new_token = f"QR-{cart.cart_number}-{secrets.token_hex(3).upper()}"
    signed_url = build_signed_connect_url(cart.cart_number, new_token)

    cart.qr_code_token = new_token
    cart.signed_connect_url = signed_url
    db.commit()
    db.refresh(cart)

    return CartResponse(
        id=cart.id,
        cart_number=cart.cart_number,
        qr_code_token=cart.qr_code_token,
        is_enabled=cart.is_enabled,
        signed_connect_url=cart.signed_connect_url,
        status=cart.status,
        battery_level=cart.battery_level,
        camera_status=cart.camera_status,
        last_heartbeat=cart.last_heartbeat
    )

@router.post("/carts/{cart_id}/regenerate-token", response_model=CartRegistrationResponse)
def regenerate_device_token(cart_id: str, db: Session = Depends(get_db)):
    """Regenerate cart device token (stores new SHA-256 hash, returns raw token once)."""
    cart = db.query(Cart).filter((Cart.id == cart_id) | (Cart.cart_number == cart_id.upper())).first()
    if not cart:
        raise HTTPException(status_code=404, detail="Cart not found.")

    raw_token = secrets.token_hex(16)
    cart.device_token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    db.commit()
    db.refresh(cart)

    return CartRegistrationResponse(
        id=cart.id,
        cart_number=cart.cart_number,
        qr_code_token=cart.qr_code_token,
        is_enabled=cart.is_enabled,
        signed_connect_url=cart.signed_connect_url or build_signed_connect_url(cart.cart_number, cart.qr_code_token),
        status=cart.status,
        battery_level=cart.battery_level,
        camera_status=cart.camera_status,
        last_heartbeat=cart.last_heartbeat,
        device_token=raw_token
    )

@router.post("/carts/{cart_id}/toggle-status", response_model=CartResponse)
def toggle_cart_status(cart_id: str, db: Session = Depends(get_db)):
    """Toggle cart enabled/disabled status. Disabled carts cannot be paired by shoppers."""
    cart = db.query(Cart).filter((Cart.id == cart_id) | (Cart.cart_number == cart_id.upper())).first()
    if not cart:
        raise HTTPException(status_code=404, detail="Cart not found.")

    cart.is_enabled = not cart.is_enabled
    db.commit()
    db.refresh(cart)

    return CartResponse(
        id=cart.id,
        cart_number=cart.cart_number,
        qr_code_token=cart.qr_code_token,
        is_enabled=cart.is_enabled,
        signed_connect_url=cart.signed_connect_url,
        status=cart.status,
        battery_level=cart.battery_level,
        camera_status=cart.camera_status,
        last_heartbeat=cart.last_heartbeat
    )

@router.post("/carts/{cart_id}/reset-session")
async def reset_cart_session(cart_id: str, db: Session = Depends(get_db)):
    """
    Force-terminate and release any active session on the cart.
    Resets cart status to IDLE and frees it immediately for new shoppers.
    """
    cart = db.query(Cart).filter((Cart.id == cart_id) | (Cart.cart_number == cart_id.upper())).first()
    if not cart:
        raise HTTPException(status_code=404, detail="Cart not found.")

    # 1. Terminate any active sessions on this cart
    active_sessions = db.query(CartSession).filter(
        CartSession.cart_id == cart.id,
        CartSession.status == "ACTIVE"
    ).all()

    for s in active_sessions:
        s.status = "ABANDONED"
        s.ended_at = datetime.utcnow()

    # 2. Reset cart state
    cart.status = "IDLE"
    cart.last_heartbeat = datetime.utcnow()
    db.commit()
    db.refresh(cart)

    # 3. Notify connected WebSockets
    await ws_manager.broadcast_to_admin("CART_STATUS_CHANGE", {
        "cart_id": cart.id,
        "cart_number": cart.cart_number,
        "status": "IDLE",
        "session_id": None
    })
    await ws_manager.broadcast_to_cart(cart.id, "SESSION_RESET_BY_ADMIN", {
        "cart_id": cart.id,
        "cart_number": cart.cart_number,
        "message": "Cart session has been reset by store administration. Cart is now available."
    })

    return {
        "status": "SUCCESS",
        "message": f"Active session on cart '{cart.cart_number}' successfully released. The cart is now available.",
        "cart_id": cart.id,
        "cart_number": cart.cart_number,
        "cart_status": cart.status
    }

@router.patch("/carts/{cart_id}", response_model=CartResponse)
async def update_cart_details(cart_id: str, update_in: CartStatusUpdate, db: Session = Depends(get_db)):
    """
    Edit cart attributes (cart_number, status, is_enabled, battery_level, camera_status).
    If status is set to IDLE, any lingering active session is automatically cleared.
    """
    cart = db.query(Cart).filter((Cart.id == cart_id) | (Cart.cart_number == cart_id.upper())).first()
    if not cart:
        raise HTTPException(status_code=404, detail="Cart not found.")

    if update_in.cart_number is not None and update_in.cart_number.strip():
        new_num = update_in.cart_number.upper().strip()
        if new_num != cart.cart_number:
            existing = db.query(Cart).filter(Cart.cart_number == new_num).first()
            if existing:
                raise HTTPException(status_code=400, detail=f"Cart number '{new_num}' is already in use.")
            cart.cart_number = new_num
            # Regenerate signed url for new cart number
            cart.signed_connect_url = build_signed_connect_url(cart.cart_number, cart.qr_code_token)

    if update_in.status is not None:
        valid_statuses = ["IDLE", "ACTIVE", "ALERT", "MAINTENANCE"]
        if update_in.status.upper() in valid_statuses:
            cart.status = update_in.status.upper()
            if cart.status == "IDLE":
                active_sessions = db.query(CartSession).filter(
                    CartSession.cart_id == cart.id,
                    CartSession.status == "ACTIVE"
                ).all()
                for s in active_sessions:
                    s.status = "ABANDONED"
                    s.ended_at = datetime.utcnow()

    if update_in.is_enabled is not None:
        cart.is_enabled = update_in.is_enabled

    if update_in.battery_level is not None:
        cart.battery_level = update_in.battery_level

    if update_in.camera_status is not None:
        cart.camera_status = update_in.camera_status

    db.commit()
    db.refresh(cart)

    active_sess = db.query(CartSession).filter(
        CartSession.cart_id == cart.id,
        CartSession.status == "ACTIVE"
    ).first()

    await ws_manager.broadcast_to_admin("CART_STATUS_CHANGE", {
        "cart_id": cart.id,
        "cart_number": cart.cart_number,
        "status": cart.status,
        "session_id": active_sess.id if active_sess else None
    })

    return CartResponse(
        id=cart.id,
        cart_number=cart.cart_number,
        qr_code_token=cart.qr_code_token,
        is_enabled=cart.is_enabled,
        signed_connect_url=cart.signed_connect_url or build_signed_connect_url(cart.cart_number, cart.qr_code_token),
        status=cart.status,
        battery_level=cart.battery_level,
        camera_status=cart.camera_status,
        last_heartbeat=cart.last_heartbeat,
        active_session_id=active_sess.id if active_sess else None,
        item_count=active_sess.item_count if active_sess else 0,
        total_amount=active_sess.total_amount if active_sess else 0.0
    )


@router.get("/alerts", response_model=List[AlertResponse])
def list_alerts(
    status: Optional[str] = Query(None, description="Filter by OPEN, RESOLVED, DISMISSED"),
    db: Session = Depends(get_db)
):
    """Retrieve security incidents and mismatch alerts."""
    query = db.query(Alert)
    if status and status != "ALL":
        query = query.filter(Alert.status == status)
    alerts = query.order_by(Alert.created_at.desc()).all()
    
    return [
        AlertResponse(
            id=a.id,
            cart_id=a.cart_id,
            cart_number=a.cart.cart_number if a.cart else "N/A",
            session_id=a.session_id,
            alert_type=a.alert_type,
            severity=a.severity,
            message=a.message,
            evidence_snapshot_url=a.evidence_snapshot_url,
            status=a.status,
            resolved_by=a.resolved_by,
            resolution_notes=a.resolution_notes,
            created_at=a.created_at,
            resolved_at=a.resolved_at
        )
        for a in alerts
    ]

@router.patch("/alerts/{alert_id}", response_model=AlertResponse)
async def resolve_alert(alert_id: str, req: AlertResolutionRequest, db: Session = Depends(get_db)):
    """Resolve or dismiss an active incident."""
    alert = await AlertService.resolve_alert(
        db=db,
        alert_id=alert_id,
        user_id="STAFF_MANUAL",
        notes=req.resolution_notes,
        action=req.action
    )
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    
    return AlertResponse(
        id=alert.id,
        cart_id=alert.cart_id,
        cart_number=alert.cart.cart_number if alert.cart else "N/A",
        session_id=alert.session_id,
        alert_type=alert.alert_type,
        severity=alert.severity,
        message=alert.message,
        evidence_snapshot_url=alert.evidence_snapshot_url,
        status=alert.status,
        resolved_by=alert.resolved_by,
        resolution_notes=alert.resolution_notes,
        created_at=alert.created_at,
        resolved_at=alert.resolved_at
    )

@router.get("/review-queue", response_model=List[ReviewCaseResponse])
def get_review_queue(db: Session = Depends(get_db)):
    """Retrieve low-confidence cases requiring staff human-in-the-loop validation."""
    cases = db.query(ReviewCase).filter(ReviewCase.status == "PENDING").all()
    result = []
    for c in cases:
        scanned_prod = None
        if c.scanned_barcode:
            scanned_prod = db.query(Product).filter(Product.barcode == c.scanned_barcode).first()
        
        cart = db.query(Cart).filter(Cart.id == c.cart_id).first()
        result.append(ReviewCaseResponse(
            id=c.id,
            alert_id=c.alert_id,
            cart_id=c.cart_id,
            cart_number=cart.cart_number if cart else "N/A",
            scanned_barcode=c.scanned_barcode,
            scanned_product_name=scanned_prod.name if scanned_prod else None,
            scanned_product_image=scanned_prod.primary_image_url if scanned_prod else None,
            predicted_product_id=c.predicted_product_id,
            predicted_product_name=c.predicted_product.name if c.predicted_product else None,
            confidence=c.confidence,
            evidence_image_url=c.evidence_image_url,
            status=c.status,
            created_at=c.created_at
        ))
    return result

@router.post("/review-queue/{case_id}/decision")
async def submit_review_decision(case_id: str, req: ReviewDecisionRequest, db: Session = Depends(get_db)):
    """Approve or reject a low-confidence detection."""
    case = db.query(ReviewCase).filter(ReviewCase.id == case_id).first()
    if not case:
        raise HTTPException(status_code=404, detail="Review case not found")

    case.status = "APPROVED" if req.decision == "APPROVE" else "REJECTED"
    case.feedback_saved_for_training = req.save_for_training
    
    # If approved, resolve the associated alert
    if req.decision == "APPROVE":
        await AlertService.resolve_alert(
            db=db,
            alert_id=case.alert_id,
            user_id="STAFF_REVIEWER",
            notes=f"Staff approved match. {req.notes or ''}",
            action="RESOLVED"
        )
        # If there's an active session with this barcode in PENDING, verify it!
        if case.scanned_barcode:
            active_session = db.query(CartSession).filter(
                CartSession.cart_id == case.cart_id,
                CartSession.status == "ACTIVE"
            ).first()
            if active_session:
                await SessionService.verify_item_placement(
                    db=db,
                    session_id=active_session.id,
                    barcode=case.scanned_barcode,
                    confidence=1.0,
                    evidence_url=case.evidence_image_url
                )
    else:
        # Rejected
        alert = db.query(Alert).filter(Alert.id == case.alert_id).first()
        if alert:
            alert.status = "IN_REVIEW"
            alert.resolution_notes = f"Staff confirmed mismatch. Security intervention required. {req.notes or ''}"

    db.commit()
    return {"status": "SUCCESS", "message": f"Review case {case.status.lower()}."}

@router.get("/models")
def list_models(db: Session = Depends(get_db)):
    """List AI model checkpoints, accuracy stats, and active version."""
    models = db.query(ModelVersion).order_by(ModelVersion.created_at.desc()).all()
    return models

@router.post("/models/{model_id}/activate")
def activate_model(model_id: str, db: Session = Depends(get_db)):
    """One-click rollback or activation of an AI model version."""
    target_model = db.query(ModelVersion).filter(ModelVersion.id == model_id).first()
    if not target_model:
        raise HTTPException(status_code=404, detail="Model version not found")

    # Deactivate all others
    db.query(ModelVersion).update({ModelVersion.is_active: False})
    target_model.is_active = True
    db.commit()
    return {"status": "SUCCESS", "message": f"Activated model {target_model.version_tag}."}

@router.get("/reports")
def get_reports(db: Session = Depends(get_db)):
    """Sales, mismatch, and theft prevention statistical report."""
    total_txs = db.query(Transaction).filter(Transaction.status == "SUCCESS").all()
    gross_sales = sum(tx.amount for tx in total_txs)
    
    total_alerts = db.query(Alert).count()
    unscanned_alerts = db.query(Alert).filter(Alert.alert_type == "UNSCANNED_ITEM").count()
    mismatch_alerts = db.query(Alert).filter(Alert.alert_type == "MISMATCH_ITEM").count()

    return {
        "total_transactions": len(total_txs),
        "gross_sales": round(gross_sales, 2),
        "theft_prevention_stats": {
            "total_alerts_intercepted": total_alerts,
            "unscanned_items_prevented": unscanned_alerts,
            "mismatch_items_caught": mismatch_alerts,
            "estimated_loss_prevented": round(unscanned_alerts * 125.0 + mismatch_alerts * 85.0, 2)
        }
    }
