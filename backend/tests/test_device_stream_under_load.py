import os
import sys
import json
import base64
import hashlib
import time
import pytest
from unittest.mock import patch
from datetime import datetime
from io import BytesIO
from PIL import Image
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Ensure backend root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.main import app
from app.database import Base, get_db
from app.models.user import User
from app.models.cart import Cart
from app.models.product import Product
from app.models.session import CartSession, CartItem
from app.utils.security import hash_password
from app.services.device_watchdog import clear_device_activity

TEST_DATABASE_URL = "sqlite:///:memory:"
test_engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

RAW_DEVICE_TOKEN = "sc_dev_loadtest_cart_secure_token"
TOKEN_HASH = hashlib.sha256(RAW_DEVICE_TOKEN.encode("utf-8")).hexdigest()

def override_get_db():
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()

def _create_dummy_jpeg_base64() -> str:
    """Generate minimal valid JPEG base64 string for testing."""
    img = Image.new("RGB", (100, 100), color=(128, 128, 128))
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=70)
    b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
    return f"data:image/jpeg;base64,{b64}"

@pytest.fixture(autouse=True)
def setup_load_test_db(monkeypatch):
    monkeypatch.setattr("app.database.check_db_health", lambda *args, **kwargs: True)
    monkeypatch.setattr("app.main.check_db_health", lambda *args, **kwargs: True)
    try:
        monkeypatch.setattr("app.migrations.check_schema_health", lambda *args, **kwargs: True)
    except Exception:
        pass
    monkeypatch.setattr("app.websocket.device_handler.SessionLocal", TestingSessionLocal)

    Base.metadata.create_all(bind=test_engine)
    app.dependency_overrides[get_db] = override_get_db

    db = TestingSessionLocal()
    try:
        # Create test user
        user = User(
            id="user-load-test-01",
            email="shopper.load@smartcart.internal",
            password_hash=hash_password("Pass123!"),
            full_name="Load Shopper",
            role="SHOPPER",
            is_active=True
        )
        db.add(user)

        # Create cart
        cart = Cart(
            id="cart-load-01",
            cart_number="CART-LOAD-01",
            qr_code_token="QR-LOAD-01",
            device_token_hash=TOKEN_HASH,
            is_enabled=True,
            camera_status="OFFLINE",
            status="IN_USE",
            battery_level=95
        )
        db.add(cart)

        # Create product
        product = Product(
            id="prod-load-01",
            name="Organic Whole Milk",
            brand="FarmFresh",
            category="Dairy",
            barcode="8901030000001",
            price=4.50,
            is_active=True
        )
        db.add(product)

        # Create active session
        session = CartSession(
            id="session-load-01",
            cart_id="cart-load-01",
            customer_phone="+1234567890",
            status="ACTIVE",
            cart_empty_verified=True,
            started_at=datetime.utcnow()
        )
        db.add(session)

        # Create PENDING item waiting for placement verification
        pending_item = CartItem(
            id="item-load-pending-01",
            session_id="session-load-01",
            product_id="prod-load-01",
            quantity=1,
            unit_price=4.50,
            status="PENDING",
            scanned_at=datetime.utcnow()
        )
        db.add(pending_item)

        db.commit()
    finally:
        db.close()

    yield

    clear_device_activity("cart-load-01")
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=test_engine)

import concurrent.futures

