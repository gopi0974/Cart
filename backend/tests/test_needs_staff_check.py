import os
import sys
import json
import time
import pytest
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
from app.models.product import Product
from app.models.cart import Cart
from app.models.session import CartSession, CartItem
from app.models.alert import Alert, ReviewCase
from app.models.transaction import AuditLog
from app.models.user import User
from app.services.session_service import SessionService
from app.services.alert_service import AlertService
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
async def test_ten_withheld_frames_create_exactly_one_alert():
    """Verify 10 consecutive withheld frames with face detected produce exactly 1 open alert."""
    db = TestingSessionLocal()

    cart = Cart(
        cart_number="CART-DEDUP1",
        qr_code_token="qr-dedup1",
        device_token_hash="hash-dedup1",
        is_enabled=True,
        status="ACTIVE"
    )
    db.add(cart)
    db.commit()

    session = CartSession(cart_id=cart.id, status="ACTIVE", session_token="tok-dedup1")
    db.add(session)
    db.commit()

    prod = Product(
        name="Book",
        barcode="8901111222233",
        price=350.0,
        brand="Publisher",
        category="Books"
    )
    db.add(prod)
    db.commit()

    item = CartItem(
        session_id=session.id,
        product_id=prod.id,
        status="PENDING",
        quantity=1,
        unit_price=350.0
    )
    db.add(item)
    db.commit()

    tracker = get_tracker(cart.id)
    tracker.face_seen_start_time = time.time() - 2.0  # Already stable past 1.0s gate

    dummy_ws = AsyncMock()
    dummy_ws.send_json = AsyncMock()

    # Simulate 10 frames arriving with face_present=True
    with patch("app.websocket.manager.ws_manager.broadcast_to_cart", new_callable=AsyncMock):
        with patch("app.websocket.manager.ws_manager.broadcast_to_admin", new_callable=AsyncMock):
            for i in range(10):
                await process_camera_frame(
                    db=db,
                    cart_id=cart.id,
                    cart_number=cart.cart_number,
                    image_data=None,
                    websocket=dummy_ws,
                    hand_present=False,
                    face_present=True,
                    motion=False,
                    face_boxes=[{"x": 0.3, "y": 0.2, "width": 0.2, "height": 0.2, "score": 0.85}],
                    detector_profile="privacy"
                )

    # Check alert count
    alerts = db.query(Alert).filter(
        Alert.cart_id == cart.id,
        Alert.session_id == session.id,
        Alert.status == "OPEN"
    ).all()

    # Exact de-duplication: exactly 1 alert created, not 10!
    assert len(alerts) == 1
    assert alerts[0].alert_type == "NEEDS_STAFF_CHECK"
    assert alerts[0].item_id == item.id

    # Item state must be NEEDS_STAFF_CHECK
    db.refresh(item)
    assert item.status == "NEEDS_STAFF_CHECK"
    assert item.warning_reason == "FACE_DETECTED"


