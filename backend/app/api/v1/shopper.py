import secrets
from typing import Optional
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Header, status
from sqlalchemy.orm import Session
from app.database import get_db
from app.config import settings
from app.models.cart import Cart
from app.models.session import CartSession
from app.models.user import User
from app.utils.security import decode_access_token
from app.websocket.manager import ws_manager
from app.schemas.session import (
    PairSessionRequest, SessionResponse, CartItemResponse,
    ScanItemRequest, RescanRemoveRequest, VerifyRemovalRequest, CouponRequest
)
from app.schemas.transaction import CheckoutRequest, ReceiptResponse
from app.services.session_service import SessionService
from app.services.billing_service import BillingService

router = APIRouter(prefix="/shopper", tags=["Shopper Mobile App"])

def verify_shopper_session(
    session_id: str,
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token"),
    authorization: Optional[str] = Header(None, alias="Authorization"),
    db: Session = Depends(get_db)
) -> CartSession:
    """
    Enforce shopper session ownership.
    A shopper must provide their unguessable session_token matching the session.
    Store staff with a valid JWT token can also access the session.
    """
    session = db.query(CartSession).filter(CartSession.id == session_id).first()
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Shopping session not found."
        )

    # 1. Check direct session token header
    token_to_check = x_session_token

    # 2. Check if provided in Authorization header: Bearer <token>
    if not token_to_check and authorization:
        parts = authorization.strip().split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            raw_token = parts[1]
            # Check if this is an admin/staff JWT access token
            payload = decode_access_token(raw_token)
            if payload and "sub" in payload:
                user = db.query(User).filter(User.email.ilike(str(payload["sub"]).strip())).first()
                if user and user.is_active:
                    return session
            # Otherwise treat as session token
            token_to_check = raw_token

    if not token_to_check:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing session authorization token. Please pair with the cart."
        )

    if not getattr(session, 'session_token', None):
        session.session_token = secrets.token_urlsafe(32)
        db.commit()

    if not secrets.compare_digest(token_to_check, session.session_token):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Session authorization failed: Invalid session token for this cart session."
        )

    return session

@router.post("/pair", response_model=SessionResponse)
async def pair_cart(req: PairSessionRequest, db: Session = Depends(get_db)):
    """Pair shopper mobile phone with cart by scanning its QR code token."""
    try:
        session = await SessionService.pair_cart(
            db=db,
            qr_token=req.qr_token,
            customer_phone=req.customer_phone,
            signature=req.signature,
            cart_number=req.cart_number
        )
        details = SessionService.get_session_details(db, session.id)
        return _format_session_response(details)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/config")
def get_shopper_config():
    """Public shopper application configuration."""
    return {
        "demo_mode": settings.DEMO_MODE,
        "base_url": settings.BASE_URL if settings.DEMO_MODE else None,
    }

@router.get("/connect", response_model=SessionResponse)
async def connect_cart_via_qr(
    cart: str,
    sig: Optional[str] = None,
    token: Optional[str] = None,
    phone: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """
    Connect shopper to cart via signed QR link.
    Validates HMAC signature and enforces single active session policy.
    """
    if not sig:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Security verification failed: Missing HMAC signature. Please scan the official cart QR code."
        )
    try:
        session = await SessionService.pair_cart(
            db=db,
            qr_token=token,
            customer_phone=phone,
            signature=sig,
            cart_number=cart
        )
        details = SessionService.get_session_details(db, session.id)
        return _format_session_response(details)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/available-carts")
def get_available_carts(db: Session = Depends(get_db)):
    """Public list of active/enabled smart carts for device pairing."""
    carts = db.query(Cart).filter(Cart.is_enabled == True).order_by(Cart.cart_number.asc()).all()
    return [{"id": c.id, "cart_number": c.cart_number, "status": c.status, "camera_status": c.camera_status} for c in carts]

@router.get("/{session_id}", response_model=SessionResponse)
def get_session(session: CartSession = Depends(verify_shopper_session), db: Session = Depends(get_db)):
    """Retrieve full live session state, items, warnings, and running bill."""
    try:
        details = SessionService.get_session_details(db, session.id)
        return _format_session_response(details)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.post("/{session_id}/scan-item", response_model=CartItemResponse)
async def scan_item(req: ScanItemRequest, session: CartSession = Depends(verify_shopper_session), db: Session = Depends(get_db)):
    """Shopper scans barcode with phone camera. Item enters PENDING state."""
    try:
        item = await SessionService.scan_item(db, session.id, req.barcode)
        return _format_item_response(item)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/{session_id}/items/{item_id}/initiate-remove")
async def initiate_item_remove(item_id: str, session: CartSession = Depends(verify_shopper_session), db: Session = Depends(get_db)):
    """Shopper taps 'Remove' on an item. If PENDING, deletes immediately; if VERIFIED, sets to REMOVING."""
    try:
        res = await SessionService.initiate_item_removal(db, session.id, item_id)
        if isinstance(res, dict):
            return res
        return _format_item_response(res)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/{session_id}/items/{item_id}/verify-removal")
async def verify_item_removal(
    item_id: str,
    req: Optional[VerifyRemovalRequest] = None,
    session: CartSession = Depends(verify_shopper_session),
    db: Session = Depends(get_db)
):
    """Cart camera AI verification of item physical departure."""
    try:
        img_data = req.image_data_url if req else None
        res = await SessionService.verify_item_removal(db, session.id, item_id, image_data=img_data)
        return res
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/{session_id}/items/{item_id}/cancel-remove", response_model=CartItemResponse)
async def cancel_item_remove(item_id: str, session: CartSession = Depends(verify_shopper_session), db: Session = Depends(get_db)):
    """Shopper taps 'Cancel' to keep the item in the cart."""
    try:
        item = await SessionService.cancel_item_removal(db, session.id, item_id)
        return _format_item_response(item)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/{session_id}/rescan-remove")
