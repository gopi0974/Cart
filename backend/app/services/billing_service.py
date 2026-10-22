from datetime import datetime
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session
from app.models.session import CartSession, CartItem
from app.models.transaction import Transaction
from app.models.product import Product
from app.models.cart import Cart
from app.services.session_service import SessionService
from app.services.alert_service import AlertService
from app.utils.receipt import generate_receipt_number, generate_exit_token
from app.websocket.manager import ws_manager

VALID_COUPONS = {
    "WELCOME10": {"type": "PERCENT", "value": 10.0, "description": "10% Welcome Discount"},
    "SUPER50": {"type": "FLAT", "value": 50.0, "description": "₹50 SuperMart Special"},
    "FREESHIP": {"type": "FLAT", "value": 20.0, "description": "₹20 Instant Savings"}
}

class BillingService:
    @staticmethod
    def apply_coupon(db: Session, session_id: str, coupon_code: str) -> Dict[str, Any]:
        """Validate and apply promotional discount code to active session."""
        code = coupon_code.upper().strip()
        if code not in VALID_COUPONS:
            raise ValueError(f"Invalid coupon code '{code}'. Try WELCOME10 or SUPER50.")

        session = db.query(CartSession).filter(CartSession.id == session_id).first()
        if not session or session.status != "ACTIVE":
            raise ValueError("No active session found.")

        coupon = VALID_COUPONS[code]
        if coupon["type"] == "PERCENT":
            discount = round(session.subtotal_amount * (coupon["value"] / 100.0), 2)
        else:
            discount = min(coupon["value"], session.subtotal_amount)

        session.total_discount = discount
        session.total_amount = max(0.0, round(session.subtotal_amount + session.total_tax - discount, 2))
        db.commit()
        db.refresh(session)

        return {
            "status": "SUCCESS",
            "coupon_code": code,
            "discount_amount": discount,
            "new_total": session.total_amount,
            "description": coupon["description"]
        }

    @staticmethod
    async def process_checkout(
        db: Session,
        session_id: str,
        payment_method: str = "UPI",
        upi_id: str = None,
        card_token: str = None
    ) -> Transaction:
        """Process bill payment, deduct stock, trigger low-stock alerts, and generate exit pass."""
        session_details = SessionService.get_session_details(db, session_id)
        session: CartSession = session_details["session"]
        cart: Cart = session_details["cart"]

        if not session_details["can_checkout"]:
            if len(session_details["active_warnings"]) > 0:
                raise ValueError("Checkout blocked: You have unresolved alerts or warnings in your cart.")
            for itm in session_details["items"]:
                if itm.status != "VERIFIED":
                    raise ValueError(f"Checkout blocked: Item '{itm.product.name}' is still {itm.status}. Must be VERIFIED by cart camera.")
            raise ValueError("Checkout blocked: Cannot complete checkout at this time.")

        # Deduct purchased quantities from product inventory & trigger low-stock alerts
        for itm in session_details["items"]:
            prod = db.query(Product).filter(Product.id == itm.product_id).first()
            if prod:
                prod.stock_quantity = max(0, prod.stock_quantity - itm.quantity)
                if prod.stock_quantity <= 5:
                    await AlertService.create_alert(
                        db=db,
                        cart_id=cart.id,
                        alert_type="LOW_STOCK_WARNING",
                        message=f"Low Stock Alert: '{prod.name}' has only {prod.stock_quantity} units remaining in inventory.",
                        severity="LOW"
                    )

        # Generate official digital receipt & store exit pass
        receipt_num = generate_receipt_number()
        exit_token = generate_exit_token(receipt_num)

        tx = Transaction(
            session_id=session.id,
            payment_method=payment_method,
            payment_gateway_ref=f"SIM_PAY_{payment_method}_{datetime.utcnow().timestamp():.0f}",
            amount=session.total_amount,
            status="SUCCESS",
            receipt_number=receipt_num,
            exit_gate_token=exit_token
        )
        db.add(tx)

        # Finalize session & mark cart IDLE
        session.status = "COMPLETED"
        session.ended_at = datetime.utcnow()
        cart.status = "IDLE"

        db.commit()
        db.refresh(tx)

        # Notify mobile app and admin feeds
        await ws_manager.broadcast_to_cart(cart.id, "CHECKOUT_COMPLETED", {
            "receipt_number": receipt_num,
            "exit_gate_token": exit_token,
            "total_paid": tx.amount,
            "payment_method": tx.payment_method
        })

        await ws_manager.broadcast_to_admin("CART_STATUS_CHANGE", {
            "cart_id": cart.id,
            "cart_number": cart.cart_number,
            "status": "IDLE",
            "session_id": None
        })

        return tx

    @staticmethod
    def verify_turnstile_exit(db: Session, exit_token: str) -> Dict[str, Any]:
        """Verify exit turnstile QR pass at supermarket exit gate."""
        tx = db.query(Transaction).filter(Transaction.exit_gate_token == exit_token.strip()).first()
        if not tx:
            return {
                "valid": False,
                "gate_unlocked": False,
                "message": "Invalid or expired exit pass. Please present your receipt to store staff."
            }

        session = tx.session
        items = db.query(CartItem).filter(
            CartItem.session_id == session.id,
            CartItem.status == "VERIFIED"
        ).all()

        return {
            "valid": True,
            "gate_unlocked": True,
            "receipt_number": tx.receipt_number,
            "cart_number": session.cart.cart_number,
            "amount_paid": tx.amount,
            "item_count": len(items),
            "timestamp": tx.created_at.isoformat(),
            "message": "Payment verified! Turnstile gate unlocked. Have a great day!"
        }

    @staticmethod
    def get_receipt(db: Session, session_id: str) -> Dict[str, Any]:
        """Fetch receipt breakdown including tax items and exit token."""
        tx = db.query(Transaction).filter(Transaction.session_id == session_id).first()
        if not tx:
            raise ValueError("No finalized transaction found for this session.")

        session = tx.session
        items = db.query(CartItem).filter(
            CartItem.session_id == session.id,
            CartItem.status == "VERIFIED"
        ).all()

        item_summaries = [
            {
                "name": itm.product.name,
                "quantity": itm.quantity,
                "unit_price": itm.unit_price,
                "total_price": round(itm.unit_price * itm.quantity, 2)
            }
            for itm in items
        ]

        return {
            "id": tx.id,
            "receipt_number": tx.receipt_number,
            "session_id": session.id,
            "cart_number": session.cart.cart_number,
            "customer_phone": session.customer_phone,
            "payment_method": tx.payment_method,
            "subtotal": session.subtotal_amount,
            "tax_amount": session.total_tax,
            "discount_amount": session.total_discount,
            "total_paid": tx.amount,
            "items": item_summaries,
            "exit_gate_token": tx.exit_gate_token,
            "timestamp": tx.created_at,
            "store_name": "SuperMart Hypermarket - Downtown",
            "store_tax_id": "GSTIN29AAACB1234F1Z5"
        }