@pytest.mark.anyio
async def test_frame_withheld_creates_needs_staff_check_not_unscanned():
    """Verify a face on a pending item never creates an UNSCANNED_ITEM alert."""
    db = TestingSessionLocal()

    cart = Cart(
        cart_number="CART-BOOK1",
        qr_code_token="qr-book1",
        device_token_hash="hash-book1",
        is_enabled=True,
        status="ACTIVE"
    )
    db.add(cart)
    db.commit()

    session = CartSession(cart_id=cart.id, status="ACTIVE", session_token="tok-book1")
    db.add(session)
    db.commit()

    prod = Product(
        name="Book",
        barcode="8901234567890",
        price=499.0,
        brand="O'Reilly",
        category="Books"
    )
    db.add(prod)
    db.commit()

    item = CartItem(
        session_id=session.id,
        product_id=prod.id,
        status="PENDING",
        quantity=1,
        unit_price=499.0
    )
    db.add(item)
    db.commit()

    tracker = get_tracker(cart.id)
    tracker.face_seen_start_time = time.time() - 2.0

    dummy_ws = AsyncMock()
    dummy_ws.send_json = AsyncMock()

    with patch("app.websocket.manager.ws_manager.broadcast_to_cart", new_callable=AsyncMock) as mock_bcast:
        with patch("app.websocket.manager.ws_manager.broadcast_to_admin", new_callable=AsyncMock):
            await process_camera_frame(
                db=db,
                cart_id=cart.id,
                cart_number=cart.cart_number,
                image_data=None,
                websocket=dummy_ws,
                hand_present=False,
                face_present=True,
                motion=False,
                face_boxes=[{"x": 0.4, "y": 0.3, "width": 0.2, "height": 0.25, "score": 0.92}],
                detector_profile="privacy"
            )

    # Ensure NO unscanned item alert was created
    unscanned_alerts = db.query(Alert).filter(
        Alert.cart_id == cart.id,
        Alert.alert_type == "UNSCANNED_ITEM"
    ).all()
    assert len(unscanned_alerts) == 0

    # Ensure the alert created is NEEDS_STAFF_CHECK
    staff_alerts = db.query(Alert).filter(
        Alert.cart_id == cart.id,
        Alert.alert_type == "NEEDS_STAFF_CHECK"
    ).all()
    assert len(staff_alerts) == 1
    assert "automatically" in staff_alerts[0].message or "staff" in staff_alerts[0].message

    # Check broadcast message
    mock_bcast.assert_called()
    called_event, called_payload = mock_bcast.call_args[0][1], mock_bcast.call_args[0][2]
    assert called_event == "ITEM_WARNING"
    assert called_payload["status"] == "NEEDS_STAFF_CHECK"
    assert "staff" in called_payload["message"].lower()


@pytest.mark.anyio
async def test_session_details_single_warning_card():
    """Verify get_session_details produces exactly ONE warning card for a withheld face item."""
    db = TestingSessionLocal()

    cart = Cart(
        cart_number="CART-SINGLECARD",
        qr_code_token="qr-sc1",
        device_token_hash="hash-sc1",
        is_enabled=True,
        status="ACTIVE"
    )
    db.add(cart)
    db.commit()

    session = CartSession(cart_id=cart.id, status="ACTIVE", session_token="tok-sc1")
    db.add(session)
    db.commit()

    prod = Product(name="Novel Book", barcode="8909999888877", price=299.0, brand="Penguin", category="Books")
    db.add(prod)
    db.commit()

    item = CartItem(
        session_id=session.id,
        product_id=prod.id,
        status="NEEDS_STAFF_CHECK",
        warning_reason="FACE_DETECTED",
        quantity=1,
        unit_price=299.0
    )
    db.add(item)
    db.commit()

    # Create associated open alert
    alert = Alert(
        cart_id=cart.id,
        session_id=session.id,
        item_id=item.id,
        alert_type="NEEDS_STAFF_CHECK",
        severity="MEDIUM",
        message="We can't check this item automatically. Please ask staff.",
        status="OPEN"
    )
    db.add(alert)
    db.commit()

    details = SessionService.get_session_details(db, session.id)
    warnings = details["active_warnings"]

    # Exactly ONE warning card returned, NOT two!
    assert len(warnings) == 1
    assert warnings[0]["type"] == "NEEDS_STAFF_CHECK"
    assert warnings[0]["message"] == "We can't check this item automatically. Please ask staff."


