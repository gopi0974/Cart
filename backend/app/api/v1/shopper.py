from typing import Optional
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.database import get_db
from app.schemas.session import (
    PairSessionRequest, SessionResponse, CartItemResponse,
    ScanItemRequest, RescanRemoveRequest
)
from app.schemas.transaction import CheckoutRequest, ReceiptResponse
from app.services.session_service import SessionService
from app.services.billing_service import BillingService

router = APIRouter(prefix="/shopper", tags=["Shopper Mobile App"])

class CouponRequest(BaseModel):
    coupon_code: str

@router.post("/pair", response_model=SessionResponse)
async def pair_cart(req: PairSessionRequest, db: Session = Depends(get_db)):
    """Pair shopper mobile phone with cart by scanning its QR code token."""
    try:
        session = await SessionService.pair_cart(db, req.qr_token, req.customer_phone)
        details = SessionService.get_session_details(db, session.id)
        return _format_session_response(details)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/{session_id}", response_model=SessionResponse)
def get_session(session_id: str, db: Session = Depends(get_db)):
    """Retrieve full live session state, items, warnings, and running bill."""
    try:
        details = SessionService.get_session_details(db, session_id)
        return _format_session_response(details)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.post("/{session_id}/scan-item", response_model=CartItemResponse)
async def scan_item(session_id: str, req: ScanItemRequest, db: Session = Depends(get_db)):
    """Shopper scans barcode with phone camera. Item enters PENDING state."""
    try:
        item = await SessionService.scan_item(db, session_id, req.barcode)
        return _format_item_response(item)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/{session_id}/rescan-remove")
async def rescan_remove(session_id: str, req: RescanRemoveRequest, db: Session = Depends(get_db)):
    """Shopper rescans an item that was removed from cart to drop it from bill."""
    success = await SessionService.rescan_to_remove(db, session_id, req.barcode)
    if not success:
        raise HTTPException(status_code=400, detail=f"No active item found with barcode {req.barcode} to remove.")
    return {"status": "SUCCESS", "message": "Item removed from cart and bill updated."}

@router.post("/{session_id}/apply-coupon")
def apply_coupon(session_id: str, req: CouponRequest, db: Session = Depends(get_db)):
    """Apply promotional coupon/discount to cart."""
    try:
        return BillingService.apply_coupon(db, session_id, req.coupon_code)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/{session_id}/checkout")
async def checkout(session_id: str, req: CheckoutRequest, db: Session = Depends(get_db)):
    """Process checkout payment. Allowed ONLY if all items are VERIFIED and no warnings open."""
    try:
        tx = await BillingService.process_checkout(
            db=db,
            session_id=session_id,
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
def get_receipt(session_id: str, db: Session = Depends(get_db)):
    """Fetch digital receipt for completed session."""
    try:
        return BillingService.get_receipt(db, session_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


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

def _format_session_response(details) -> SessionResponse:
    sess = details["session"]
    cart = details["cart"]
    return SessionResponse(
        id=sess.id,
        cart_id=cart.id,
        cart_number=cart.cart_number,
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
