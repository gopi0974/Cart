from datetime import datetime, date
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func
from app.database import get_db
from app.models.cart import Cart
from app.models.session import CartSession, CartItem
from app.models.alert import Alert, ReviewCase
from app.models.transaction import Transaction, ModelVersion, AuditLog
from app.models.product import Product
import json
import secrets
import hashlib
import hmac
from app.config import settings, is_valid_base_url
from app.models.user import User
from app.api.v1.auth import get_current_user, require_admin_or_manager
from app.schemas.cart import CartResponse, CartCreate, CartRegistrationResponse, CartStatusUpdate
from app.schemas.alert import AlertResponse, AlertResolutionRequest, ReviewCaseResponse, ReviewDecisionRequest
from app.services.alert_service import AlertService
from app.services.session_service import SessionService
from app.websocket.manager import ws_manager

router = APIRouter(prefix="/admin", tags=["Admin Portal"], dependencies=[Depends(get_current_user)])

@router.get("/overview")
def get_overview(db: Session = Depends(get_db)):
    """Executive KPI metrics and live operational status."""
    total_carts = db.query(Cart).count()
    active_carts = db.query(Cart).filter(Cart.status.in_(["ACTIVE", "ALERT"])).count()
    open_incidents = db.query(Alert).filter(Alert.status == "OPEN").count()
    
    # Revenue today (single aggregate query)
    today_start = datetime.combine(date.today(), datetime.min.time())
    revenue_today = db.query(func.coalesce(func.sum(Transaction.amount), 0.0)).filter(
        Transaction.created_at >= today_start,
        Transaction.status == "SUCCESS"
    ).scalar() or 0.0
    
    # Active model accuracy
    active_model = db.query(ModelVersion).filter(ModelVersion.is_active == True).first()
    ai_accuracy = round(active_model.accuracy * 100, 1) if active_model else 98.4

    # Latest 5 incidents (eager cart loading eliminates N+1 queries)
    recent_alerts = db.query(Alert).options(joinedload(Alert.cart)).order_by(Alert.created_at.desc()).limit(5).all()

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

