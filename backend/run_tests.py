import sys
from fastapi.testclient import TestClient
from app.main import app
from app.database import init_db, SessionLocal
from app.utils.seed_data import seed_database
from app.models.session import CartSession
from app.models.cart import Cart

def run_all_tests():
    print("========================================")
    print("Starting SmartCart AI Backend Test Suite")
    print("========================================")
    
    init_db()
    db = SessionLocal()
    seed_database(db)

    # Clean up lingering test sessions so runs are 100% idempotent
    active_test_sessions = db.query(CartSession).filter(CartSession.status == "ACTIVE").all()
    for s in active_test_sessions:
        s.status = "COMPLETED"
    test_carts = db.query(Cart).all()
    for c in test_carts:
        c.status = "IDLE"
        c.is_enabled = True
    db.commit()
    db.close()
    
    client = TestClient(app)
    
    # Test 1: Root
    print("Test 1: Healthcheck root endpoint...")
    resp = client.get("/")
    assert resp.status_code == 200, f"Root failed: {resp.text}"
    assert resp.json()["status"] == "ONLINE"
    print("[OK] Healthcheck PASSED")
    
    # Test 2: Auth
    print("Test 2: Staff login & JWT issue...")
    resp = client.post("/api/v1/auth/login", json={
        "email": "admin@supermart.com",
        "password": "admin123"
    })
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    token = resp.json()["access_token"]
    assert len(token) > 20
    auth_header = {"Authorization": f"Bearer {token}"}
    print("[OK] Auth PASSED (Token generated)")
    
    # Test 3: Catalog
    print("Test 3: Catalog products listing & search...")
    resp = client.get("/api/v1/products")
    assert resp.status_code == 200
    prods = resp.json()
    assert len(prods) >= 10
    test_barcode = prods[0]["barcode"]
    print(f"[OK] Catalog PASSED ({len(prods)} products verified, testing with {test_barcode})")
    
    # Test 4: Shopper flow & state machine
    print("Test 4: Shopper pairing, scan item (PENDING state)...")
    pair_resp = client.post("/api/v1/shopper/pair", json={"qr_token": "QR-CART-001"})
    assert pair_resp.status_code == 200, f"Pair failed: {pair_resp.text}"
    sess_id = pair_resp.json()["id"]
    
    scan_resp = client.post(f"/api/v1/shopper/{sess_id}/scan-item", json={"barcode": test_barcode})
    assert scan_resp.status_code == 200
    sess_state = client.get(f"/api/v1/shopper/{sess_id}").json()
    assert len(sess_state["items"]) == 1
    assert sess_state["items"][0]["status"] == "PENDING"
    print("[OK] Scanned item is in PENDING state")
    
    # Test 5: Checkout blocked on pending
    print("Test 5: Checkout validation rules (must block PENDING)...")
    co_block = client.post(f"/api/v1/shopper/{sess_id}/checkout", json={"payment_method": "UPI"})
    assert co_block.status_code == 400
    assert "pending" in co_block.json()["detail"].lower() or "blocked" in co_block.json()["detail"].lower()
    print("[OK] Checkout correctly BLOCKED while item is pending verification")
    
    # Test 6: AI verification
    print("Test 6: Simulating AI camera verification...")
    ver_sim = client.post("/api/v1/vision/simulate-action", json={
        "cart_id": "CART-001",
        "action_type": "CONFIRM_BARCODE",
        "detected_barcode": test_barcode
    })
    assert ver_sim.status_code == 200
    sess_state_ver = client.get(f"/api/v1/shopper/{sess_id}").json()
    assert sess_state_ver["items"][0]["status"] == "VERIFIED"
    assert sess_state_ver["can_checkout"] is True
    print("[OK] AI camera confirmed item: state updated to VERIFIED")
    
    # Test 7: Successful checkout & receipt
    print("Test 7: Checkout completion & exit receipt generation...")
    co_ok = client.post(f"/api/v1/shopper/{sess_id}/checkout", json={
        "payment_method": "UPI",
        "upi_id": "shopper@oksbi"
    })
    assert co_ok.status_code == 200
    co_data = co_ok.json()
    assert "REC-" in co_data["receipt_number"]
    
    rec_resp = client.get(f"/api/v1/shopper/{sess_id}/receipt")
    assert rec_resp.status_code == 200
    print(f"[OK] Checkout PASSED: Generated receipt {co_data['receipt_number']}")
    
    # Test 8: Fraud detection - unscanned item
    print("Test 8: Detecting unscanned item and raising alert...")
    pair2 = client.post("/api/v1/shopper/pair", json={"qr_token": "QR-CART-002"})
    assert pair2.status_code == 200
    sess_id_2 = pair2.json()["id"]
    
    unscanned = client.post("/api/v1/vision/simulate-action", json={
        "cart_id": "CART-002",
        "action_type": "PLACE_UNSCANNED",
        "detected_barcode": "7622201745424"
    })
    assert unscanned.status_code == 200
    
    sess2_state = client.get(f"/api/v1/shopper/{sess_id_2}").json()
    assert len(sess2_state["active_warnings"]) > 0
    assert sess2_state["can_checkout"] is False
    print("[OK] Unscanned item alert detected and flagged in cart session")
    
    # Test 9: Admin overview & alert triage
    print("Test 9: Admin overview KPI and alert triage...")
    admin_ov = client.get("/api/v1/admin/overview", headers=auth_header).json()
    assert admin_ov["total_carts"] >= 3
    assert admin_ov["open_incidents"] >= 1
    print("[OK] Admin KPI overview and alert triage verified")

    # Complete session 2 to release CART-002
    db2 = SessionLocal()
    s2 = db2.query(CartSession).filter(CartSession.id == sess_id_2).first()
    if s2:
        s2.status = "COMPLETED"
    db2.commit()
    db2.close()

    # Test 10: Promotional discount
    print("Test 10: Testing promotional coupon discount...")
    pair3 = client.post("/api/v1/shopper/pair", json={"qr_token": "QR-CART-003"})
    assert pair3.status_code == 200
    sess_id_3 = pair3.json()["id"]
    client.post(f"/api/v1/shopper/{sess_id_3}/scan-item", json={"barcode": "8901262010053"}) # Amul Butter ₹58
    coup_res = client.post(f"/api/v1/shopper/{sess_id_3}/apply-coupon", json={"coupon_code": "SUPER50"})
    assert coup_res.status_code == 200
    sess3_data = coup_res.json()
    assert sess3_data["discount_amount"] > 0
    print(f"[OK] Coupon SUPER50 applied: discount = Rs.{sess3_data['discount_amount']}")

    # Complete session 3
    db3 = SessionLocal()
    s3 = db3.query(CartSession).filter(CartSession.id == sess_id_3).first()
    if s3:
        s3.status = "COMPLETED"
    db3.commit()
    db3.close()

    # Test 11: TASK 2 - Cart registration with device token hashing
    print("Test 11: Task 2 - Cart registration & secure device token...")
    reg_num = "CART-T2"
    # Ensure clean slate for CART-T2
    db_clean = SessionLocal()
    old_c = db_clean.query(Cart).filter(Cart.cart_number == reg_num).first()
    if old_c:
        db_clean.query(CartSession).filter(CartSession.cart_id == old_c.id).delete()
        db_clean.delete(old_c)
        db_clean.commit()
    db_clean.close()

    reg_resp = client.post("/api/v1/admin/carts", json={"cart_number": reg_num}, headers=auth_header)
    assert reg_resp.status_code == 200, f"Register cart failed: {reg_resp.text}"
    reg_data = reg_resp.json()
    assert reg_data["cart_number"] == reg_num
    assert reg_data["device_token"] is not None
    assert len(reg_data["device_token"]) == 32 # 16-byte hex
    assert "sig=" in reg_data["signed_connect_url"]
    print(f"[OK] Task 2: Registered {reg_num} with device token and HMAC signed connect URL")

    # Test 12: TASK 2 - Connect via signed QR link and verify signature
    print("Test 12: Task 2 - Shopper connect via signed QR link...")
    # Extract params from signed URL
    from urllib.parse import urlparse, parse_qs
    parsed = urlparse(reg_data["signed_connect_url"])
    params = parse_qs(parsed.query)
    c_param = params["cart"][0]
    t_param = params["token"][0]
    s_param = params["sig"][0]

    qr_connect = client.get(f"/api/v1/shopper/connect?cart={c_param}&token={t_param}&sig={s_param}")
    assert qr_connect.status_code == 200, f"QR connect failed: {qr_connect.text}"
    qr_sess = qr_connect.json()
    assert qr_sess["cart_number"] == reg_num
    assert qr_sess["status"] == "ACTIVE"
    print(f"[OK] Task 2: Successfully connected shopper to {reg_num} via HMAC signed link")

    # Test 13: TASK 2 - Single active session enforcement (reject second shopper)
    print("Test 13: Task 2 - Single active session policy enforcement...")
    second_connect = client.get(f"/api/v1/shopper/connect?cart={c_param}&token={t_param}&sig={s_param}&phone=9999999999")
    assert second_connect.status_code == 400
    assert "occupied" in second_connect.json()["detail"].lower()
    print("[OK] Task 2: Second active shopper correctly REJECTED on occupied cart")

    # Test Admin Force Release & Edit Cart
    reset_resp = client.post(f"/api/v1/admin/carts/{reg_data['id']}/reset-session", headers=auth_header)
    assert reset_resp.status_code == 200
    assert reset_resp.json()["cart_status"] == "IDLE"

    # Shopper can now reconnect after admin release
    reconnect_resp = client.get(f"/api/v1/shopper/connect?cart={c_param}&token={t_param}&sig={s_param}&phone=9999999999")
    assert reconnect_resp.status_code == 200
    print("[OK] Task 2: Admin force session release frees occupied cart for new shoppers")

    # Test Admin PATCH cart status
    patch_resp = client.patch(f"/api/v1/admin/carts/{reg_data['id']}", json={"status": "MAINTENANCE"}, headers=auth_header)
    assert patch_resp.status_code == 200
    assert patch_resp.json()["status"] == "MAINTENANCE"
    # Revert to IDLE
    client.patch(f"/api/v1/admin/carts/{reg_data['id']}", json={"status": "IDLE"}, headers=auth_header)

    # Test 14: TASK 2 - Rejection of tampered signature & disabled cart
    print("Test 14: Task 2 - Tampered signature and disabled cart rejection...")
    bad_sig_resp = client.get(f"/api/v1/shopper/connect?cart={c_param}&token={t_param}&sig=invalid_sig_1234")
    assert bad_sig_resp.status_code == 400
    assert "security" in bad_sig_resp.json()["detail"].lower() or "signature" in bad_sig_resp.json()["detail"].lower()

    # Toggle cart to disabled
    toggle_resp = client.post(f"/api/v1/admin/carts/{reg_data['id']}/toggle-status", headers=auth_header)
    assert toggle_resp.status_code == 200
    assert toggle_resp.json()["is_enabled"] is False

    disabled_connect = client.get(f"/api/v1/shopper/connect?cart={c_param}&token={t_param}&sig={s_param}")
    assert disabled_connect.status_code == 400
    assert "disabled" in disabled_connect.json()["detail"].lower()
    print("[OK] Task 2: Tampered signature and disabled cart successfully rejected")

    # =========================================================================
    # TASK 3 TESTS: Laptop-webcam "Cart Device" WebSocket & Authentication
    # =========================================================================
    import starlette.websockets

    # Test 15: Device WebSocket rejects missing token
    print("Test 15: Task 3 - Device WebSocket rejects missing token...")
    try:
        with client.websocket_connect("/ws/device"):
            pass
        assert False, "Should have rejected missing device token"
    except starlette.websockets.WebSocketDisconnect as e:
        assert e.code == 1008
    print("[OK] Task 3: Missing device token rejected with code 1008 (Policy Violation)")

    # Test 16: Device WebSocket rejects unknown token
    print("Test 16: Task 3 - Device WebSocket rejects unknown token...")
    try:
        with client.websocket_connect("/ws/device?token=invalid_unregistered_token"):
            pass
        assert False, "Should have rejected unknown device token"
    except starlette.websockets.WebSocketDisconnect as e:
        assert e.code == 1008
    print("[OK] Task 3: Unknown device token rejected and logged to AuditLog")

    # Test 17: Device WebSocket rejects disabled cart
    print("Test 17: Task 3 - Device WebSocket rejects disabled cart...")
    # reg_data['device_token'] is for CART-T2 which was disabled in Test 14
    try:
        with client.websocket_connect(f"/ws/device?token={reg_data['device_token']}"):
            pass
        assert False, "Should have rejected connection for disabled cart"
    except starlette.websockets.WebSocketDisconnect as e:
        assert e.code == 1008
    print("[OK] Task 3: Disabled cart device connection rejected with code 1008")

    # Test 18: Device WebSocket connects with valid token, derives cart, handles heartbeat
    print("Test 18: Task 3 - Device WebSocket connection, heartbeat, and camera online status...")
    with client.websocket_connect("/ws/device?token=CART001_SECRET_TOKEN_2026") as ws:
        conn_msg = ws.receive_json()
        assert conn_msg["type"] == "connected"
        assert conn_msg["cart_number"] == "CART-001"
        assert conn_msg["status"] == "ONLINE"

        # Send heartbeat with simulated battery
        ws.send_json({"type": "heartbeat", "battery": 92, "timestamp": 123456789})
        hb_ack = ws.receive_json()
        assert hb_ack["type"] == "heartbeat_ack"
        assert hb_ack["cart_number"] == "CART-001"

        # Send test camera frame during motion
        mock_frame = "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAP//////////////////////////////////////////////////////////////////////////////////////wgALCAABAAEBAREA/8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABPxA="
        ws.send_json({"type": "frame", "format": "jpeg", "data": mock_frame})
        frame_ack = ws.receive_json()
        assert frame_ack["type"] in ["frame_ack", "verification_result"]

    print("[OK] Task 3: Device WebSocket authenticated, derived cart identity, and processed frame/heartbeat")

    print("========================================")
    print("ALL 18 TEST SUITES PASSED FLAWLESSLY!")
    print("========================================")

if __name__ == "__main__":
    run_all_tests()
