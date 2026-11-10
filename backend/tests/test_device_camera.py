import os
import sys
import json
import hashlib
import pytest
from datetime import datetime, timedelta
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Ensure backend root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.main import app
from app.database import Base, get_db
from app.models.user import User
from app.models.cart import Cart
from app.utils.security import hash_password, create_access_token
from app.services.device_watchdog import (
    record_device_activity,
    record_device_frame,
    clear_device_activity,
    get_latest_frame,
    get_frames_per_minute,
    check_cart_timeouts,
    cart_device_last_seen
)
from app.websocket.manager import ws_manager

TEST_DATABASE_URL = "sqlite:///:memory:"
test_engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

RAW_DEVICE_TOKEN = "sc_dev_testtoken_cart003_secure_secret"
TOKEN_HASH = hashlib.sha256(RAW_DEVICE_TOKEN.encode("utf-8")).hexdigest()

DISABLED_RAW_TOKEN = "sc_dev_testtoken_disabled_secure_secret"
DISABLED_TOKEN_HASH = hashlib.sha256(DISABLED_RAW_TOKEN.encode("utf-8")).hexdigest()

def override_get_db():
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()

@pytest.fixture(autouse=True)
def setup_test_db():
    Base.metadata.create_all(bind=test_engine)
    app.dependency_overrides[get_db] = override_get_db

    db = TestingSessionLocal()
    try:
        # Admin User
        admin_user = User(
            id="admin-device-test-id",
            email="admin.device@smartcart.internal",
            password_hash=hash_password("AdminPass!2026"),
            full_name="Device Admin",
            role="ADMIN",
            is_active=True
        )
        db.add(admin_user)

        # Staff User (non-admin/manager)
        staff_user = User(
            id="staff-device-test-id",
            email="staff.device@smartcart.internal",
            password_hash=hash_password("StaffPass!2026"),
            full_name="Device Staff",
            role="STAFF",
            is_active=True
        )
        db.add(staff_user)

        # Enabled Cart CART-003
        cart_003 = Cart(
            id="cart-003-test-id",
            cart_number="CART-003",
            qr_code_token="QR-DEV-003",
            device_token_hash=TOKEN_HASH,
            is_enabled=True,
            camera_status="OFFLINE",
            status="IDLE",
            battery_level=100
        )
        db.add(cart_003)

        # Disabled Cart CART-004
        cart_disabled = Cart(
            id="cart-disabled-test-id",
            cart_number="CART-004",
            qr_code_token="QR-DEV-004",
            device_token_hash=DISABLED_TOKEN_HASH,
            is_enabled=False,
            camera_status="OFFLINE",
            status="IDLE",
            battery_level=90
        )
        db.add(cart_disabled)

        db.commit()
    finally:
        db.close()

    yield

    clear_device_activity("cart-003-test-id")
    clear_device_activity("cart-disabled-test-id")
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=test_engine)

def test_device_token_in_url_rejected():
    """URL query string token must be rejected with close code 4003 (Token in URL forbidden)."""
    client = TestClient(app)
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(f"/ws/device?token={RAW_DEVICE_TOKEN}"):
            pass
    assert exc.value.code == 4003

def test_device_unknown_token_rejected():
    """Unknown token in first message must be rejected with close code 4004 (Unknown device token)."""
    client = TestClient(app)
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/ws/device") as ws:
            ws.send_text(json.dumps({
                "type": "auth",
                "token": "unknown_random_device_token_9999"
            }))
            ws.receive_text()
    assert exc.value.code == 4004

def test_device_malformed_auth_rejected():
    """Malformed or invalid first message must be rejected with close code 4001."""
    client = TestClient(app)
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/ws/device") as ws:
            ws.send_text("not-a-json")
            ws.receive_text()
    assert exc.value.code == 4001

def test_device_disabled_cart_rejected():
    """Attempting connection with token for disabled cart must be rejected with close code 4005."""
    client = TestClient(app)
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/ws/device") as ws:
            ws.send_text(json.dumps({
                "type": "auth",
                "token": DISABLED_RAW_TOKEN
            }))
            ws.receive_text()
    assert exc.value.code == 4005