def _receive_text_with_timeout(ws, timeout: float = 5.0) -> str:
    """Receive raw text from TestClient WebSocket with an explicit wall-clock timeout."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(ws.receive_text)
        try:
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            raise TimeoutError(f"WebSocket receive timed out after {timeout}s")

def _receive_json_handling_pings(ws, timeout: float = 5.0):
    """Receive JSON message with timeout, replying with 'pong' if server keepalive 'ping' is received."""
    start_time = time.time()
    while time.time() - start_time < timeout:
        remaining = max(0.5, timeout - (time.time() - start_time))
        raw = _receive_text_with_timeout(ws, timeout=remaining)
        if raw == "ping":
            ws.send_text("pong")
            continue
        return json.loads(raw)
    raise TimeoutError(f"WebSocket receive_json timed out after {timeout}s")

@pytest.mark.timeout(60)
def test_device_stream_20_frames_under_load():
    """Verify device handler processes 20 frames with a PENDING item without closing

    the WebSocket connection, dropping/handling frames safely, and keeping /health responsive.
    """
    client = TestClient(app)
    frame_b64 = _create_dummy_jpeg_base64()

    with client.websocket_connect("/ws/device") as ws:
        # 1. Authenticate via first message
        ws.send_text(json.dumps({
            "type": "auth",
            "token": RAW_DEVICE_TOKEN
        }))
        auth_ack = _receive_json_handling_pings(ws, timeout=5.0)
        assert auth_ack.get("type") == "auth_ok"
        assert auth_ack.get("camera_status") == "ONLINE"

        # 2. Send 20 camera frames through the handler
        processed_count = 0
        for i in range(20):
            ws.send_text(json.dumps({
                "type": "frame",
                "data": frame_b64,
                "motion": False,
                "hand_present": False,
                "face_present": False,
                "timestamp": time.time()
            }))
            resp = _receive_json_handling_pings(ws, timeout=5.0)
            assert resp is not None
            assert resp.get("type") in ("frame_ack", "vision_status", "verification_result", "heartbeat_ack", "frame_error")

            # Check that /health responds and stays 200 during processing
            health_res = client.get("/health")
            assert health_res.status_code == 200
            assert health_res.json().get("status").lower() in ("healthy", "degraded", "starting")
            processed_count += 1
            # Small 20ms pacing between frames to simulate camera interval
            time.sleep(0.02)

        assert processed_count == 20

        # 3. Connection is still alive and responsive to heartbeats
        ws.send_text(json.dumps({
            "type": "heartbeat",
            "battery": 92
        }))
        hb_resp = _receive_json_handling_pings(ws, timeout=5.0)
        assert hb_resp.get("type") == "heartbeat_ack"


@pytest.mark.timeout(30)
def test_judging_takes_5s_and_heartbeat_is_answered():
    """Deliverable 4: Verify that when judging takes 5 seconds on a worker thread,

    the WebSocket receive loop is NOT blocked, and heartbeat messages are answered
    immediately (< 2s) while judging is still actively running.
    """
    client = TestClient(app)
    frame_b64 = _create_dummy_jpeg_base64()

    def slow_judgement(*args, **kwargs):
        time.sleep(5.0)
        return {
            "status": "SUCCESS",
            "broadcasts": [],
            "websocket_messages": [{
                "type": "frame_ack",
                "status": "VERIFIED_ALL",
                "message": "Slow judgement finished."
            }],
            "trace_data": None,
            "item_verified": False
        }

    with patch("app.websocket.device_handler._run_sync_judgement", side_effect=slow_judgement):
        with client.websocket_connect("/ws/device") as ws:
            # 1. Authenticate via first message
            ws.send_text(json.dumps({"type": "auth", "token": RAW_DEVICE_TOKEN}))
            auth_ack = _receive_json_handling_pings(ws, timeout=5.0)
            assert auth_ack.get("type") == "auth_ok"

            # 2. Send frame that triggers 5-second slow judgement
            t_frame_start = time.time()
            ws.send_text(json.dumps({
                "type": "frame",
                "data": frame_b64,
                "motion": False,
                "hand_present": False,
                "face_present": False,
                "timestamp": t_frame_start
            }))

            # Small delay to ensure frame is received and handed off to worker thread
            time.sleep(0.3)

            # 3. Send heartbeat WHILE 5s judging is in progress
            t_hb_sent = time.time()
            ws.send_text(json.dumps({
                "type": "heartbeat",
                "battery": 88
            }))

            # 4. Heartbeat must be answered immediately (< 2.0s), NOT blocked by 5s judging
            hb_ack = _receive_json_handling_pings(ws, timeout=2.0)
            t_hb_recv = time.time()
            assert hb_ack.get("type") == "heartbeat_ack"
            assert (t_hb_recv - t_hb_sent) < 2.0, f"Heartbeat was blocked by judging! Took {t_hb_recv - t_hb_sent:.2f}s"

            # 5. Receive completion of the 5s judging frame
            frame_ack = _receive_json_handling_pings(ws, timeout=7.0)
            t_frame_end = time.time()
            assert frame_ack.get("type") == "frame_ack"
            assert (t_frame_end - t_frame_start) >= 4.8, f"Judgement should have taken ~5s, took {t_frame_end - t_frame_start:.2f}s"


@pytest.mark.slow
@pytest.mark.skip(reason="Heavy load test (50 frames) skipped by default; run with -m slow")
@pytest.mark.timeout(120)
def test_device_stream_50_frames_heavy():
    """Heavy 50-frame stress test, skipped by default."""
    client = TestClient(app)
    frame_b64 = _create_dummy_jpeg_base64()

    with client.websocket_connect("/ws/device") as ws:
        ws.send_text(json.dumps({"type": "auth", "token": RAW_DEVICE_TOKEN}))
        auth_ack = _receive_json_handling_pings(ws, timeout=5.0)
        assert auth_ack.get("type") == "auth_ok"

        for _ in range(50):
            ws.send_text(json.dumps({
                "type": "frame",
                "data": frame_b64,
                "motion": False,
                "hand_present": False,
                "face_present": False,
                "timestamp": time.time()
            }))
            resp = _receive_json_handling_pings(ws, timeout=5.0)
            assert resp is not None
            time.sleep(0.02)