@pytest.mark.anyio
async def test_staff_one_click_approval_verifies_item_and_resolves_alert():
    """Verify staff one-click approval verifies the item, resolves the alert, and logs an AuditLog entry."""
    db = TestingSessionLocal()

    admin_user = User(
        email="staff_reviewer@smartcart.internal",
        password_hash="hashed_dummy_pw",
        full_name="Staff Reviewer",
        role="STORE_STAFF",
        is_active=True
    )
    db.add(admin_user)
    db.commit()

    cart = Cart(
        cart_number="CART-REV1",
        qr_code_token="qr-rev1",
        device_token_hash="hash-rev1",
        is_enabled=True,
        status="ALERT"
    )
    db.add(cart)
    db.commit()

    session = CartSession(cart_id=cart.id, status="ACTIVE", session_token="tok-rev1")
    db.add(session)
    db.commit()

    prod = Product(name="History Book", barcode="8901122334455", price=500.0, brand="Publisher", category="Books")
    db.add(prod)
    db.commit()

    item = CartItem(
        session_id=session.id,
        product_id=prod.id,
        status="NEEDS_STAFF_CHECK",
        warning_reason="FACE_DETECTED",
        quantity=1,
        unit_price=500.0
    )
    db.add(item)
    db.commit()

    alert = Alert(
        cart_id=cart.id,
        session_id=session.id,
        item_id=item.id,
        alert_type="NEEDS_STAFF_CHECK",
        severity="MEDIUM",
        message="We can't check this item automatically. Please ask staff.",
        status="OPEN"
    )
    db.add(alert)
    db.commit()

    case = ReviewCase(
        alert_id=alert.id,
        cart_id=cart.id,
        scanned_barcode=prod.barcode,
        confidence=0.0,
        evidence_image_url="https://images.unsplash.com/photo-1542838132-92c53300491e",
        status="PENDING"
    )
    db.add(case)
    db.commit()

    # Generate admin JWT token
    token = create_access_token(data={"sub": admin_user.email, "role": "STORE_STAFF"})

    with patch("app.websocket.manager.ws_manager.broadcast_to_cart", new_callable=AsyncMock) as mock_cart_bcast:
        with patch("app.websocket.manager.ws_manager.broadcast_to_admin", new_callable=AsyncMock):
            resp = client.post(
                f"/api/v1/admin/review-queue/{case.id}/decision",
                headers={"Authorization": f"Bearer {token}"},
                json={"decision": "APPROVE", "notes": "Cover photo verified by staff"}
            )

    assert resp.status_code == 200
    assert resp.json()["status"] == "SUCCESS"

    # Verify item status changed to VERIFIED
    db.refresh(item)
    assert item.status == "VERIFIED"

    # Verify alert status changed to RESOLVED
    db.refresh(alert)
    assert alert.status == "RESOLVED"

    # Verify audit log entry was created
    audit = db.query(AuditLog).filter(
        AuditLog.entity_id == case.id,
        AuditLog.action == "STAFF_ITEM_APPROVAL"
    ).first()
    assert audit is not None
    assert "Cover photo verified" in audit.details_json

    # Verify WebSocket cleared alert on shopper app
    mock_cart_bcast.assert_called()


@pytest.mark.anyio
async def test_session_cleanup_closes_older_sessions_and_resolves_alerts():
    """Verify session cleanup closes older active sessions and resolves their open alerts."""
    db = TestingSessionLocal()

    cart = Cart(
        cart_number="CART-CLEANUP",
        qr_code_token="qr-clean1",
        device_token_hash="hash-clean1",
        is_enabled=True,
        status="ACTIVE"
    )
    db.add(cart)
    db.commit()

    old_session = CartSession(
        cart_id=cart.id,
        status="ACTIVE",
        started_at=datetime.utcnow() - timedelta(hours=1),
        session_token="old-tok"
    )
    db.add(old_session)
    db.commit()

    old_alert = Alert(
        cart_id=cart.id,
        session_id=old_session.id,
        alert_type="UNSCANNED_ITEM",
        severity="HIGH",
        message="Old unscanned alert",
        status="OPEN"
    )
    db.add(old_alert)
    db.commit()

    new_session = CartSession(
        cart_id=cart.id,
        status="ACTIVE",
        started_at=datetime.utcnow(),
        session_token="new-tok"
    )
    db.add(new_session)
    db.commit()

    # Call ensure_single_active_session
    retained = SessionService.ensure_single_active_session(db, cart.id)
    assert retained.id == new_session.id

    # Verify old session ended
    db.refresh(old_session)
    assert old_session.status == "ENDED"
    assert old_session.ended_at is not None

    # Verify old alert resolved
    db.refresh(old_alert)
    assert old_alert.status == "RESOLVED"
    assert old_alert.resolved_at is not None
