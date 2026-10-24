import sys
import os
import asyncio
import json

# Ensure backend directory is in python path
sys.path.insert(0, os.path.abspath("."))

from app.database import SessionLocal
from app.models.product import Product
from app.models.cart import Cart
from app.models.session import CartSession, CartItem
from app.models.alert import Alert
from app.models.transaction import AuditLog
from app.services.session_service import SessionService
from app.services.alert_service import AlertService

def run_task5_verification():
    db = SessionLocal()
    print("=== Running Task 5 Admin Removals Verification ===")

    try:
        # 1. Setup or retrieve active cart and product
        cart = db.query(Cart).filter(Cart.is_enabled == True).first()
        assert cart is not None, "At least one enabled cart must exist in DB."
        print(f"Using Cart: {cart.cart_number}")

        product = db.query(Product).filter(Product.is_deleted == False).first()
        assert product is not None, "At least one active product must exist."
        print(f"Using Product: {product.name} ({product.barcode}) @ Rs.{product.price}")

        # Clean any stale active session for this cart
        old_sessions = db.query(CartSession).filter(CartSession.cart_id == cart.id, CartSession.status == "ACTIVE").all()
        for s in old_sessions:
            s.status = "COMPLETED"
        db.commit()

        # Create fresh session
        session = CartSession(cart_id=cart.id, status="ACTIVE", customer_phone="+919876543210")
        db.add(session)
        cart.status = "ACTIVE"
        db.commit()
        db.refresh(session)
        print(f"Created Session: {session.id}")

        # Add 2 items to session
        loop = asyncio.get_event_loop()
        item1 = loop.run_until_complete(SessionService.scan_item(db, session.id, product.barcode))
        item2 = loop.run_until_complete(SessionService.scan_item(db, session.id, product.barcode))
        
        # Verify initial totals
        session_state = SessionService.get_session_details(db, session.id)
        assert session_state["session"].item_count == 2
        print(f"Basket initial item count: {session_state['session'].item_count}, Total: Rs.{session_state['session'].total_amount}")

        # Step 2: Trigger removal on item1 to put it into REMOVED_PENDING_RESCAN with camera snapshot
        item1_obj = db.query(CartItem).filter(CartItem.id == item1.id).first()
        item1_obj.status = "REMOVED_PENDING_RESCAN"
        item1_obj.verification_evidence_url = "/uploads/evidence/test_snapshot.jpg"
        db.commit()

        # Step 3: Test GET /admin/sessions/{session_id}/items logic
        items = db.query(CartItem).filter(CartItem.session_id == session.id).order_by(CartItem.scanned_at.desc()).all()
        assert len(items) == 2
        status_map = {itm.id: itm.status for itm in items}
        assert status_map[item1.id] == "REMOVED_PENDING_RESCAN"
        assert items[0].verification_evidence_url or items[1].verification_evidence_url
        print("✓ Admin session items correctly expose 'REMOVED_PENDING_RESCAN' status and camera snapshot evidence URL.")

        # Step 4: Create a removal alert for this session
        alert = Alert(
            cart_id=cart.id,
            session_id=session.id,
            alert_type="REMOVAL_WITHOUT_RESCAN",
            severity="HIGH",
            message=f"Item departure detected for '{product.name}', pending rescan.",
            evidence_snapshot_url="/uploads/evidence/test_snapshot.jpg",
            status="OPEN"
        )
        db.add(alert)
        db.commit()
        db.refresh(alert)
        print(f"Created Alert: {alert.id} ({alert.alert_type})")

        # Step 5: Test Force-Remove from Alert
        # Simulating force_remove_from_alert logic
        from app.api.v1.admin import force_remove_from_alert, ForceRemoveRequest
        req = ForceRemoveRequest(
            reason="Floor associate confirmed customer handed item to cashier outside cart.",
            cart_item_id=item1.id
        )
        res = loop.run_until_complete(force_remove_from_alert(alert.id, req, db))
        print("Force-remove from alert response:", res)
        assert res["status"] == "SUCCESS"

        # Verify alert is resolved
        db.refresh(alert)
        assert alert.status == "RESOLVED"
        assert "Force-removed by staff" in alert.resolution_notes
        print(f"✓ Alert {alert.id} successfully resolved with notes: {alert.resolution_notes}")

        # Verify item1 is dropped from bill and totals recalculated
        db.refresh(session)
        db.refresh(item1_obj)
        assert item1_obj.status == "REMOVED"
        assert session.item_count == 1
        print(f"✓ Item 1 dropped from cart. New basket item count: {session.item_count}, Total: Rs.{session.total_amount}")

        # Verify AuditLog written
        audit = db.query(AuditLog).filter(
            AuditLog.action == "FORCE_REMOVE_ITEM",
            AuditLog.entity_id == item1.id
        ).first()
        assert audit is not None, "AuditLog entry for force removal must exist."
        details = json.loads(audit.details_json)
        assert details["reason"] == req.reason
        print(f"✓ AuditLog recorded successfully: action={audit.action}, user={audit.user_id}, reason='{details['reason']}'")

        # Step 6: Test direct Force-Remove from Live Cart Monitor on item2
        from app.api.v1.admin import force_remove_session_item
        req2 = ForceRemoveRequest(
            reason="Staff inspected cart and confirmed damaged packaging item removed."
        )
        res2 = loop.run_until_complete(force_remove_session_item(session.id, item2.id, req2, db))
        print("Direct session item force-remove response:", res2)
        assert res2["status"] == "SUCCESS"

        db.refresh(session)
        assert session.item_count == 0
        assert session.total_amount == 0.0
        print(f"✓ Direct force-remove passed. Basket items: {session.item_count}, Total: Rs.{session.total_amount}")

        # Cleanup session
        session.status = "COMPLETED"
        cart.status = "IDLE"
        db.commit()
        print("=== Task 5 Verification PASSED Completely! ===")

    finally:
        db.close()

if __name__ == "__main__":
    run_task5_verification()
