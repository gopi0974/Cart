import os
import sys
import json
import time
import pytest
import numpy as np
from datetime import datetime, timedelta
from unittest.mock import patch, AsyncMock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.main import app
from app.config import settings
from app.database import Base, get_db
from app.models.product import Product, ProductEmbedding
from app.models.cart import Cart
from app.models.session import CartSession, CartItem, VerificationDecision
from app.models.alert import Alert
from app.models.user import User
from app.services.session_service import SessionService
from app.websocket.device_handler import get_tracker, process_camera_frame
from app.utils.security import create_access_token

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
    yield
    Base.metadata.drop_all(bind=test_engine)


@pytest.mark.anyio
async def test_ensure_single_active_session_deduplication():
    """Verify multiple ACTIVE sessions on a cart are closed, retaining only the latest one."""
    db = TestingSessionLocal()
    cart = Cart(
        cart_number="CART-DUP1",
        qr_code_token="qr-dup1",
        device_token_hash="hash-dup1",
        is_enabled=True,
        status="ACTIVE"
    )
    db.add(cart)
    db.commit()

    # Create 3 active sessions with different start times
    s1 = CartSession(cart_id=cart.id, status="ACTIVE", started_at=datetime.utcnow() - timedelta(minutes=10))
    s2 = CartSession(cart_id=cart.id, status="ACTIVE", started_at=datetime.utcnow() - timedelta(minutes=5))
    s3 = CartSession(cart_id=cart.id, status="ACTIVE", started_at=datetime.utcnow())
    db.add_all([s1, s2, s3])
    db.commit()

    # Query before deduplication
    active_before = db.query(CartSession).filter(CartSession.cart_id == cart.id, CartSession.status == "ACTIVE").all()
    assert len(active_before) == 3

    # Run ensure_single_active_session
    retained = SessionService.ensure_single_active_session(db, cart.id)
    assert retained is not None
    assert retained.id == s3.id

    # Verify older sessions are ENDED
    db.refresh(s1)
    db.refresh(s2)
    db.refresh(s3)
    assert s1.status == "ENDED"
    assert s2.status == "ENDED"
    assert s3.status == "ACTIVE"
    db.close()


@pytest.mark.anyio
async def test_scan_item_updates_tracker_and_clears_unscanned_alert():
    """Verify scan_item invalidates cached pending list and auto-clears any open unscanned alerts."""
    db = TestingSessionLocal()
    cart = Cart(
        cart_number="CART-SCAN1",
        qr_code_token="qr-scan1",
        device_token_hash="hash-scan1",
        is_enabled=True,
        status="ACTIVE"
    )
    product = Product(
        name="Organic Almond Milk",
        barcode="890123456789",
        price=3.99,
        brand="AlmondCo",
        category="Dairy",
        is_active=True
    )
    db.add_all([cart, product])
    db.commit()

    session = CartSession(cart_id=cart.id, status="ACTIVE")
    db.add(session)
    db.commit()

    # Simulate an open unscanned item alert and placeholder
    alert = Alert(
        cart_id=cart.id,
        session_id=session.id,
        alert_type="UNSCANNED_ITEM",
        severity="HIGH",
        message="Unscanned item placed in cart",
        status="OPEN"
    )
    placeholder = CartItem(
        session_id=session.id,
        product_id=product.id,
        quantity=1,
        unit_price=product.price,
        status="WARNING_UNSCANNED"
    )
    db.add_all([alert, placeholder])
    db.commit()

    # Tracker state before scan
    tracker = get_tracker(cart.id)
    tracker.last_scanned_time = 0.0

    # User scans barcode
    with patch("app.websocket.manager.ws_manager.broadcast_to_cart", new_callable=AsyncMock) as mock_ws:
        item = await SessionService.scan_item(db, session.id, "890123456789")

    assert item.status == "PENDING"
    assert item.product_id == product.id

    # Check tracker was immediately notified
    assert tracker.last_scanned_time > 0.0
    assert tracker.last_pending_barcode == "890123456789"
    assert tracker.has_pending_items is True

    # Verify open UNSCANNED_ITEM alert was resolved automatically
    db.refresh(alert)
    assert alert.status == "RESOLVED"
    assert "Auto-cleared" in alert.resolution_notes

    # Verify placeholder was cleaned up
    remaining_placeholders = db.query(CartItem).filter(
        CartItem.session_id == session.id,
        CartItem.status == "WARNING_UNSCANNED"
    ).count()
    assert remaining_placeholders == 0

    # Verify ALERT_CLEARED broadcast occurred
    broadcast_events = [call.args[1] for call in mock_ws.call_args_list]
    assert "ALERT_CLEARED" in broadcast_events
    db.close()


