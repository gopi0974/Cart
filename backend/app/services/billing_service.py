from datetime import datetime
from typing import Dict, Any
from sqlalchemy.orm import Session
from app.models.session import CartSession, CartItem
from app.models.transaction import Transaction
from app.models.cart import Cart
from app.services.session_service import SessionService
from app.utils.receipt import generate_receipt_number, generate_exit_token
from app.websocket.manager import ws_manager

class BillingService:
    @staticmethod
    async def process_checkout(
        db: Session,
        session_id: str,
        payment_method: str = "UPI",
        upi_id: str = None,
        card_token: str = None
    ) -> Transaction:
        """Process bill payment and generate official digital receipt + exit pass."""
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

        # Simulate sandbox transaction
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

        # Mark session completed & free up cart
        session.status = "COMPLETED"
        session.ended_at = datetime.utcnow()
        cart.status = "IDLE"

        db.commit()
        db.refresh(tx)

        # Notify shopper phone & admin feed
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