def test_device_valid_auth_and_heartbeat():
    """Valid auth handshake sets cart camera_status ONLINE and acknowledges heartbeats."""
    client = TestClient(app)
    with client.websocket_connect("/ws/device") as ws:
        # First message auth
        ws.send_text(json.dumps({
            "type": "auth",
            "token": RAW_DEVICE_TOKEN
        }))
        auth_ack = json.loads(ws.receive_text())
        assert auth_ack["type"] == "auth_ok"
        assert auth_ack["cart_number"] == "CART-003"
        assert auth_ack["camera_status"] == "ONLINE"

        # Verify DB cart status updated to ONLINE
        db = TestingSessionLocal()
        try:
            db_cart = db.query(Cart).filter(Cart.id == "cart-003-test-id").first()
            assert db_cart.camera_status == "ONLINE"
        finally:
            db.close()

        # Send heartbeat
        ws.send_text(json.dumps({
            "type": "heartbeat",
            "battery": 75
        }))
        hb_ack = json.loads(ws.receive_text())
        assert hb_ack["type"] == "heartbeat_ack"
        assert hb_ack["cart_number"] == "CART-003"

        # Verify DB battery updated
        db = TestingSessionLocal()
        try:
            db_cart = db.query(Cart).filter(Cart.id == "cart-003-test-id").first()
            assert db_cart.battery_level == 75
        finally:
            db.close()

def test_device_privacy_face_withheld():
    """If face_present is True, the frame image must be discarded and NOT forwarded or saved."""
    client = TestClient(app)
    with client.websocket_connect("/ws/device") as ws:
        ws.send_text(json.dumps({
            "type": "auth",
            "token": RAW_DEVICE_TOKEN
        }))
        auth_ack = json.loads(ws.receive_text())
        assert auth_ack["type"] == "auth_ok"

        # Send frame with face_present: True
        fake_frame = "data:image/jpeg;base64," + "A" * 500
        ws.send_text(json.dumps({
            "type": "frame",
            "data": fake_frame,
            "face_present": True,
            "hand_present": False,
            "motion_level": 0.35
        }))

        ack = json.loads(ws.receive_text())
        assert ack["type"] == "frame_ack"
        assert ack["status"] == "FACE_REDACTED"

        # Verify in-memory preview does NOT have the face frame
        latest = get_latest_frame("cart-003-test-id")
        assert latest is None or latest.get("data") is None

def test_device_reference_frame_preview():
    """Reference frame sent from device must update in-memory staff preview with is_reference flag."""
    client = TestClient(app)
    with client.websocket_connect("/ws/device") as ws:
        ws.send_text(json.dumps({
            "type": "auth",
            "token": RAW_DEVICE_TOKEN
        }))
        json.loads(ws.receive_text())

        ref_image = "data:image/jpeg;base64,/9j/4AAQSkZJRg=="
        ws.send_text(json.dumps({
            "type": "reference_frame",
            "data": ref_image,
            "is_reference": True,
            "face_present": False
        }))

        ack = json.loads(ws.receive_text())
        assert ack["type"] == "reference_ack"
        assert ack["status"] == "REFERENCE_SAVED"

        # Latest frame preview in memory while connected
        latest = get_latest_frame("cart-003-test-id")
        assert latest is not None
        assert latest["is_reference"] is True
        assert latest["data"] == ref_image

def test_device_oversized_frame_rejected():
    """Frame exceeding 200 KB limit must be rejected with frame_error."""
    client = TestClient(app)
    with client.websocket_connect("/ws/device") as ws:
        ws.send_text(json.dumps({
            "type": "auth",
            "token": RAW_DEVICE_TOKEN
        }))
        json.loads(ws.receive_text())

        # Payload over 400,000 characters (> 200 KB base64)
        oversized = "data:image/jpeg;base64," + ("X" * (450 * 1024))
        ws.send_text(json.dumps({
            "type": "frame",
            "data": oversized,
            "face_present": False
        }))

        err = json.loads(ws.receive_text())
        assert err["type"] == "frame_error"
        assert "200 KB" in err["message"]