@pytest.mark.anyio
async def test_verify_item_placement_clears_unscanned_alert():
    """Verify that camera verification auto-clears any open unscanned alerts."""
    db = TestingSessionLocal()
    cart = Cart(
        cart_number="CART-VERIF1",
        qr_code_token="qr-verif1",
        device_token_hash="hash-verif1",
        is_enabled=True,
        status="ACTIVE"
    )
    product = Product(
        name="Granola Bar",
        barcode="778899001122",
        price=1.99,
        brand="HealthyBite",
        category="Snacks",
        is_active=True
    )
    db.add_all([cart, product])
    db.commit()

    session = CartSession(cart_id=cart.id, status="ACTIVE")
    db.add(session)
    db.commit()

    pending_item = CartItem(
        session_id=session.id,
        product_id=product.id,
        quantity=1,
        unit_price=product.price,
        status="PENDING",
        scanned_at=datetime.utcnow()
    )
    alert = Alert(
        cart_id=cart.id,
        session_id=session.id,
        alert_type="UNSCANNED_ITEM",
        severity="HIGH",
        message="Unscanned item placed in cart",
        status="OPEN"
    )
    db.add_all([pending_item, alert])
    db.commit()

    with patch("app.websocket.manager.ws_manager.broadcast_to_cart", new_callable=AsyncMock) as mock_ws:
        verified_item = await SessionService.verify_item_placement(
            db, session.id, "778899001122", confidence=0.96
        )

    assert verified_item is not None
    assert verified_item.status == "VERIFIED"

    # Verify alert was auto-cleared
    db.refresh(alert)
    assert alert.status == "RESOLVED"
    assert "item verified" in alert.resolution_notes

    broadcast_events = [call.args[1] for call in mock_ws.call_args_list]
    assert "ALERT_CLEARED" in broadcast_events
    assert "ITEM_VERIFIED" in broadcast_events
    db.close()


@pytest.mark.anyio
async def test_grace_period_suppresses_unscanned_alert_within_10s():
    """Verify camera frame within 1s and 5s of scan does NOT raise unscanned item alert."""
    db = TestingSessionLocal()
    cart = Cart(
        cart_number="CART-GRACE1",
        qr_code_token="qr-grace1",
        device_token_hash="hash-grace1",
        is_enabled=True,
        status="ACTIVE"
    )
    db.add(cart)
    db.commit()

    session = CartSession(cart_id=cart.id, status="ACTIVE")
    db.add(session)
    db.commit()

    tracker = get_tracker(cart.id)
    test_frame = np.full((240, 320, 3), 128, dtype=np.uint8)
    tracker.ref_background = np.zeros((240, 320, 3), dtype=np.uint8)

    mock_ws = AsyncMock()

    # Scenario 1: Scan occurred 1 second ago -> Grace period active (1s < 10s)
    tracker.last_scanned_time = time.time() - 1.0
    tracker.stable_start_time = time.time() - 2.0
    tracker.stable_frame_count = 5
    tracker.last_motion_time = time.time()
    tracker.last_judged_time = time.time() - 5.0

    await process_camera_frame(
        db=db,
        cart_id=cart.id,
        cart_number=cart.cart_number,
        image_data=test_frame,
        websocket=mock_ws,
        hand_present=False,
        face_present=False,
        motion=False
    )

    # Check mock_ws sent vision_status AWAITING_PLACEMENT, NOT UNSCANNED_ITEM_DETECTED
    sent_msgs = [call.args[0] for call in mock_ws.send_json.call_args_list]
    awaiting_msgs = [m for m in sent_msgs if m.get("status") == "AWAITING_PLACEMENT"]
    assert len(awaiting_msgs) > 0
    assert "Grace period active" in awaiting_msgs[0].get("message", "")

    # Ensure no alert was created
    alerts_count = db.query(Alert).filter(Alert.cart_id == cart.id, Alert.alert_type == "UNSCANNED_ITEM").count()
    assert alerts_count == 0

    mock_ws.reset_mock()

    # Scenario 2: Scan occurred 5 seconds ago -> Grace period active (5s < 10s)
    tracker.last_scanned_time = time.time() - 5.0
    tracker.stable_start_time = time.time() - 2.0
    tracker.stable_frame_count = 5
    tracker.last_motion_time = time.time()
    tracker.last_judged_time = time.time() - 5.0

    await process_camera_frame(
        db=db,
        cart_id=cart.id,
        cart_number=cart.cart_number,
        image_data=test_frame,
        websocket=mock_ws,
        hand_present=False,
        face_present=False,
        motion=False
    )
    sent_msgs_5s = [call.args[0] for call in mock_ws.send_json.call_args_list]
    awaiting_msgs_5s = [m for m in sent_msgs_5s if m.get("status") == "AWAITING_PLACEMENT"]
    assert len(awaiting_msgs_5s) > 0

    # Ensure still no alert created
    alerts_count = db.query(Alert).filter(Alert.cart_id == cart.id, Alert.alert_type == "UNSCANNED_ITEM").count()
    assert alerts_count == 0
    db.close()


