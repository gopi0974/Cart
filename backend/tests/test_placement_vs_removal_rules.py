import json
import time
import uuid
import numpy as np
import pytest
from unittest.mock import AsyncMock, patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.cart import Cart
from app.models.product import Product
from app.models.session import CartSession, CartItem
from app.models.alert import Alert
from app.services.cart_state_machine import ViolationType
from app.websocket.device_handler import process_camera_frame, get_tracker, cart_trackers


engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture
def db_session():
    Base.metadata.create_all(bind=engine)
    cart_trackers.clear()
    db = TestingSessionLocal()
    cart = Cart(id="cart-rules-1", cart_number="CART-R1", qr_code_token="tok-r1", is_enabled=True, status="ACTIVE")
    p1 = Product(id="prod-1", barcode="111111", name="Product One", brand="B1", category="Snacks", price=20.0, weight_grams=100, is_active=True)
    p2 = Product(id="prod-2", barcode="222222", name="Product Two", brand="B2", category="Snacks", price=30.0, weight_grams=150, is_active=True)
    db.add_all([cart, p1, p2])
    db.commit()
    try:
        yield db
    finally:
        db.close()
        cart_trackers.clear()
        Base.metadata.drop_all(bind=engine)


@pytest.mark.anyio
async def test_wrong_item_placement_records_wrong_item_placed_not_removed(db_session):
    """Placing a mismatched item after barcode scan must record WRONG_ITEM_PLACED, never WRONG_ITEM_REMOVED."""
    sess = CartSession(id=str(uuid.uuid4()), cart_id="cart-rules-1", status="ACTIVE", cart_empty_verified=True)
    db_session.add(sess)
    item = CartItem(id="itm-wrong-1", session_id=sess.id, product_id="prod-1", quantity=1, unit_price=20.0, status="PENDING")
    db_session.add(item)
    db_session.commit()

    tracker = get_tracker("cart-rules-1")
    tracker.ref_background = np.zeros((240, 320, 3), dtype=np.uint8)
    tracker.stable_start_time = time.time() - 2.0
    tracker.stable_frame_count = 4

    mock_ws = AsyncMock()
    frame = np.zeros((240, 320, 3), dtype=np.uint8)
    fake_emb = [0.2] * 512

    with (
        patch("app.ai.object_detector.object_detector.detect_all_objects", return_value=[(20, 20, 120, 120)]),
        patch("app.ai.feature_extractor.feature_extractor.get_embedding", return_value=fake_emb),
        patch(
            "app.ai.vector_store.VectorStoreMatcher.find_nearest_product",
            return_value=[{"barcode": "222222", "product_name": "Product Two", "similarity": 0.94}],
        ),
        patch("app.ai.object_detector.object_detector.save_evidence_snapshot", return_value="evidence/wrong.jpg"),
    ):
        await process_camera_frame(
            db=db_session,
            cart_id="cart-rules-1",
            cart_number="CART-R1",
            image_data=frame,
            websocket=mock_ws,
            hand_present=False,
            face_present=False,
            motion=False,
        )

    wrong_placed = db_session.query(Alert).filter(Alert.session_id == sess.id, Alert.violation_type == ViolationType.WRONG_ITEM_PLACED.value).first()
    wrong_removed = db_session.query(Alert).filter(Alert.session_id == sess.id, Alert.violation_type == ViolationType.WRONG_ITEM_REMOVED.value).first()
    assert wrong_placed is not None
    assert wrong_removed is None


