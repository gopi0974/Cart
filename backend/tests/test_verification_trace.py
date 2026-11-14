import os
import sys
import json
import time
import base64
import io
import pytest
import numpy as np
from PIL import Image
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

# Ensure backend root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import app.database as app_db
from app.main import app
from app.config import settings, CURRENT_PREPROCESSING_VERSION
from app.database import Base, get_db
from app.models.product import Product, ProductEmbedding
from app.models.cart import Cart
from app.models.session import CartSession, CartItem, VerificationDecision
from app.models.user import User
from app.ai.verification_engine import verification_engine
from app.ai.feature_extractor import feature_extractor
from app.ai.vector_store import VectorStoreMatcher
from app.services.session_service import SessionService
from app.websocket.device_handler import get_tracker
from app.utils.security import create_access_token

# Isolated test DB
test_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
Base.metadata.create_all(bind=test_engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_test_db():
    Base.metadata.create_all(bind=test_engine)
    app.dependency_overrides[get_db] = override_get_db
    old_engine = app_db.engine
    old_session = app_db.SessionLocal
    app_db.engine = test_engine
    app_db.SessionLocal = TestingSessionLocal
    yield
    Base.metadata.drop_all(bind=test_engine)
    app_db.engine = old_engine
    app_db.SessionLocal = old_session


@pytest.fixture
def db():
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def auth_headers():
    token = create_access_token({"sub": "admin@smartcart.local", "role": "ADMIN"})
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def setup_data(db):
    # Staff admin
    admin = User(
        id="user-admin-1",
        email="admin@smartcart.local",
        full_name="Store Admin",
        password_hash="hash",
        role="ADMIN",
        is_active=True
    )
    db.add(admin)

    # Cart
    cart = Cart(
        id="cart-debug-001",
        cart_number="CART-001",
        qr_code_token="token-001",
        camera_status="ONLINE",
        is_enabled=True,
        battery_level=100
    )
    db.add(cart)

    # Product A (Enrolled with vectors)
    prod_a = Product(
        id="prod-a-coke",
        barcode="890123456001",
        name="Coca Cola 500ml",
        brand="Coca Cola",
        category="Beverages",
        price=40.0,
        weight_grams=500
    )
    # Product B (Different product for cross-testing)
    prod_b = Product(
        id="prod-b-pepsi",
        barcode="890123456002",
        name="Pepsi 500ml",
        brand="Pepsi",
        category="Beverages",
        price=40.0,
        weight_grams=500
    )
    # Product C (No vectors enrolled)
    prod_c = Product(
        id="prod-c-novectors",
        barcode="890123456003",
        name="Organic Dark Chocolate",
        brand="Artisan",
        category="Snacks",
        price=120.0,
        weight_grams=100
    )
    db.add_all([prod_a, prod_b, prod_c])
    db.commit()

    # Enroll vectors for Product A and Product B
    img_a = Image.new("RGB", (224, 224), color=(220, 20, 20))
    vec_a = feature_extractor.get_embedding(img_a)
    VectorStoreMatcher.store_embedding(
        db=db,
        product_id=prod_a.id,
        barcode=prod_a.barcode,
        angle_tag="front",
        vector=vec_a
    )

    img_b = Image.new("RGB", (224, 224), color=(20, 20, 220))
    vec_b = feature_extractor.get_embedding(img_b)
    VectorStoreMatcher.store_embedding(
        db=db,
        product_id=prod_b.id,
        barcode=prod_b.barcode,
        angle_tag="front",
        vector=vec_b
    )

    # Active session on cart
    session = CartSession(
        id="sess-debug-001",
        cart_id=cart.id,
        status="ACTIVE",
        subtotal_amount=0.0,
        total_amount=0.0,
        total_tax=0.0,
        item_count=0
    )
    db.add(session)
    db.commit()

    return {
        "admin": admin,
        "cart": cart,
        "prod_a": prod_a,
        "prod_b": prod_b,
        "prod_c": prod_c,
        "session": session,
        "img_a": img_a,
        "vec_a": vec_a
    }


# =========================================================================
# 1. Trace Test: Scan Product A, Send Recorded Real Frame of A, Expect VERIFIED
# =========================================================================
def test_trace_product_a_scan_and_verification_trace(db, setup_data):
    cart = setup_data["cart"]
    prod_a = setup_data["prod_a"]
    session = setup_data["session"]
    img_a = setup_data["img_a"]

    # 1. Shopper scans Product A -> enters PENDING
    pending_item = CartItem(
        id="item-pending-a",
        session_id=session.id,
        product_id=prod_a.id,
        quantity=1,
        unit_price=prod_a.price,
        status="PENDING",
        scanned_at=datetime.utcnow()
    )
    db.add(pending_item)
    db.commit()

    # 2. Setup empty reference and recorded frame of A placed in cart
    ref_bgr = np.zeros((480, 640, 3), dtype=np.uint8) + 128  # Gray basket
    placed_bgr = ref_bgr.copy()
    # Place Product A in center of basket
    placed_bgr[140:340, 220:420] = [20, 20, 220]  # BGR equivalent of red

    # Configure tracker with empty reference
    tracker = get_tracker(cart.id)
    tracker.ref_background = ref_bgr.copy()
    tracker.last_stable_frame = placed_bgr.copy()

    # 3. Evaluate item placement
    result = verification_engine.evaluate_item_placement(
        db=db,
        claimed_barcode=prod_a.barcode,
        image_data=placed_bgr,
        ref_background=tracker.ref_background,
        cart_id=cart.id,
        session_id=session.id,
        item_id=pending_item.id
    )

    # 4. Verify decision is AUTO_APPROVE and item is VERIFIED
    assert result["decision"] == "AUTO_APPROVE"
    assert result["status"] == "VERIFIED"
    assert result["confidence"] >= settings.CONFIDENCE_HIGH

    # 5. Inspect complete 10-stage trace
    trace = result.get("trace")
    assert trace is not None, "Trace dictionary must be present in evaluation result"

    print("\n--- COMPLETE VERIFICATION TRACE OUTPUT ---")
    print(json.dumps(trace, indent=2))
    print("------------------------------------------\n")

    assert trace["stopped_at"] == "completed"
    assert trace["camera_online"] is True
    assert trace["empty_reference_present"] is True
    assert trace["hand_present"] is False
    assert trace["face_present"] is False
    assert trace["frame_stable"] is True
    assert trace["changed_region_found"] is True
    assert trace["changed_region_box"] is not None
    assert trace["crop_status"] == "saved"
    assert trace["preprocessing_used"] == CURRENT_PREPROCESSING_VERSION
    assert trace["embedding_ms"] > 0
    assert trace["score_scanned"] >= 0.85
    assert trace["scanned_barcode"] == prod_a.barcode
    assert trace["scanned_product_name"] == prod_a.name
    assert trace["scanned_has_vectors"] is True
    assert trace["scanned_vector_count"] >= 1
    assert trace["decision"] == "AUTO_APPROVE"
    assert trace["threshold_high"] == settings.CONFIDENCE_HIGH
    assert trace["threshold_low"] == settings.CONFIDENCE_LOW


# =========================================================================
# 2. Test Stopped-At Stages (Hand, Face, No Vectors, Empty Reference)
# =========================================================================
def test_trace_stopped_at_conditions(db, setup_data):
    cart = setup_data["cart"]
    prod_a = setup_data["prod_a"]
    prod_c = setup_data["prod_c"]
    session = setup_data["session"]
    frame = np.zeros((480, 640, 3), dtype=np.uint8)

    # Condition A: Hand present in frame
    res_hand = verification_engine.evaluate_item_placement(
        db=db,
        claimed_barcode=prod_a.barcode,
        image_data=frame,
        hand_present=True,
        face_present=False,
        cart_id=cart.id,
        session_id=session.id
    )
    assert res_hand["decision"] == "HAND_IN_CART"
    assert res_hand["trace"]["stopped_at"] == "hand_present"
    assert res_hand["trace"]["crop_status"] == "withheld"

    # Condition B: Face present in frame
    res_face = verification_engine.evaluate_item_placement(
        db=db,
        claimed_barcode=prod_a.barcode,
        image_data=frame,
        hand_present=False,
        face_present=True,
        cart_id=cart.id,
        session_id=session.id
    )
    assert res_face["decision"] == "FACE_DETECTED_WITHHELD"
    assert res_face["trace"]["stopped_at"] == "face_present"
    assert res_face["trace"]["crop_status"] == "withheld"

    # Condition C: Product with NO visual vectors enrolled (Product C)
    res_novectors = verification_engine.evaluate_item_placement(
        db=db,
        claimed_barcode=prod_c.barcode,
        image_data=frame,
        hand_present=False,
        face_present=False,
        cart_id=cart.id,
        session_id=session.id
    )
    assert res_novectors["trace"]["stopped_at"] == "no_product_vectors"
    assert res_novectors["trace"]["scanned_has_vectors"] is False
    assert res_novectors["trace"]["scanned_vector_count"] == 0

    # Condition D: Empty reference missing
    res_noref = verification_engine.evaluate_item_placement(
        db=db,
        claimed_barcode=prod_a.barcode,
        image_data=frame,
        ref_background=None,
        hand_present=False,
        face_present=False,
        cart_id=cart.id,
        session_id=session.id
    )
    assert res_noref["trace"]["empty_reference_present"] is False


# =========================================================================
# 3. Test /admin/system-health Pending Items Diagnostics
# =========================================================================
def test_system_health_pending_items_diagnostics(db, setup_data, auth_headers):
    prod_c = setup_data["prod_c"]
    session = setup_data["session"]

    # Add Product C (no vectors) as pending item in session
    pending_item = CartItem(
        id="item-test-novectors",
        session_id=session.id,
        product_id=prod_c.id,
        quantity=1,
        unit_price=prod_c.price,
        status="PENDING",
        scanned_at=datetime.utcnow()
    )
    db.add(pending_item)
    db.commit()

    resp = client.get("/admin/system-health?fresh=true", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()

    assert "pending_items_diagnostics" in data
    diag_list = data["pending_items_diagnostics"]
    assert len(diag_list) >= 1

    item_diag = next((i for i in diag_list if i["scanned_barcode"] == prod_c.barcode), None)
    assert item_diag is not None
    assert item_diag["has_vectors"] is False
    assert item_diag["vector_count"] == 0
    assert item_diag["product_name"] == prod_c.name


# =========================================================================
# 4. Test Pending Item > 15s Computes Clear Diagnostic Reason
# =========================================================================
def test_pending_item_exceeding_15_seconds_shows_reason(db, setup_data):
    cart = setup_data["cart"]
    prod_c = setup_data["prod_c"]
    session = setup_data["session"]

    # Pending item scanned 25 seconds ago
    old_time = datetime.utcnow() - timedelta(seconds=25)
    pending_item = CartItem(
        id="item-delayed-15s",
        session_id=session.id,
        product_id=prod_c.id,
        quantity=1,
        unit_price=prod_c.price,
        status="PENDING",
        scanned_at=old_time
    )
    db.add(pending_item)
    db.commit()

    details = SessionService.get_session_details(db, session.id)
    assert details["items"] is not None

    # Check reason computed
    reason = getattr(pending_item, "pending_reason", None)
    assert reason in (
        "camera offline",
        "no reference",
        "hand in view",
        "face withheld",
        "product has no recognition data",
        "below threshold",
        "waiting for steady placement"
    )

    # Check warning string formatted for shopper
    warning = next((w for w in details["active_warnings"] if w["type"] == "PENDING_ITEM"), None)
    assert warning is not None
    assert "Waiting for the camera to check this item" in warning["message"]


# =========================================================================
# 5. Test Save Debug Frame Endpoint (Product Crop Only, Size Gated)
# =========================================================================
def test_save_debug_frame_endpoint(db, setup_data, auth_headers):
    # Valid crop (300x300 px)
    crop_img = Image.new("RGB", (300, 300), color=(100, 150, 200))
    buf = io.BytesIO()
    crop_img.save(buf, format="PNG")
    crop_b64 = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("utf-8")

    resp = client.post(
        "/api/v1/vision/debug-frames",
        json={
            "image_data": crop_b64,
            "cart_number": "CART-001",
            "barcode": "890123456001",
            "product_name": "Coca Cola 500ml",
            "notes": "Test debug product crop"
        },
        headers=auth_headers
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "SAVED"
    assert data["width"] == 300
    assert data["height"] == 300
    assert os.path.exists(data["file_path"])

    # Clean up test file
    try:
        os.remove(data["file_path"])
    except Exception:
        pass

    # Invalid oversized frame (900x900 px) -> Rejected
    oversized = Image.new("RGB", (900, 900), color=(50, 50, 50))
    buf_over = io.BytesIO()
    oversized.save(buf_over, format="PNG")
    over_b64 = base64.b64encode(buf_over.getvalue()).decode("utf-8")

    resp_over = client.post(
        "/api/v1/vision/debug-frames",
        json={"image_data": over_b64},
        headers=auth_headers
    )
    assert resp_over.status_code == 400
    assert "exceed crop maximum" in resp_over.json()["detail"]


# =========================================================================
# 6. Test Admin Verification Trace and Run Now Endpoints
# =========================================================================
def test_admin_cart_verification_trace_and_run_now_endpoints(db, setup_data, auth_headers):
    cart = setup_data["cart"]
    prod_a = setup_data["prod_a"]
    session = setup_data["session"]

    # Pending item
    pending_item = CartItem(
        id="item-admin-run",
        session_id=session.id,
        product_id=prod_a.id,
        quantity=1,
        unit_price=prod_a.price,
        status="PENDING",
        scanned_at=datetime.utcnow()
    )
    db.add(pending_item)
    db.commit()

    # Setup frame in tracker
    tracker = get_tracker(cart.id)
    ref_bgr = np.zeros((480, 640, 3), dtype=np.uint8) + 100
    placed_bgr = ref_bgr.copy()
    placed_bgr[150:350, 200:400] = [20, 20, 220]
    tracker.ref_background = ref_bgr
    tracker.last_stable_frame = placed_bgr

    # 1. Staff triggers "Run verification now"
    resp_run = client.post(f"/api/v1/admin/carts/{cart.id}/run-verification", headers=auth_headers)
    assert resp_run.status_code == 200
    run_data = resp_run.json()
    assert run_data["status"] == "SUCCESS"
    assert run_data["decision"] == "AUTO_APPROVE"
    assert run_data["trace"]["stopped_at"] == "completed"

    # 2. Staff views Verification Trace
    resp_trace = client.get(f"/api/v1/admin/carts/{cart.id}/verification-trace", headers=auth_headers)
    assert resp_trace.status_code == 200
    trace_page = resp_trace.json()
    assert trace_page["cart_id"] == cart.id
    assert trace_page["total_judgements"] >= 1
    first_trace = trace_page["traces"][0]
    assert first_trace["decision"] == "AUTO_APPROVE"
    assert first_trace["stopped_at"] == "completed"