async def rescan_remove(req: RescanRemoveRequest, session: CartSession = Depends(verify_shopper_session), db: Session = Depends(get_db)):
    """Shopper rescans an item that was removed from cart to drop it from bill."""
    try:
        res = await SessionService.rescan_to_remove(db, session.id, req.barcode)
        return res
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/{session_id}/checkout")
async def checkout(req: CheckoutRequest, session: CartSession = Depends(verify_shopper_session), db: Session = Depends(get_db)):
    """Process checkout payment. Allowed ONLY if all items are VERIFIED and no warnings open."""
    try:
        tx = await BillingService.process_checkout(
            db=db,
            session_id=session.id,
            payment_method=req.payment_method,
            upi_id=req.upi_id,
            card_token=req.card_token
        )
        return {
            "status": "SUCCESS",
            "receipt_number": tx.receipt_number,
            "amount_paid": tx.amount
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/{session_id}/receipt", response_model=ReceiptResponse)
def get_receipt(session: CartSession = Depends(verify_shopper_session), db: Session = Depends(get_db)):
    """Fetch digital receipt for completed session."""
    try:
        return BillingService.get_receipt(db, session.id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.post("/{session_id}/end-session")
async def end_session(session: CartSession = Depends(verify_shopper_session), db: Session = Depends(get_db)):
    """
    Shopper ends session to leave or cancel.
    Frees the cart immediately (sets cart to IDLE) so other shoppers can occupy it.
    Sets session status to ENDED.
    Idempotent: calling multiple times on an already ended session succeeds without error.
    """
    cart = session.cart
    if session.status == "ACTIVE":
        session.status = "ENDED"
        session.ended_at = datetime.utcnow()
    elif session.status not in ("ENDED", "ABANDONED", "COMPLETED"):
        session.status = "ENDED"
        session.ended_at = datetime.utcnow()

    if cart:
        cart.status = "IDLE"
        cart.last_heartbeat = datetime.utcnow()

    db.commit()

    if cart:
        # Broadcast to admin & devices that cart is now IDLE and free
        await ws_manager.broadcast_to_admin("CART_STATUS_CHANGE", {
            "cart_id": cart.id,
            "cart_number": cart.cart_number,
            "status": "IDLE",
            "session_id": None
        })
        await ws_manager.broadcast_to_cart(cart.id, "SESSION_ABANDONED", {
            "cart_id": cart.id,
            "cart_number": cart.cart_number,
            "message": "Shopper exited the session. Cart is now available."
        })

    return {
        "status": "SUCCESS",
        "message": f"Session closed. Cart '{cart.cart_number if cart else ''}' is now free for new shoppers."
    }


def _format_item_response(itm) -> CartItemResponse:
    prod = itm.product
    return CartItemResponse(
        id=itm.id,
        product_id=prod.id,
        product_name=prod.name,
        product_barcode=prod.barcode,
        product_image_url=prod.primary_image_url,
        brand=prod.brand,
        category=prod.category,
        quantity=itm.quantity,
        unit_price=itm.unit_price,
        status=itm.status,
        scanned_at=itm.scanned_at,
        verified_at=itm.verified_at,
        confidence_score=itm.confidence_score,
        verification_evidence_url=itm.verification_evidence_url
    )

@router.post("/{session_id}/apply-coupon")
async def apply_coupon(
    req: CouponRequest,
    session: CartSession = Depends(verify_shopper_session),
    db: Session = Depends(get_db)
):
    """Apply promotional coupon code to active shopping cart session."""
    code = (req.coupon_code or "").strip().upper()
    if code in ["SUPER50", "WELCOME50", "SAVE50"]:
        discount = round(min(session.subtotal_amount * 0.5, 50.0), 2)
        if discount <= 0:
            discount = round(session.subtotal_amount * 0.5, 2)
    elif code in ["SUPER10", "SAVE10"]:
        discount = round(session.subtotal_amount * 0.1, 2)
    elif code in ["FLAT100"]:
        discount = min(session.subtotal_amount, 100.0)
    else:
        raise HTTPException(status_code=400, detail=f"Invalid or expired coupon code '{code}'.")

    session.total_discount = discount
    session.total_amount = max(0.0, round(session.subtotal_amount + session.total_tax - discount, 2))
    db.commit()
    db.refresh(session)

    return {
        "status": "SUCCESS",
        "coupon_code": code,
        "discount_amount": discount,
        "subtotal_amount": session.subtotal_amount,
        "total_amount": session.total_amount,
        "message": f"Coupon '{code}' applied successfully!"
    }

def _format_session_response(details) -> SessionResponse:
    sess = details["session"]
    cart = details["cart"]
    return SessionResponse(
        id=sess.id,
        cart_id=cart.id,
        cart_number=cart.cart_number,
        session_token=getattr(sess, "session_token", None),
        camera_status=details.get("camera_status", getattr(cart, "camera_status", "OFFLINE")),
        status=sess.status,
        started_at=sess.started_at,
        subtotal_amount=sess.subtotal_amount,
        total_tax=sess.total_tax,
        total_discount=sess.total_discount,
        total_amount=sess.total_amount,
        item_count=sess.item_count,
        items=[_format_item_response(itm) for itm in details["items"]],
        active_warnings=details["active_warnings"],
        can_checkout=details["can_checkout"]
    )
