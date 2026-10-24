# pyrefly: ignore[missing-import]
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.database import init_db, SessionLocal
from app.utils.seed_data import seed_database

client = TestClient(app)

@pytest.fixture(scope="module", autouse=True)
def setup_test_db():
    init_db()
    db = SessionLocal()
    seed_database(db)
    db.close()
    yield

def test_root_endpoint():
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ONLINE"

def test_auth_login():
    response = client.post("/api/v1/auth/login", json={
        "email": "admin@supermart.com",
        "password": "admin123"
    })
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["role"] == "ADMIN"

def test_catalog_listing():
    response = client.get("/api/v1/products")
    assert response.status_code == 200
    products = response.json()
    assert len(products) >= 10
    barcodes = [p["barcode"] for p in products]
    assert "8901262010053" in barcodes  # Amul Milk

def test_full_shopper_lifecycle_and_checkout_rules():
    # 1. Pair phone with CART-01
    pair_resp = client.post("/api/v1/shopper/pair", json={
        "qr_token": "QR-CART-01",
        "customer_phone": "+919876543210"
    })
    assert pair_resp.status_code == 200
    session_data = pair_resp.json()
    session_id = session_data["id"]
    assert session_data["cart_number"] == "CART-01"

    # 2. Scan barcode for Amul Milk (8901262010053)
    scan_resp = client.post(f"/api/v1/shopper/{session_id}/scan-item", json={
        "barcode": "8901262010053"
    })
    assert scan_resp.status_code == 200
    item = scan_resp.json()
    assert item["status"] == "PENDING"
    assert item["product_barcode"] == "8901262010053"

    # 3. Verify session state - can_checkout should be FALSE because item is still PENDING
    sess_check = client.get(f"/api/v1/shopper/{session_id}")
    assert sess_check.status_code == 200
    assert sess_check.json()["can_checkout"] is False

    # Attempt premature checkout - MUST FAIL
    checkout_fail = client.post(f"/api/v1/shopper/{session_id}/checkout", json={
        "payment_method": "UPI"
    })
    assert checkout_fail.status_code == 400
    assert "Checkout blocked" in checkout_fail.json()["detail"]

    # 4. Simulate AI Cart Camera confirming item physically placed in cart
    ai_verify = client.post("/api/v1/vision/simulate-action", json={
        "cart_id": "CART-01",
        "action_type": "PLACE_CORRECT",
        "barcode": "8901262010053",
        "confidence": 0.96
    })
    assert ai_verify.status_code == 200
    assert ai_verify.json()["event"] == "ITEM_VERIFIED"

    # 5. Session state should now be VERIFIED and can_checkout should be TRUE
    sess_ready = client.get(f"/api/v1/shopper/{session_id}")
    assert sess_ready.status_code == 200
    ready_data = sess_ready.json()
    assert ready_data["can_checkout"] is True
    assert ready_data["items"][0]["status"] == "VERIFIED"

    # 6. Checkout now succeeds!
    checkout_success = client.post(f"/api/v1/shopper/{session_id}/checkout", json={
        "payment_method": "UPI",
        "upi_id": "shopper@oksbi"
    })
    assert checkout_success.status_code == 200
    pay_data = checkout_success.json()
    assert pay_data["status"] == "SUCCESS"
    assert "REC-" in pay_data["receipt_number"]

    # 7. Fetch digital receipt
    receipt_resp = client.get(f"/api/v1/shopper/{session_id}/receipt")
    assert receipt_resp.status_code == 200
    rec = receipt_resp.json()
    assert rec["receipt_number"] == pay_data["receipt_number"]
    assert len(rec["items"]) == 1
    assert rec["total_paid"] > 0

def test_unscanned_item_detection_and_alert():
    # Pair with CART-02
    pair_resp = client.post("/api/v1/shopper/pair", json={"qr_token": "QR-CART-02"})
    session_id = pair_resp.json()["id"]

    # Simulate physical item placed without barcode scan
    unscanned_sim = client.post("/api/v1/vision/simulate-action", json={
        "cart_id": "CART-02",
        "action_type": "PLACE_UNSCANNED",
        "detected_barcode": "7622201745424"  # Cadbury Silk
    })
    assert unscanned_sim.status_code == 200

    # Session should now have active warnings and checkout blocked
    sess_warn = client.get(f"/api/v1/shopper/{session_id}")
    data = sess_warn.json()
    assert len(data["active_warnings"]) > 0
    assert data["can_checkout"] is False

    # Admin alert feed should list this incident
    alerts_resp = client.get("/api/v1/admin/alerts?status=OPEN")
    assert alerts_resp.status_code == 200
    alerts = alerts_resp.json()
    unscanned_alerts = [a for a in alerts if a["alert_type"] == "UNSCANNED_ITEM"]
    assert len(unscanned_alerts) > 0
