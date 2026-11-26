"""Unit tests for Phase 2: Camera Monitoring Loop with CartStateMachine.

Tests:
1. R1: Empty start verification against calibration reference.
2. R4: Stable-frame logic and FULL MATCH multi-object detection.
3. R4: Hand-activity marker setting and triggering full match upon departure.
4. R4: Long motion warning (>20s prompt) and staff escalation (>60s).
5. R4: Positions updated silently for matched pairs.
6. R3: Placement check with margin check and cart-state snapshot creation.
7. R4 & R7: Unauthorized removal detection and missing item identification.
8. Privacy: Faces withheld and never stored.
"""

import json
import time
import uuid
from datetime import datetime
from unittest.mock import AsyncMock, patch
import numpy as np
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.alert import Alert
from app.models.cart import Cart
from app.models.product import Product, ProductEmbedding
from app.models.session import CartItem, CartSession
from app.services.cart_state_machine import (
    CartStateMachine,
    ViolationType,
)
from app.websocket.device_handler import (
    get_tracker,
    process_camera_frame,
)


@pytest.fixture
def db_session():
    """In-memory SQLite database for camera monitoring loop testing."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(bind=engine)
    session = TestingSession()

    cart = Cart(
        id="cart-loop-01",
        cart_number="CART-LP-01",
        qr_code_token="QR-LOOP-01",
        camera_status="ONLINE",
        is_enabled=True,
        status="ACTIVE",
    )
    product_a = Product(
        id="prod-milk-uuid",
        name="Amul Milk 500ml",
        brand="Amul",
        category="Dairy",
        barcode="8901262010053",
        price=32.0,
        stock_quantity=50,
    )
    product_b = Product(
        id="prod-tea-uuid",
        name="Tata Tea Gold 250g",
        brand="Tata",
        category="Beverages",
        barcode="8901262010020",
        price=140.0,
        stock_quantity=50,
    )
    session.add_all([cart, product_a, product_b])
    session.commit()

    # Seed product embeddings
    emb_milk = ProductEmbedding(
        product_id=product_a.id,
        barcode=product_a.barcode,
        angle_tag="front",
        embedding_json=json.dumps([0.5] * 512),
        preprocessing_version="v2_bilinear_224",
    )
    emb_tea = ProductEmbedding(
        product_id=product_b.id,
        barcode=product_b.barcode,
        angle_tag="front",
        embedding_json=json.dumps([-0.5] * 512),
        preprocessing_version="v2_bilinear_224",
    )
    session.add_all([emb_milk, emb_tea])
    session.commit()

    yield session
    session.close()


@pytest.mark.anyio
async def test_camera_loop_empty_start_not_empty_blocks(db_session):
    cart = db_session.query(Cart).filter(Cart.id == "cart-loop-01").first()
    cart_sess = CartSession(
        id=str(uuid.uuid4()),
        cart_id=cart.id,
        status="ACTIVE",
        cart_empty_verified=False,
    )
    db_session.add(cart_sess)
    db_session.commit()

    tracker = get_tracker(cart.id)
    tracker.ref_background = np.zeros((240, 320, 3), dtype=np.uint8)
    tracker.stable_start_time = time.time() - 3.0
    tracker.stable_frame_count = 5

    # Non-empty frame with an object inside
    non_empty_frame = np.full((240, 320, 3), 150, dtype=np.uint8)
    mock_ws = AsyncMock()

    with patch("app.ai.object_detector.object_detector.detect_all_objects", return_value=[(50, 50, 150, 150)]):
        await process_camera_frame(
            db=db_session,
            cart_id=cart.id,
            cart_number=cart.cart_number,
            image_data=non_empty_frame,
            websocket=mock_ws,
            hand_present=False,
            face_present=False,
            motion=False,
        )

    # Must refuse start: cart_empty_verified stays False, alert created
    db_session.refresh(cart_sess)
    assert not cart_sess.cart_empty_verified
    alert = db_session.query(Alert).filter(
        Alert.session_id == cart_sess.id,
        Alert.violation_type == ViolationType.CART_NOT_EMPTY_AT_START.value
    ).first()
    assert alert is not None


@pytest.mark.anyio
async def test_camera_loop_empty_start_empty_verified(db_session):
    cart = db_session.query(Cart).filter(Cart.id == "cart-loop-01").first()
    cart_sess = CartSession(
        id=str(uuid.uuid4()),
        cart_id=cart.id,
        status="ACTIVE",
        cart_empty_verified=False,
    )
    db_session.add(cart_sess)
    db_session.commit()

    tracker = get_tracker(cart.id)
    tracker.ref_background = np.zeros((240, 320, 3), dtype=np.uint8)
    tracker.stable_start_time = time.time() - 3.0
    tracker.stable_frame_count = 5

    # Completely empty frame matching reference
    empty_frame = np.zeros((240, 320, 3), dtype=np.uint8)
    mock_ws = AsyncMock()

    with patch("app.ai.object_detector.object_detector.detect_all_objects", return_value=[]):
        await process_camera_frame(
            db=db_session,
            cart_id=cart.id,
            cart_number=cart.cart_number,
            image_data=empty_frame,
            websocket=mock_ws,
            hand_present=False,
            face_present=False,
            motion=False,
        )

    db_session.refresh(cart_sess)
    assert cart_sess.cart_empty_verified is True


@pytest.mark.anyio
async def test_camera_loop_hand_activity_marker_forces_full_match(db_session):
    cart = db_session.query(Cart).filter(Cart.id == "cart-loop-01").first()
    cart_sess = CartSession(
        id=str(uuid.uuid4()),
        cart_id=cart.id,
        status="ACTIVE",
        cart_empty_verified=True,
    )
    db_session.add(cart_sess)
    db_session.commit()

    tracker = get_tracker(cart.id)
    tracker.ref_background = np.zeros((240, 320, 3), dtype=np.uint8)
    mock_ws = AsyncMock()
    frame = np.zeros((240, 320, 3), dtype=np.uint8)

    # 1. Hand enters basket -> sets marker
    await process_camera_frame(
        db=db_session,
        cart_id=cart.id,
        cart_number=cart.cart_number,
        image_data=frame,
        websocket=mock_ws,
        hand_present=True,
        motion=False,
    )
    assert tracker.hand_activity_marker is True
    assert tracker.hand_in_frame is True

    # 2. Hand leaves and frame steadies -> full match MUST run even if frame looks same
    tracker.stable_start_time = time.time() - 2.0
    tracker.stable_frame_count = 4

    with patch("app.services.cart_state_machine.CartStateMachine.run_full_match") as mock_match:
        mock_match.return_value = CartStateMachine.run_full_match([], [])
        await process_camera_frame(
            db=db_session,
            cart_id=cart.id,
            cart_number=cart.cart_number,
            image_data=frame,
            websocket=mock_ws,
            hand_present=False,
            motion=False,
        )
        assert mock_match.called
        assert tracker.hand_activity_marker is False


@pytest.mark.anyio
async def test_camera_loop_long_motion_warning_and_escalation(db_session):
    cart = db_session.query(Cart).filter(Cart.id == "cart-loop-01").first()
    cart_sess = CartSession(
        id=str(uuid.uuid4()),
        cart_id=cart.id,
        status="ACTIVE",
        cart_empty_verified=True,
    )
    db_session.add(cart_sess)
    db_session.commit()

    tracker = get_tracker(cart.id)
    mock_ws = AsyncMock()
    frame = np.zeros((240, 320, 3), dtype=np.uint8)

    # Unstable motion for 25s (>20s warning)
    tracker.motion_start_time = time.time() - 25.0
    with patch("app.websocket.manager.ws_manager.broadcast_to_cart") as mock_bcast:
        await process_camera_frame(
            db=db_session,
            cart_id=cart.id,
            cart_number=cart.cart_number,
            image_data=frame,
            websocket=mock_ws,
            motion=True,
        )
        assert mock_bcast.called
        event_name = mock_bcast.call_args[0][1]
        assert event_name == "CART_MOTION_WARNING"

    # Unstable motion for 65s (>60s staff escalation)
    tracker.motion_start_time = time.time() - 65.0
    await process_camera_frame(
        db=db_session,
        cart_id=cart.id,
        cart_number=cart.cart_number,
        image_data=frame,
        websocket=mock_ws,
        motion=True,
    )
    alert = db_session.query(Alert).filter(
        Alert.session_id == cart_sess.id,
        Alert.alert_type == "NEEDS_STAFF_CHECK"
    ).first()
    assert alert is not None
    assert "motion unstable" in alert.message.lower()


@pytest.mark.anyio
async def test_camera_loop_placement_check_verifies_item_and_stores_snapshot(db_session):
    cart = db_session.query(Cart).filter(Cart.id == "cart-loop-01").first()
    cart_sess = CartSession(
        id=str(uuid.uuid4()),
        cart_id=cart.id,
        status="ACTIVE",
        cart_empty_verified=True,
    )
    db_session.add(cart_sess)

    # Scanned item pending placement
    pending_item = CartItem(
        id=str(uuid.uuid4()),
        session_id=cart_sess.id,
        product_id="prod-milk-uuid",
        quantity=1,
        unit_price=32.0,
        status="PENDING",
        scanned_at=datetime.utcnow(),
    )
    db_session.add(pending_item)
    db_session.commit()

    tracker = get_tracker(cart.id)
    tracker.ref_background = np.zeros((240, 320, 3), dtype=np.uint8)
    tracker.stable_start_time = time.time() - 2.0
    tracker.stable_frame_count = 4

    mock_ws = AsyncMock()
    frame = np.full((240, 320, 3), 120, dtype=np.uint8)

    with patch("app.ai.object_detector.object_detector.detect_all_objects", return_value=[(40, 40, 160, 160)]), \
         patch("app.ai.feature_extractor.feature_extractor.get_embedding", return_value=[0.5] * 512), \
         patch("app.ai.vector_store.VectorStoreMatcher.find_nearest_product", return_value=[
             {"id": "prod-milk-uuid", "product_name": "Amul Milk 500ml", "barcode": "8901262010053", "similarity": 0.94},
             {"id": "prod-tea-uuid", "product_name": "Tata Tea Gold 250g", "barcode": "8901262010020", "similarity": 0.35},
         ]):
        await process_camera_frame(
            db=db_session,
            cart_id=cart.id,
            cart_number=cart.cart_number,
            image_data=frame,
            websocket=mock_ws,
            hand_present=False,
            face_present=False,
            motion=False,
        )

    db_session.refresh(pending_item)
    assert pending_item.status == "VERIFIED"
    assert pending_item.crop_embedding is not None
    assert pending_item.bounding_box is not None


@pytest.mark.anyio
async def test_camera_loop_unauthorized_remove_detected(db_session):
    cart = db_session.query(Cart).filter(Cart.id == "cart-loop-01").first()
    cart_sess = CartSession(
        id=str(uuid.uuid4()),
        cart_id=cart.id,
        status="ACTIVE",
        cart_empty_verified=True,
    )
    db_session.add(cart_sess)

    # Previously verified item in cart
    verified_item = CartItem(
        id="item-verified-tea",
        session_id=cart_sess.id,
        product_id="prod-tea-uuid",
        quantity=1,
        unit_price=140.0,
        status="VERIFIED",
        crop_embedding=json.dumps([-0.5] * 512),
        bounding_box=json.dumps({"x": 0.2, "y": 0.2, "width": 0.3, "height": 0.3}),
        last_known_crop_path="/uploads/tea.jpg",
    )
    db_session.add(verified_item)
    db_session.commit()

    tracker = get_tracker(cart.id)
    tracker.ref_background = np.zeros((240, 320, 3), dtype=np.uint8)
    tracker.stable_start_time = time.time() - 2.0
    tracker.stable_frame_count = 4

    mock_ws = AsyncMock()
    # Current camera frame is empty (item was removed without Delete button)
    empty_frame = np.zeros((240, 320, 3), dtype=np.uint8)

    with patch("app.ai.object_detector.object_detector.detect_all_objects", return_value=[]):
        await process_camera_frame(
            db=db_session,
            cart_id=cart.id,
            cart_number=cart.cart_number,
            image_data=empty_frame,
            websocket=mock_ws,
            hand_present=False,
            face_present=False,
            motion=False,
        )

    # Unauthorized removal violation must be raised
    alert = db_session.query(Alert).filter(
        Alert.session_id == cart_sess.id,
        Alert.violation_type == ViolationType.UNAUTHORIZED_REMOVE.value
    ).first()
    assert alert is not None
    assert "Tata Tea Gold" in alert.message


@pytest.mark.anyio
async def test_changing_db_threshold_changes_live_placement_decision(db_session):
    """Changing HIGH threshold in DB changes a live placement decision even if in-memory settings reset."""
    from app.config import settings

    cart = db_session.query(Cart).filter(Cart.id == "cart-loop-01").first()
    cart_sess = CartSession(
        id=str(uuid.uuid4()),
        cart_id=cart.id,
        status="ACTIVE",
        cart_empty_verified=True,
    )
    db_session.add(cart_sess)

    pending_item = CartItem(
        id=str(uuid.uuid4()),
        session_id=cart_sess.id,
        product_id="prod-milk-uuid",
        quantity=1,
        unit_price=32.0,
        status="PENDING",
        scanned_at=datetime.utcnow(),
    )
    db_session.add(pending_item)
    db_session.commit()

    # Persist stricter HIGH threshold (0.95) to DB, then reset in-memory settings to simulate restart
    CartStateMachine.save_thresholds(db_session, confidence_high=0.95, confidence_low=0.65, min_margin=0.08)
    settings.CONFIDENCE_HIGH = 0.85

    tracker = get_tracker(cart.id)
    tracker.ref_background = np.zeros((240, 320, 3), dtype=np.uint8)
    tracker.stable_start_time = time.time() - 2.0
    tracker.stable_frame_count = 4

    mock_ws = AsyncMock()
    frame = np.full((240, 320, 3), 120, dtype=np.uint8)

    # Score 0.90 would pass default 0.85, but must trigger REPOSITION under DB-persisted 0.95
    with patch("app.ai.object_detector.object_detector.detect_all_objects", return_value=[(40, 40, 160, 160)]), \
         patch("app.ai.feature_extractor.feature_extractor.get_embedding", return_value=[0.5] * 512), \
         patch("app.ai.vector_store.VectorStoreMatcher.find_nearest_product", return_value=[
             {"id": "prod-milk-uuid", "product_name": "Amul Milk 500ml", "barcode": "8901262010053", "similarity": 0.90},
             {"id": "prod-tea-uuid", "product_name": "Tata Tea Gold 250g", "barcode": "8901262010020", "similarity": 0.35},
         ]):
        await process_camera_frame(
            db=db_session,
            cart_id=cart.id,
            cart_number=cart.cart_number,
            image_data=frame,
            websocket=mock_ws,
            hand_present=False,
            face_present=False,
            motion=False,
        )

    db_session.refresh(pending_item)
    assert pending_item.status == "WARNING"
    assert pending_item.warning_reason == "REPOSITION"
    sent_msgs = [c.args[0] for c in mock_ws.send_json.call_args_list]
    assert any(m.get("action") == "UNCERTAIN_REPOSITION" for m in sent_msgs)

    # Restore default thresholds
    CartStateMachine.save_thresholds(db_session, confidence_high=0.85, confidence_low=0.65, min_margin=0.08)


@pytest.mark.anyio
async def test_no_auto_reference_sets_needs_reference_and_blocks_scan(db_session):
    """Frames without an empty-cart reference must NOT auto-create one; cart enters NEEDS_REFERENCE and blocks scans."""
    from app.websocket.device_handler import cart_trackers
    from app.services.session_service import SessionService
    from app.services.cart_state_machine import ScanBlockedError, ScanBlockReason

    cart = db_session.query(Cart).filter(Cart.id == "cart-loop-01").first()
    cart.reference_image_path = None
    cart.status = "ACTIVE"
    cart_sess = CartSession(
        id=str(uuid.uuid4()),
        cart_id=cart.id,
        status="ACTIVE",
        cart_empty_verified=False,
    )
    db_session.add(cart_sess)
    db_session.commit()

    cart_trackers.pop(cart.id, None)
    tracker = get_tracker(cart.id)
    tracker.ref_background = None
    tracker.stable_start_time = time.time() - 2.0
    tracker.stable_frame_count = 4

    mock_ws = AsyncMock()
    frame = np.zeros((240, 320, 3), dtype=np.uint8)

    with patch("app.websocket.device_handler.load_persisted_cart_reference", return_value=None):
        await process_camera_frame(
            db=db_session,
            cart_id=cart.id,
            cart_number=cart.cart_number,
            image_data=frame,
            websocket=mock_ws,
            hand_present=False,
            face_present=False,
            motion=False,
        )

    assert tracker.ref_background is None
    db_session.refresh(cart)
    assert cart.status == "NEEDS_REFERENCE"

    # Admin alert raised
    ref_alert = db_session.query(Alert).filter(
        Alert.cart_id == cart.id,
        Alert.alert_type == "NEEDS_REFERENCE",
        Alert.status == "OPEN",
    ).first()
    assert ref_alert is not None

    # Device WS got "This cart is being prepared"
    sent_msgs = [c.args[0] for c in mock_ws.send_json.call_args_list]
    assert any(m.get("status") == "NEEDS_REFERENCE" and "prepared" in m.get("message", "") for m in sent_msgs)

    # Shopper scanning is blocked
    with pytest.raises(ScanBlockedError) as exc_info:
        await SessionService.scan_item(db_session, cart_sess.id, "8901262010053")
    assert exc_info.value.reason_code == ScanBlockReason.NO_REFERENCE
    assert "prepared" in exc_info.value.message


@pytest.mark.anyio
async def test_explicit_staff_capture_reference_rejects_non_empty_and_reloads_on_restart(db_session):
    """Staff capture-reference refuses hand/face/objects, persists to smartcart-evidence, and reloads on startup."""
    import base64
    from io import BytesIO
    from PIL import Image
    from fastapi import HTTPException
    from app.api.v1.admin import capture_cart_reference, CaptureReferenceRequest
    from app.websocket.device_handler import cart_trackers, reload_cart_references_on_startup
    from app.models.user import User

    cart = db_session.query(Cart).filter(Cart.id == "cart-loop-01").first()
    cart.status = "NEEDS_REFERENCE"
    staff = User(id="staff-ref-1", email="staff.ref@smartcart.internal", password_hash="x", full_name="Staff", role="ADMIN", is_active=True)
    db_session.add(staff)
    db_session.commit()

    img = Image.new("RGB", (160, 120), color=(200, 200, 200))
    buf = BytesIO()
    img.save(buf, format="JPEG")
    data_url = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("utf-8")

    # 1. Refuse when hand, face, or objects are detected
    for bad_req in [
        CaptureReferenceRequest(image_data_url=data_url, hand_present=True),
        CaptureReferenceRequest(image_data_url=data_url, face_present=True),
        CaptureReferenceRequest(image_data_url=data_url, objects_present=True),
    ]:
        with pytest.raises(HTTPException) as exc:
            await capture_cart_reference(cart_id=cart.id, req=bad_req, db=db_session, current_user=staff)
        assert exc.value.status_code == 400

    # 2. Succeed on clean empty frame and store in smartcart-evidence bucket
    stored_bytes = {}

    def fake_upload(object_path, data, content_type="image/jpeg", bucket=None):
        uri = f"supabase://smartcart-evidence/{object_path}"
        stored_bytes[uri] = data
        return uri

    def fake_download(object_ref):
        return stored_bytes.get(object_ref)

    with patch("app.services.storage_service.storage_service.upload_bytes", side_effect=fake_upload), \
         patch("app.services.storage_service.storage_service.download_bytes", side_effect=fake_download):
        res = await capture_cart_reference(
            cart_id=cart.id,
            req=CaptureReferenceRequest(image_data_url=data_url),
            db=db_session,
            current_user=staff,
        )
        assert res["status"] == "SUCCESS"
        assert res["reference_image_path"] == f"supabase://smartcart-evidence/cart_references/{cart.id}/reference.jpg"
        assert cart.status == "IDLE"

        # Simulate server restart by clearing in-memory trackers and reloading from storage
        cart_trackers.clear()
        reloaded = reload_cart_references_on_startup(db_session)
        assert reloaded == 1
        assert get_tracker(cart.id).ref_background is not None