def test_device_camera_preview_rbac():
    """Admin/Manager can access camera preview; Staff or unauthenticated users are forbidden."""
    client = TestClient(app)
    admin_token = create_access_token(data={"sub": "admin.device@smartcart.internal", "role": "ADMIN"})
    staff_token = create_access_token(data={"sub": "staff.device@smartcart.internal", "role": "STAFF"})

    # 1. Staff -> 403 Forbidden
    res_staff = client.get(
        "/api/v1/admin/carts/cart-003-test-id/camera-preview",
        headers={"Authorization": f"Bearer {staff_token}"}
    )
    assert res_staff.status_code == 403

    # 2. Admin -> 200 OK
    res_admin = client.get(
        "/api/v1/admin/carts/cart-003-test-id/camera-preview",
        headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert res_admin.status_code == 200
    data = res_admin.json()
    assert data["cart_number"] == "CART-003"
    assert "has_frame" in data
    assert "frames_per_minute" in data

def test_device_watchdog_timeout_transition():
    """Cart camera transitions from ONLINE to OFFLINE after 15s without activity."""
    db = TestingSessionLocal()
    try:
        cart = db.query(Cart).filter(Cart.id == "cart-003-test-id").first()
        cart.camera_status = "ONLINE"
        cart.last_heartbeat = datetime.utcnow() - timedelta(seconds=25)
        db.commit()

        # Set memory activity to 25s ago
        cart_device_last_seen[cart.id] = datetime.utcnow() - timedelta(seconds=25)

        # Run watchdog check
        import asyncio
        timed_out = asyncio.run(check_cart_timeouts(db=db, timeout_seconds=15))

        assert cart.id in timed_out

        db.refresh(cart)
        assert cart.camera_status == "OFFLINE"
    finally:
        db.close()

def test_skin_color_heuristics_completely_deleted_and_mediapipe_used():
    """Requirement 7: Test that all legacy skin-colour heuristics are deleted from frontend and real MediaPipe detector is wired."""
    frontend_src = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "src"))
    assert os.path.exists(frontend_src), f"frontend/src not found at {frontend_src}"

    forbidden_tokens = ["isSkin", "skinPixelCount", "upperSkinPixels", "lowerSkinPixels", "skinRatio"]

    for root, _, files in os.walk(frontend_src):
        for f in files:
            if f.endswith((".ts", ".tsx", ".js")):
                filepath = os.path.join(root, f)
                with open(filepath, "r", encoding="utf-8") as file:
                    content = file.read()
                    for token in forbidden_tokens:
                        assert token not in content, (
                            f"Legacy skin-colour heuristic token '{token}' found in {f}! "
                            f"Must be completely replaced by real MediaPipe detector."
                        )

    # Verify real detector integration in both cartCamera.ts and Guided360ScanView.tsx
    cart_camera_path = os.path.join(frontend_src, "device", "cartCamera.ts")
    guided_scan_path = os.path.join(frontend_src, "admin", "Guided360ScanView.tsx")

    with open(cart_camera_path, "r", encoding="utf-8") as f:
        cart_camera_code = f.read()
        assert "privacyDetector" in cart_camera_code
        assert "privacyDetector.detect" in cart_camera_code

    with open(guided_scan_path, "r", encoding="utf-8") as f:
        guided_scan_code = f.read()
        assert "privacyDetector" in guided_scan_code
        assert "privacyDetector.detect" in guided_scan_code

    # Verify self-hosted model and wasm assets exist in frontend/public/mediapipe
    public_mediapipe = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "public", "mediapipe"))
    assert os.path.exists(os.path.join(public_mediapipe, "wasm", "vision_wasm_internal.wasm")), "Missing vision_wasm_internal.wasm in public"
    assert os.path.exists(os.path.join(public_mediapipe, "models", "blaze_face_short_range.tflite")), "Missing blaze_face_short_range.tflite in public"
    assert os.path.exists(os.path.join(public_mediapipe, "models", "hand_landmarker.task")), "Missing hand_landmarker.task in public"

def test_device_safe_failure_when_detector_not_ready():
    """Safe failure: when detector_ready is false, client sends data: null, no image is processed."""
    client = TestClient(app)
    with client.websocket_connect("/ws/device") as ws:
        ws.send_text(json.dumps({
            "type": "auth",
            "token": RAW_DEVICE_TOKEN
        }))
        json.loads(ws.receive_text())

        # Frame with detector_ready: False and data: None
        ws.send_text(json.dumps({
            "type": "frame",
            "data": None,
            "detector_ready": False,
            "face_present": False,
            "hand_present": False,
            "hand_count": 0,
            "face_boxes": [],
            "hand_boxes": [],
            "motion_level": 0.15
        }))

        ack = json.loads(ws.receive_text())
        assert ack["type"] == "frame_ack"
        assert ack["status"] == "METADATA_ONLY"

        # In-memory preview has no image
        latest = get_latest_frame("cart-003-test-id")
        assert latest is None or latest.get("data") is None

def test_device_frame_with_face_and_hand_boxes():
    """Frame transmission transmits normalized boxes, hand_count, and respects face withholding."""
    client = TestClient(app)
    with client.websocket_connect("/ws/device") as ws:
        ws.send_text(json.dumps({
            "type": "auth",
            "token": RAW_DEVICE_TOKEN
        }))
        json.loads(ws.receive_text())

        # Frame with 1 hand box, 1 face box, face_present: True -> image data is null
        ws.send_text(json.dumps({
            "type": "frame",
            "data": None,
            "detector_ready": True,
            "face_present": True,
            "hand_present": True,
            "hand_count": 1,
            "face_boxes": [{"x": 0.4, "y": 0.1, "width": 0.2, "height": 0.25}],
            "hand_boxes": [{"x": 0.2, "y": 0.6, "width": 0.15, "height": 0.2}],
            "processing_ms": 14,
            "motion_level": 0.4
        }))

        ack = json.loads(ws.receive_text())
        assert ack["type"] == "frame_ack"
        assert ack["status"] == "FACE_REDACTED"

