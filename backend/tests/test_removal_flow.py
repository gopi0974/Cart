import sys
import os
sys.path.insert(0, os.path.abspath("."))
import asyncio
from app.database import SessionLocal
from app.models.cart import Cart
from app.models.product import Product
from app.models.session import CartSession, CartItem
from app.services.session_service import SessionService
from app.services.billing_service import BillingService

async def test_removal_flow():
    db = SessionLocal()
    try:
        cart = db.query(Cart).filter(Cart.is_enabled == True).first()
        assert cart, "No enabled cart found"
        cart.camera_status = "ONLINE"
        db.commit()

        # Clean prior sessions on this cart
        db.query(CartSession).filter(CartSession.cart_id == cart.id, CartSession.status == "ACTIVE").update({"status": "ABANDONED"})
        db.commit()

        # 1. Pair session
        session = await SessionService.pair_cart(db, cart.qr_code_token)
        print("1. Paired session:", session.id)

        # 2. Add two products
        p1 = db.query(Product).filter(Product.barcode.isnot(None), Product.is_active == True, Product.is_deleted == False).first()
        p2 = db.query(Product).filter(Product.barcode != p1.barcode, Product.is_active == True, Product.is_deleted == False).first()
        assert p1 and p2, "Need 2 active products"

        item1 = await SessionService.scan_item(db, session.id, p1.barcode)
        item2 = await SessionService.scan_item(db, session.id, p2.barcode)
        
        # Verify both items
        await SessionService.verify_item_placement(db, session.id, p1.barcode)
        await SessionService.verify_item_placement(db, session.id, p2.barcode)
        db.refresh(session)
        print(f"2. Added & verified 2 items: {p1.name} (Rs.{item1.unit_price}), {p2.name} (Rs.{item2.unit_price}). Total: Rs.{session.total_amount}")
        
        # Verify checkout allowed when both items verified
        details = SessionService.get_session_details(db, session.id)
        assert details["can_checkout"] == True, "Should be able to checkout"

        # 3. Initiate removal of item1
        rem_item = await SessionService.initiate_item_removal(db, session.id, item1.id)
        assert rem_item.status == "REMOVING", f"Expected REMOVING but got {rem_item.status}"
        print("3. Item 1 status set to REMOVING")

        # Check details: can_checkout must be FALSE
        details_rem = SessionService.get_session_details(db, session.id)
        assert details_rem["can_checkout"] == False, "Checkout must be blocked during removal"
        has_warning = any(w["type"] == "ITEM_REMOVING" for w in details_rem["active_warnings"])
        assert has_warning, "Active warning ITEM_REMOVING must exist"

        # Test process_checkout blocks with exact message
        try:
            await BillingService.process_checkout(db, session.id)
            assert False, "Checkout should have failed"
        except ValueError as e:
            assert "Please complete the item removal before checking out." in str(e), f"Wrong checkout error: {e}"
            print("4. Checkout properly blocked with message: 'Please complete the item removal before checking out.'")

        # 4. Verify removal AI check
        verif_res = await SessionService.verify_item_removal(db, session.id, item1.id)
        assert verif_res["removed"] == True
        assert verif_res["status"] == "REMOVED_PENDING_RESCAN"
        print("5. AI removal verified: state updated to REMOVED_PENDING_RESCAN")

        # 5. Shopper scans WRONG barcode (e.g. dummy barcode or different product)
        try:
            await SessionService.rescan_to_remove(db, session.id, "9999999999999")
            assert False, "Scanning different barcode should have failed"
        except ValueError as e:
            expected_msg = f"This barcode does not match the item you are removing. Please scan {p1.name}."
            assert expected_msg in str(e), f"Wrong error: {e}"
            print("6. Mismatch blocked with exact message:", str(e))

        # Check total has NOT changed
        db.refresh(session)
        assert session.total_amount > 0, "Total should not have changed on mismatch"

        # 6. Shopper scans CORRECT barcode (p1.barcode)
        rescan_res = await SessionService.rescan_to_remove(db, session.id, p1.barcode)
        assert rescan_res["status"] == "SUCCESS"
        assert f"{p1.name} removed from cart." in rescan_res["message"]
        print("7. Correct barcode scanned. Rescan result:", rescan_res["message"])

        db.refresh(session)
        db.refresh(item1)
        assert item1.status == "REMOVED", "Item 1 status must be REMOVED"
        print(f"8. Total recalculated: Rs.{session.total_amount} (Item 2 remaining: Rs.{item2.unit_price})")
        assert session.item_count == 1, "Only 1 item should remain"

        # Now can checkout!
        details_final = SessionService.get_session_details(db, session.id)
        assert details_final["can_checkout"] == True, "Checkout should now be allowed"
        print("9. Checkout unblocked! All removal tests passed with flying colors!")

    finally:
        db.close()

if __name__ == "__main__":
    asyncio.run(test_removal_flow())