def build_signed_connect_url(cart_number: str, qr_token: str) -> Optional[str]:
    """
    Build full live public URL for shopper QR pairing with HMAC verification signature.
    Format: BASE_URL/user/connect?cart=<cart_number>&sig=<HMAC signature>
    Returns None if BASE_URL is missing or contains localhost/127.0.0.1 in production.
    """
    base_url = (settings.BASE_URL or "").strip().rstrip("/")
    if not is_valid_base_url(base_url, demo_mode=settings.DEMO_MODE):
        return None
    sig = generate_cart_hmac(cart_number, qr_token)
    return f"{base_url}/user/connect?cart={cart_number}&sig={sig}"

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
        
        # Build signed connect url dynamically using current settings.BASE_URL
        signed_url = build_signed_connect_url(c.cart_number, c.qr_code_token)
        if c.signed_connect_url != signed_url:
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
def register_cart(
    cart_in: CartCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_manager)
):
    """
    Register new smart cart in the fleet (Admin and Manager only).
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
    db.flush()

    audit = AuditLog(
        user_id=current_user.id,
        action="REGISTER_CART",
        entity_type="CART",
        entity_id=new_cart.id,
        details_json=json.dumps({
            "cart_number": new_cart.cart_number,
            "registered_by": current_user.email,
            "role": current_user.role,
            "timestamp": datetime.utcnow().isoformat()
        }),
        created_at=datetime.utcnow()
    )
    db.add(audit)
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
def regenerate_cart_qr(
    cart_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_manager)
):
    """Regenerate cart QR token and HMAC signature, invalidating previous QR code (Admin and Manager only)."""
    cart = db.query(Cart).filter((Cart.id == cart_id) | (Cart.cart_number == cart_id.upper())).first()
    if not cart:
        raise HTTPException(status_code=404, detail="Cart not found.")

    new_token = f"QR-{cart.cart_number}-{secrets.token_hex(3).upper()}"
    signed_url = build_signed_connect_url(cart.cart_number, new_token)

    cart.qr_code_token = new_token
    cart.signed_connect_url = signed_url

    audit = AuditLog(
        user_id=current_user.id,
        action="REGENERATE_CART_QR",
        entity_type="CART",
        entity_id=cart.id,
        details_json=json.dumps({
            "cart_number": cart.cart_number,
            "new_qr_token": new_token,
            "regenerated_by": current_user.email,
            "timestamp": datetime.utcnow().isoformat()
        }),
        created_at=datetime.utcnow()
    )
    db.add(audit)
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
def regenerate_device_token(
    cart_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_manager)
):
    """Regenerate cart device token (stores new SHA-256 hash, returns raw token once) (Admin and Manager only)."""
    cart = db.query(Cart).filter((Cart.id == cart_id) | (Cart.cart_number == cart_id.upper())).first()
    if not cart:
        raise HTTPException(status_code=404, detail="Cart not found.")

    raw_token = secrets.token_hex(16)
    cart.device_token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()

    audit = AuditLog(
        user_id=current_user.id,
        action="REGENERATE_DEVICE_TOKEN",
        entity_type="CART",
        entity_id=cart.id,
        details_json=json.dumps({
            "cart_number": cart.cart_number,
            "regenerated_by": current_user.email,
            "timestamp": datetime.utcnow().isoformat()
        }),
        created_at=datetime.utcnow()
    )
    db.add(audit)
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
def toggle_cart_status(
    cart_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_manager)
):
    """Toggle cart enabled/disabled status. Disabled carts cannot be paired (Admin and Manager only)."""
    cart = db.query(Cart).filter((Cart.id == cart_id) | (Cart.cart_number == cart_id.upper())).first()
    if not cart:
        raise HTTPException(status_code=404, detail="Cart not found.")

    cart.is_enabled = not cart.is_enabled
    action_type = "ENABLE_CART" if cart.is_enabled else "DISABLE_CART"

    audit = AuditLog(
        user_id=current_user.id,
        action=action_type,
        entity_type="CART",
        entity_id=cart.id,
        details_json=json.dumps({
            "cart_number": cart.cart_number,
            "is_enabled": cart.is_enabled,
            "toggled_by": current_user.email,
            "timestamp": datetime.utcnow().isoformat()
        }),
        created_at=datetime.utcnow()
    )
    db.add(audit)
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
async def reset_cart_session(
    cart_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_manager)
):
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
async def update_cart_details(
    cart_id: str,
    update_in: CartStatusUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_manager)
):
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
    limit: int = Query(100, ge=1, le=500, description="Page limit"),
    offset: int = Query(0, ge=0, description="Page offset"),
    db: Session = Depends(get_db)
):
    """Retrieve security incidents and mismatch alerts with eager cart loading."""
    query = db.query(Alert).options(joinedload(Alert.cart))
    if status and status != "ALL":
        query = query.filter(Alert.status == status)
    alerts = query.order_by(Alert.created_at.desc()).offset(offset).limit(limit).all()
    
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
async def resolve_alert(
    alert_id: str,
    req: AlertResolutionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Resolve or dismiss an active incident (All staff)."""
    alert = await AlertService.resolve_alert(
        db=db,
        alert_id=alert_id,
        user_id=current_user.id,
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

class ForceRemoveRequest(BaseModel):
    reason: str
    cart_item_id: Optional[str] = None
    barcode: Optional[str] = None

@router.post("/alerts/{alert_id}/force-remove")
async def force_remove_from_alert(
    alert_id: str,
    req: ForceRemoveRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_manager)
):
    """
    Store staff force-removes an item associated with an active alert (Admin and Manager only).
    Drops item from cart/bill, resolves alert, logs audit entry, and notifies shopper.
    """
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found.")

    if not alert.session_id:
        raise HTTPException(status_code=400, detail="Alert is not tied to an active session.")

    session = db.query(CartSession).filter(CartSession.id == alert.session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Active session not found.")

    # Locate item to force-remove
    item = None
    if req.cart_item_id:
        item = db.query(CartItem).filter(CartItem.id == req.cart_item_id, CartItem.session_id == session.id).first()
    elif req.barcode:
        item = db.query(CartItem).join(Product).filter(
            CartItem.session_id == session.id,
            Product.barcode == req.barcode,
            CartItem.status != "REMOVED"
        ).first()

    if not item:
        # Check if an item in session is in REMOVED_PENDING_RESCAN or REMOVING
        item = db.query(CartItem).filter(
            CartItem.session_id == session.id,
            CartItem.status.in_(["REMOVED_PENDING_RESCAN", "REMOVING", "WARNING_MISMATCH", "WARNING_UNSCANNED"])
        ).first()

    if not item:
        # Fallback to the latest item in cart
        item = db.query(CartItem).filter(
            CartItem.session_id == session.id,
            CartItem.status != "REMOVED"
        ).order_by(CartItem.scanned_at.desc()).first()

    if not item:
        raise HTTPException(status_code=400, detail="No active item found in session to force remove.")

    prod_name = item.product.name if item.product else "Item"
    prev_status = item.status
    item.status = "REMOVED"
    db.flush()
    SessionService.recalculate_session_totals(db, session)

    actor_id = current_user.id
    actor_name = current_user.full_name or current_user.email

    # Resolve this alert and any related removal alerts
    alert.status = "RESOLVED"
    alert.resolved_by = actor_id
    alert.resolution_notes = f"Force-removed by {current_user.role}. Reason: {req.reason}"
    alert.resolved_at = datetime.utcnow()

    # Log to AuditLog
    audit = AuditLog(
        user_id=actor_id,
        action="FORCE_REMOVE_ALERT_ITEM",
        entity_type="CART_ITEM",
        entity_id=item.id,
        details_json=json.dumps({
            "staff_name": actor_name,
            "staff_email": current_user.email,
            "staff_role": current_user.role,
            "product_name": prod_name,
            "product_barcode": item.product.barcode if item.product else None,
            "session_id": session.id,
            "cart_number": alert.cart.cart_number if alert.cart else None,
            "alert_id": alert.id,
            "reason": req.reason,
            "previous_status": prev_status
        }),
        created_at=datetime.utcnow()
    )
    db.add(audit)
    db.commit()

    # Broadcast cleared warning and updated totals to cart WebSocket
    await ws_manager.broadcast_to_cart(session.cart_id, "WARNING_CLEARED", {
        "message": f"'{prod_name}' force-removed by store staff.",
        "product_name": prod_name,
        "subtotal": session.subtotal_amount,
        "total": session.total_amount
    })

    return {
        "status": "SUCCESS",
        "message": f"'{prod_name}' successfully force-removed from session.",
        "product_name": prod_name,
        "new_subtotal": session.subtotal_amount,
        "new_total": session.total_amount
    }

@router.post("/sessions/{session_id}/items/{item_id}/force-remove")
async def force_remove_session_item(
    session_id: str,
    item_id: str,
    req: ForceRemoveRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_manager)
):
    """
    Store staff force-removes an item directly from Live Cart Monitor (Admin and Manager only).
    """
    session = db.query(CartSession).filter(CartSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Cart session not found.")

    item = db.query(CartItem).filter(CartItem.id == item_id, CartItem.session_id == session.id).first()
    if not item or item.status == "REMOVED":
        raise HTTPException(status_code=404, detail="Item not found or already removed.")

    prod_name = item.product.name if item.product else "Item"
    prev_status = item.status
    item.status = "REMOVED"
    db.flush()
    SessionService.recalculate_session_totals(db, session)

    actor_id = current_user.id
    actor_name = current_user.full_name or current_user.email

    # Resolve open alerts for this session
    open_alerts = db.query(Alert).filter(
        Alert.session_id == session.id,
        Alert.status == "OPEN"
    ).all()
    for al in open_alerts:
        al.status = "RESOLVED"
        al.resolved_by = actor_id
        al.resolution_notes = f"Item force-removed by {current_user.role}. Reason: {req.reason}"
        al.resolved_at = datetime.utcnow()

    audit = AuditLog(
        user_id=actor_id,
        action="FORCE_REMOVE_SESSION_ITEM",
        entity_type="CART_ITEM",
        entity_id=item.id,
        details_json=json.dumps({
            "staff_name": actor_name,
            "staff_email": current_user.email,
            "staff_role": current_user.role,
            "product_name": prod_name,
            "product_barcode": item.product.barcode if item.product else None,
            "session_id": session.id,
            "cart_number": session.cart.cart_number if session.cart else None,
            "reason": req.reason,
            "previous_status": prev_status
        }),
        created_at=datetime.utcnow()
    )
    db.add(audit)
    db.commit()

    await ws_manager.broadcast_to_cart(session.cart_id, "WARNING_CLEARED", {
        "message": f"'{prod_name}' force-removed by store staff.",
        "product_name": prod_name,
        "subtotal": session.subtotal_amount,
        "total": session.total_amount
    })

    return {
        "status": "SUCCESS",
        "message": f"'{prod_name}' force-removed by staff.",
        "product_name": prod_name,
        "new_subtotal": session.subtotal_amount,
        "new_total": session.total_amount
    }

@router.get("/sessions/{session_id}/items")
def get_session_items(session_id: str, db: Session = Depends(get_db)):
    """Retrieve all items for a cart session, including REMOVING, REMOVED_PENDING_RESCAN, and camera snapshots."""
    session = db.query(CartSession).filter(CartSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Cart session not found.")
    
    items = db.query(CartItem).options(joinedload(CartItem.product)).filter(CartItem.session_id == session.id).order_by(CartItem.scanned_at.desc()).all()
    res = []
    for itm in items:
        p = itm.product
        res.append({
            "id": itm.id,
            "product_id": p.id if p else None,
            "product_name": p.name if p else "Item",
            "product_barcode": p.barcode if p else "",
            "product_image_url": p.primary_image_url if p else None,
            "brand": p.brand if p else "",
            "category": p.category if p else "",
            "quantity": itm.quantity,
            "unit_price": itm.unit_price,
            "status": itm.status,
            "scanned_at": itm.scanned_at.isoformat() if itm.scanned_at else None,
            "verified_at": itm.verified_at.isoformat() if itm.verified_at else None,
            "confidence_score": itm.confidence_score,
            "verification_evidence_url": itm.verification_evidence_url
        })
    return {
        "session_id": session.id,
        "cart_id": session.cart_id,
        "status": session.status,
        "item_count": session.item_count,
        "subtotal_amount": session.subtotal_amount,
        "total_amount": session.total_amount,
        "items": res
    }


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
async def submit_review_decision(
    case_id: str,
    req: ReviewDecisionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Approve or reject a low-confidence detection (All staff)."""
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
            user_id=current_user.id,
            notes=f"Staff approved match ({current_user.email}). {req.notes or ''}",
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

class ModelThresholdsUpdate(BaseModel):
    confidence_high: float
    confidence_low: float

@router.get("/model-health")
def get_model_health(db: Session = Depends(get_db)):
    """Health endpoint returning real embedding model name, vector dim, products enrolled, vectors count, and last enrollment time."""
    import os
    from app.ai.feature_extractor import MODEL_NAME, MODEL_VERSION, VECTOR_DIM, LOCAL_MODEL_DIR, FALLBACK_MODEL_DIR
    from app.models.product import ProductEmbedding

    total_vectors = db.query(ProductEmbedding).count()
    enrolled_products = db.query(func.count(func.distinct(ProductEmbedding.product_id))).scalar() or 0
    latest_emb = db.query(ProductEmbedding).order_by(ProductEmbedding.created_at.desc()).first()
    last_enrollment_time = latest_emb.created_at.isoformat() if (latest_emb and latest_emb.created_at) else None

    offline_cached = (os.path.exists(LOCAL_MODEL_DIR) and len(os.listdir(LOCAL_MODEL_DIR)) > 0) or \
                     (os.path.exists(FALLBACK_MODEL_DIR) and len(os.listdir(FALLBACK_MODEL_DIR)) > 0)

    return {
        "status": "HEALTHY",
        "model_name": MODEL_NAME,
        "model_version": MODEL_VERSION,
        "vector_dimension": VECTOR_DIM,
        "enrolled_products_count": enrolled_products,
        "total_vectors_count": total_vectors,
        "last_enrollment_time": last_enrollment_time,
        "offline_cached": offline_cached,
        "confidence_high": settings.CONFIDENCE_HIGH,
        "confidence_low": settings.CONFIDENCE_LOW,
    }

@router.post("/model-thresholds")
def update_model_thresholds(
    req: ModelThresholdsUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_manager)
):
    """Dynamically configure high and low verification thresholds."""
    if not (0.0 <= req.confidence_low < req.confidence_high <= 1.0):
        raise HTTPException(status_code=400, detail="Thresholds must satisfy 0.0 <= low < high <= 1.0")
    old_high = settings.CONFIDENCE_HIGH
    old_low = settings.CONFIDENCE_LOW
    settings.CONFIDENCE_HIGH = round(req.confidence_high, 4)
    settings.CONFIDENCE_LOW = round(req.confidence_low, 4)

    audit = AuditLog(
        user_id=current_user.id,
        action="UPDATE_MODEL_THRESHOLDS",
        entity_type="SYSTEM",
        entity_id="model_thresholds",
        details_json=json.dumps({
            "old_confidence_high": old_high,
            "old_confidence_low": old_low,
            "confidence_high": settings.CONFIDENCE_HIGH,
            "confidence_low": settings.CONFIDENCE_LOW,
            "updated_by_email": current_user.email,
            "updated_by_role": current_user.role,
            "timestamp": datetime.utcnow().isoformat()
        }),
        created_at=datetime.utcnow()
    )
    db.add(audit)
    db.commit()

    return {
        "status": "SUCCESS",
        "confidence_high": settings.CONFIDENCE_HIGH,
        "confidence_low": settings.CONFIDENCE_LOW
    }

@router.get("/models")
def list_models(db: Session = Depends(get_db)):
    """List AI model checkpoints, accuracy stats, and active version."""
    models = db.query(ModelVersion).order_by(ModelVersion.created_at.desc()).all()
    return models

@router.post("/models/{model_id}/activate")
def activate_model(
    model_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_manager)
):
    """One-click activation of an AI model version (Admin and Manager only)."""
    target_model = db.query(ModelVersion).filter(ModelVersion.id == model_id).first()
    if not target_model:
        raise HTTPException(status_code=404, detail="Model version not found")

    # Deactivate all others
    db.query(ModelVersion).update({ModelVersion.is_active: False})
    target_model.is_active = True

    audit = AuditLog(
        user_id=current_user.id,
        action="ACTIVATE_MODEL",
        entity_type="MODEL",
        entity_id=target_model.id,
        details_json=json.dumps({
            "version_tag": target_model.version_tag,
            "accuracy": target_model.accuracy,
            "activated_by_email": current_user.email,
            "activated_by_role": current_user.role,
            "timestamp": datetime.utcnow().isoformat()
        }),
        created_at=datetime.utcnow()
    )
    db.add(audit)
    db.commit()

    return {"status": "SUCCESS", "message": f"Activated model {target_model.version_tag}."}

@router.post("/models/{model_id}/rollback")
@router.post("/models/rollback")
def rollback_model(
    model_id: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_manager)
):
    """Roll back AI model to a specified or previous checkpoint (Admin and Manager only)."""
    if model_id:
        target_model = db.query(ModelVersion).filter(ModelVersion.id == model_id).first()
    else:
        # Pick the latest inactive model version
        target_model = db.query(ModelVersion).filter(ModelVersion.is_active == False).order_by(ModelVersion.created_at.desc()).first()

    if not target_model:
        raise HTTPException(status_code=404, detail="Target model version for rollback not found.")

    current_active = db.query(ModelVersion).filter(ModelVersion.is_active == True).first()
    prev_tag = current_active.version_tag if current_active else "None"

    db.query(ModelVersion).update({ModelVersion.is_active: False})
    target_model.is_active = True

    audit = AuditLog(
        user_id=current_user.id,
        action="ROLLBACK_MODEL",
        entity_type="MODEL",
        entity_id=target_model.id,
        details_json=json.dumps({
            "previous_version": prev_tag,
            "new_version": target_model.version_tag,
            "rolled_back_by_email": current_user.email,
            "rolled_back_by_role": current_user.role,
            "timestamp": datetime.utcnow().isoformat()
        }),
        created_at=datetime.utcnow()
    )
    db.add(audit)
    db.commit()

    return {
        "status": "SUCCESS",
        "message": f"Successfully rolled back model from {prev_tag} to {target_model.version_tag}.",
        "active_model": target_model.version_tag
    }

@router.get("/audit-logs")
def get_audit_logs(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    action: Optional[str] = Query(None, description="Filter by action type"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_manager)
):
    """Retrieve immutable system audit logs (Admin and Manager only)."""
    query = db.query(AuditLog)
    if action:
        query = query.filter(AuditLog.action.ilike(f"%{action}%"))
    total = query.count()
    logs = query.order_by(AuditLog.created_at.desc()).offset(offset).limit(limit).all()

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": [
            {
                "id": log.id,
                "user_id": log.user_id,
                "action": log.action,
                "entity_type": log.entity_type,
                "entity_id": log.entity_id,
                "details": json.loads(log.details_json) if log.details_json else {},
                "created_at": log.created_at.isoformat() if log.created_at else None
            }
            for log in logs
        ]
    }

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
