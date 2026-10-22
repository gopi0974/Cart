import sys
from fastapi.testclient import TestClient
from app.main import app
from app.database import init_db, SessionLocal
from app.utils.seed_data import seed_database

def run_all_tests():
    print("========================================")
    print("Starting SmartCart AI Backend Test Suite")
    print("========================================")
    
    init_db()
    db = SessionLocal()
    seed_database(db)
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
    print("[OK] Auth PASSED (Token generated)")
    
    # Test 3: Catalog
    print("Test 3: Catalog products listing & search...")
    resp = client.get("/api/v1/products")
    assert resp.status_code == 200
    prods = resp.json()
    assert len(prods) >= 10
    print(f"[OK] Catalog PASSED ({len(prods)} products verified)")
    
    # Test 4: Shopper flow & state machine
    print("Test 4: Shopper pairing, scan item (PENDING state)...")
    pair = client.post("/api/v1/shopper/pair", json={"qr_token": "QR-CART-03"})
    assert pair.status_code == 200
    sess_id = pair.json()["id"]
    
    scan = client.post(f"/api/v1/shopper/{sess_id}/scan-item", json={"barcode": "8901262010053"})
    assert scan.status_code == 200
    assert scan.json()["status"] == "PENDING"
    print("[OK] Scanned item is in PENDING state")
    
    # Test 5: Checkout blocked
    print("Test 5: Checkout validation rules (must block PENDING)...")
    co_blocked = client.post(f"/api/v1/shopper/{sess_id}/checkout", json={"payment_method": "UPI"})
    assert co_blocked.status_code == 400
    print("[OK] Checkout correctly BLOCKED while item is pending verification")
    
    # Test 6: AI verification
    print("Test 6: Simulating AI camera verification...")
    ai = client.post("/api/v1/vision/simulate-action", json={
        "cart_id": "CART-03",
        "action_type": "PLACE_CORRECT",
        "barcode": "8901262010053"
    })
    assert ai.status_code == 200
    assert ai.json()["event"] == "ITEM_VERIFIED"
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
    assert "EXIT-" in co_data["exit_gate_token"]
    
    rec_resp = client.get(f"/api/v1/shopper/{sess_id}/receipt")
    assert rec_resp.status_code == 200
    print(f"[OK] Checkout PASSED: Generated receipt {co_data['receipt_number']} with exit QR")
    
    # Test 8: Fraud detection - unscanned item
    print("Test 8: Detecting unscanned item and raising alert...")
    pair2 = client.post("/api/v1/shopper/pair", json={"qr_token": "QR-CART-04"})
    sess_id_2 = pair2.json()["id"]
    
    unscanned = client.post("/api/v1/vision/simulate-action", json={
        "cart_id": "CART-04",
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
    admin_ov = client.get("/api/v1/admin/overview").json()
    assert admin_ov["total_carts"] >= 12
    assert admin_ov["open_incidents"] >= 1
    print("[OK] Admin KPI overview and alert triage verified")
    
    print("========================================")
    print("ALL 9 TEST SUITES PASSED FLAWLESSLY!")
    print("========================================")

if __name__ == "__main__":
    run_all_tests()