@pytest.mark.anyio
async def test_pending_placement_does_not_trigger_unauthorized_remove_on_verified_item(db_session):
    """While a PENDING item is being placed, temporary occlusion/unmatch of an existing VERIFIED item must not fire UNAUTHORIZED_REMOVE."""
    sess = CartSession(id=str(uuid.uuid4()), cart_id="cart-rules-1", status="ACTIVE", cart_empty_verified=True)
    db_session.add(sess)
    verified = CartItem(
        id="itm-ver-1",
        session_id=sess.id,
        product_id="prod-1",
        quantity=1,
        unit_price=20.0,
        status="VERIFIED",
        crop_embedding=json.dumps([-0.8] * 512),
        bounding_box=json.dumps({"x": 0.1, "y": 0.1, "width": 0.2, "height": 0.2}),
    )
    pending = CartItem(id="itm-pend-2", session_id=sess.id, product_id="prod-2", quantity=1, unit_price=30.0, status="PENDING")
    db_session.add_all([verified, pending])
    db_session.commit()

    tracker = get_tracker("cart-rules-1")
    tracker.ref_background = np.zeros((240, 320, 3), dtype=np.uint8)
    tracker.stable_start_time = time.time() - 2.0
    tracker.stable_frame_count = 4

    mock_ws = AsyncMock()
    frame = np.zeros((240, 320, 3), dtype=np.uint8)
    new_item_emb = [0.8] * 512

    with (
        patch("app.ai.object_detector.object_detector.detect_all_objects", return_value=[(140, 40, 240, 140)]),
        patch("app.ai.feature_extractor.feature_extractor.get_embedding", return_value=new_item_emb),
        patch(
            "app.ai.vector_store.VectorStoreMatcher.find_nearest_product",
            return_value=[{"barcode": "222222", "product_name": "Product Two", "similarity": 0.93}],
        ),
        patch("app.ai.object_detector.object_detector.save_evidence_snapshot", return_value="evidence/ok.jpg"),
    ):
        await process_camera_frame(
            db=db_session,
            cart_id="cart-rules-1",
            cart_number="CART-R1",
            image_data=frame,
            websocket=mock_ws,
            hand_present=False,
            face_present=False,
            motion=False,
        )

    rem_alert = db_session.query(Alert).filter(Alert.session_id == sess.id, Alert.violation_type == ViolationType.UNAUTHORIZED_REMOVE.value).first()
    assert rem_alert is None
    db_session.refresh(pending)
    assert pending.status == "VERIFIED"


@pytest.mark.anyio
async def test_reposition_warning_item_continues_to_verify_on_next_frame(db_session):
    """An item in WARNING(REPOSITION) must remain tracked for placement and verify on a better frame, not trigger UNSCANNED_ADD."""
    sess = CartSession(id=str(uuid.uuid4()), cart_id="cart-rules-1", status="ACTIVE", cart_empty_verified=True)
    db_session.add(sess)
    item = CartItem(
        id="itm-repo-1",
        session_id=sess.id,
        product_id="prod-1",
        quantity=1,
        unit_price=20.0,
        status="WARNING",
        warning_reason="REPOSITION",
    )
    db_session.add(item)
    db_session.commit()

    tracker = get_tracker("cart-rules-1")
    tracker.ref_background = np.zeros((240, 320, 3), dtype=np.uint8)
    tracker.stable_start_time = time.time() - 2.0
    tracker.stable_frame_count = 4
    tracker.last_scanned_time = time.time() - 30.0  # past grace period

    mock_ws = AsyncMock()
    frame = np.zeros((240, 320, 3), dtype=np.uint8)

    with (
        patch("app.ai.object_detector.object_detector.detect_all_objects", return_value=[(30, 30, 130, 130)]),
        patch("app.ai.feature_extractor.feature_extractor.get_embedding", return_value=[0.5] * 512),
        patch(
            "app.ai.vector_store.VectorStoreMatcher.find_nearest_product",
            return_value=[{"barcode": "111111", "product_name": "Product One", "similarity": 0.92}],
        ),
        patch("app.ai.object_detector.object_detector.save_evidence_snapshot", return_value="evidence/repo_ok.jpg"),
    ):
        await process_camera_frame(
            db=db_session,
            cart_id="cart-rules-1",
            cart_number="CART-R1",
            image_data=frame,
            websocket=mock_ws,
            hand_present=False,
            face_present=False,
            motion=False,
        )

    db_session.refresh(item)
    assert item.status == "VERIFIED"
    unscanned = db_session.query(Alert).filter(Alert.session_id == sess.id, Alert.violation_type == ViolationType.UNSCANNED_ADD.value).first()
    assert unscanned is None