@pytest.mark.anyio
async def test_unscanned_alert_raised_when_no_scan_and_grace_period_expired():
    """Verify unscanned item alert IS raised when no item pending AND >10s elapsed since any scan."""
    db = TestingSessionLocal()
    cart = Cart(
        cart_number="CART-NO-SCAN",
        qr_code_token="qr-noscan",
        device_token_hash="hash-noscan",
        is_enabled=True,
        status="ACTIVE"
    )
    product = Product(
        name="Orange Juice",
        barcode="554433221100",
        price=2.49,
        brand="Tropic",
        category="Beverages",
        is_active=True
    )
    db.add_all([cart, product])
    db.commit()

    # Seed vector for matching
    emb = ProductEmbedding(
        product_id=product.id,
        barcode=product.barcode,
        angle_tag="front",
        embedding_json=json.dumps(np.random.randn(512).astype(np.float32).tolist()),
        preprocessing_version="v2_bilinear_224"
    )
    db.add(emb)

    session = CartSession(cart_id=cart.id, status="ACTIVE")
    db.add(session)
    db.commit()

    tracker = get_tracker(cart.id)
    # Scan occurred 15 seconds ago (grace period 10s is expired)
    tracker.last_scanned_time = time.time() - 15.0
    tracker.stable_start_time = time.time() - 2.0
    tracker.stable_frame_count = 5
    tracker.last_motion_time = time.time()
    tracker.last_judged_time = time.time() - 5.0

    test_frame = np.full((240, 320, 3), 128, dtype=np.uint8)
    tracker.ref_background = np.zeros((240, 320, 3), dtype=np.uint8)

    mock_ws = AsyncMock()

    with patch("app.ai.object_detector.object_detector.compute_motion_box", return_value=(20, 20, 200, 200)), \
         patch("app.ai.vector_store.VectorStoreMatcher.find_nearest_product", return_value=[{"id": product.id, "product_id": product.id, "product_name": product.name, "barcode": product.barcode, "similarity": 0.88}]):
        await process_camera_frame(
            db=db,
            cart_id=cart.id,
            cart_number=cart.cart_number,
            image_data=test_frame,
            websocket=mock_ws,
            hand_present=False,
            face_present=False,
            motion=False
        )

    # Verify UNSCANNED_ITEM_DETECTED was triggered
    sent_msgs = [call.args[0] for call in mock_ws.send_json.call_args_list]
    unscanned_results = [m for m in sent_msgs if m.get("action") == "UNSCANNED_ITEM_DETECTED"]
    assert len(unscanned_results) > 0

    # Verify Alert in DB
    alert = db.query(Alert).filter(Alert.cart_id == cart.id, Alert.alert_type == "UNSCANNED_ITEM").first()
    assert alert is not None
    assert alert.status == "OPEN"

    # Verify tracker trace contains pending_items and unscanned_alert_reason
    assert len(tracker.recent_traces) > 0
    latest_trace = tracker.recent_traces[0]
    assert latest_trace.get("cart_id") == cart.id
    assert latest_trace.get("session_id") == session.id
    assert "pending_items" in latest_trace
    assert "unscanned_alert_reason" in latest_trace
    assert "grace period expired" in latest_trace["unscanned_alert_reason"]
    db.close()
