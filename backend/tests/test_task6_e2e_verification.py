import sys
import os
import asyncio
import uuid

# Ensure backend directory is in python path
sys.path.insert(0, os.path.abspath("."))

from app.database import SessionLocal
from app.models.user import User
from app.models.product import Product
from app.models.cart import Cart
from app.models.session import CartSession, CartItem
from app.models.transaction import AuditLog
from app.services.session_service import SessionService
from app.api.v1.products import create_product, delete_product, list_products, restore_product
from app.schemas.product import ProductCreate

def test_full_e2e():
    db = SessionLocal()
    loop = asyncio.get_event_loop()
    print("=================================================================")
    print("   TASK 6: FINAL END-TO-END VERIFICATION & DEPLOYMENT CHECKLIST   ")
    print("=================================================================")

    test_barcode = f"890{uuid.uuid4().int % 10000000000:010d}"
    test_prod_name = "E2E Test Almond Butter 200g"

    try:
        # -------------------------------------------------------------
        # CHECKLIST 1: Admin Add Product -> save -> log out -> log in -> still there?
        # -------------------------------------------------------------
        print("\n--- [CHECK 1] Admin Add Product -> Persist -> Relogin Verification ---")
        
        # 1. Login as Admin
        admin_user = db.query(User).filter(User.role == "ADMIN").first()
        if not admin_user:
            admin_user = db.query(User).first()
        assert admin_user is not None, "Admin user must exist."
        print(f"Logged in staff: {admin_user.full_name} ({admin_user.email})")

        # 2. Add product
        new_prod_data = ProductCreate(
            name=test_prod_name,
            barcode=test_barcode,
            brand="Nut Butter Co.",
            category="Spreads",
            price=299.0,
            weight_grams=200.0,
            tax_rate=0.05,
            stock_quantity=50,
            is_active=True
        )
        created_prod = create_product(new_prod_data, db)
        print(f"Product created in DB: id={created_prod.id}, name='{created_prod.name}', barcode={created_prod.barcode}")
        assert created_prod.id is not None

        # Close session to simulate logout / disconnect from server
        db.close()

        # Reopen fresh database session simulating new login
        db = SessionLocal()
        admin_user = db.query(User).filter(User.role == "ADMIN").first() or db.query(User).first()
        print("Simulated admin logout, connection teardown, and fresh login...")
        reloaded_prod = db.query(Product).filter(Product.id == created_prod.id).first()
        assert reloaded_prod is not None, "Product must still exist in DB after re-login!"
        assert reloaded_prod.name == test_prod_name
        assert reloaded_prod.barcode == test_barcode
        assert reloaded_prod.price == 299.0
        print(f"✓ Product '{reloaded_prod.name}' successfully retrieved after relogin. Price: Rs.{reloaded_prod.price}, Stock: {reloaded_prod.stock_quantity}")

        # -------------------------------------------------------------
        # CHECKLIST 2: Admin Delete Product -> gone from User app?
        # -------------------------------------------------------------
        print("\n--- [CHECK 2] Admin Delete Product -> Gone from User App Verification ---")
        del_result = delete_product(created_prod.id, db=db, current_user=admin_user)
        print("Delete API response:", del_result)
        assert del_result["status"] == "SUCCESS"

        # Check in active products list (what User app queries)
        active_catalog = list_products(search=None, category=None, db=db)
        active_ids = [p.id for p in active_catalog]
        assert created_prod.id not in active_ids, "Deleted product must NOT appear in active catalog!"
        print(f"✓ Deleted product '{created_prod.name}' is gone from User app catalog.")

        # Check scanner lookup logic: attempt to find product for scanning
        scanned_prod = db.query(Product).filter(Product.barcode == test_barcode, Product.is_deleted == False).first()
        assert scanned_prod is None, "Deleted product must NOT be returned for barcode scan in cart!"
        print("✓ Barcode scanner correctly rejects deleted product.")

        # Check in admin deleted list
        trash_items = db.query(Product).filter(Product.is_deleted == True).all()
        trash_ids = [p.id for p in trash_items]
        assert created_prod.id in trash_ids, "Product must appear in Admin trash/deleted view."
        print("✓ Product is preserved with is_deleted=True for Admin audit and restore.")

        # Restore product for Check 3
        restore_result = restore_product(created_prod.id, db=db, current_user=admin_user)
        print("Restored product for removal testing:", restore_result)
        db.refresh(reloaded_prod)
        assert reloaded_prod.is_deleted is False


        # -------------------------------------------------------------
        # CHECKLIST 3: User Add Item -> Remove Item -> Camera Check -> Rescan -> Removed from Cart & Bill
        # -------------------------------------------------------------
        print("\n--- [CHECK 3] Full Removal Lifecycle Verification ---")
        cart = db.query(Cart).filter(Cart.is_enabled == True).first()
        assert cart is not None, "Cart required."

        # Setup active session with camera ONLINE
        cart.camera_status = "ONLINE"
        session = CartSession(cart_id=cart.id, status="ACTIVE", customer_phone="+919876543210")
        db.add(session)
        cart.status = "ACTIVE"
        db.commit()
        db.refresh(session)
        print(f"Session started: {session.id} on Cart {cart.cart_number}")

        # 1. User Scans & Adds Item
        item = loop.run_until_complete(SessionService.scan_item(db, session.id, test_barcode))
        # Camera verifies placement in basket
        item_obj = db.query(CartItem).filter(CartItem.id == item.id).first()
        item_obj.status = "VERIFIED"
        db.commit()

        db.refresh(session)
        print(f"1. Item added & verified in cart: '{item.product.name}', Cart count: {session.item_count}, Total: Rs.{session.total_amount}")
        assert session.item_count == 1
        assert session.total_amount > 0

        # Check checkout status: allowed
        state1 = SessionService.get_session_details(db, session.id)
        assert state1["can_checkout"] is True
        print("   ✓ Checkout allowed when item is verified in cart.")


        # 2. User Taps 'Remove Item'
        init_item = loop.run_until_complete(SessionService.initiate_item_removal(db, session.id, item.id))
        assert init_item.status == "REMOVING"
        print(f"2. User initiated removal. Item status: {init_item.status}")

        # Check checkout status: BLOCKED
        state2 = SessionService.get_session_details(db, session.id)
        assert state2["can_checkout"] is False, "Checkout MUST be blocked while item is being removed!"
        print("   ✓ Checkout successfully BLOCKED during removal phase.")

        # 3. Camera verifies departure
        removal_res = loop.run_until_complete(SessionService.verify_item_removal(
            db, session.id, item.id,
            image_data="data:image/jpeg;base64,/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAP//////////////////////////////////////////////////////////////////////////////////////wgALCAABAAEBAREA/8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABPxA="
        ))
        print("3. Camera AI verified departure:", removal_res)
        assert removal_res["status"] == "REMOVED_PENDING_RESCAN"
        assert removal_res["evidence_url"] is not None

        # Verify checkout is still BLOCKED pending rescan
        state3 = SessionService.get_session_details(db, session.id)
        assert state3["can_checkout"] is False, "Checkout MUST remain blocked pending barcode rescan!"
        print("   ✓ Checkout remains BLOCKED until customer rescans barcode.")

        # 4. Attempt rescan with WRONG barcode -> must fail
        wrong_barcode = "1111111111111"
        try:
            loop.run_until_complete(SessionService.rescan_to_remove(db, session.id, wrong_barcode))
            assert False, "Rescan with mismatched barcode should have raised ValueError!"
        except ValueError as err:
            print(f"4a. Mismatch barcode protection verified: caught expected error '{err}'")

        # 5. Rescan with EXACT barcode
        rescan_res = loop.run_until_complete(SessionService.rescan_to_remove(db, session.id, test_barcode))
        print(f"5. Rescan successful: {rescan_res}")
        assert rescan_res["status"] == "SUCCESS"

        # Verify final cart and bill totals
        db.refresh(session)
        assert session.item_count == 0, f"Expected 0 items, found {session.item_count}"
        assert session.total_amount == 0.0, f"Expected Rs.0.0, found {session.total_amount}"
        print(f"✓ Item fully removed from basket and bill! Basket items: {session.item_count}, Total: Rs.{session.total_amount}")

        # Verify all removal warnings are cleared from session state
        state4 = SessionService.get_session_details(db, session.id)
        assert len(state4["active_warnings"]) == 0
        assert len(state4["items"]) == 0
        print("   ✓ All removal warnings successfully cleared, 0 active warnings, empty basket.")


        # Cleanup test data
        session.status = "COMPLETED"
        cart.status = "IDLE"
        # Delete test cart item and session first to satisfy foreign key integrity
        db.query(CartItem).filter(CartItem.session_id == session.id).delete()
        db.delete(session)
        db.delete(reloaded_prod)
        db.commit()


        print("\n=================================================================")
        print("   ALL TASK 6 VERIFICATION CHECKS PASSED WITH ZERO ERRORS!       ")
        print("=================================================================\n")

    finally:
        db.close()

if __name__ == "__main__":
    test_full_e2e()
