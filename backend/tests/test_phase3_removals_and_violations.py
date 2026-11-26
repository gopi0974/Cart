import uuid
import json
import time
from datetime import datetime
import pytest
import numpy as np
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.cart import Cart
from app.models.product import Product
from app.models.session import CartSession, CartItem
from app.models.alert import Alert
from app.services.cart_state_machine import (
    CartStateMachine,
    ViolationType,
    ScanBlockReason,
    ScanBlockedError,
    StoredItemSnapshot,
    BoundingBox,
    DetectedRegion
)
from app.services.session_service import SessionService
from app.ai.object_detector import ObjectDetector, cleanup_expired_evidence
from app.config import settings

TEST_DB_URL = "sqlite:///:memory:"

@pytest.fixture
def db_session():
    engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = Session()

    # Seed test cart and product
    cart = Cart(
        id="cart-phase3-01",
        cart_number="CART-P3",
        qr_code_token="token-phase3-01",
        device_token_hash="hash-phase3-01",
        status="ACTIVE",
        camera_status="ONLINE"
    )
    product_a = Product(
        id="prod-phase3-a",
        name="Organic Milk",
        barcode="8901234001",
        price=50.0,
        brand="FarmFresh",
        category="Dairy",
        is_active=True
    )
    product_b = Product(
        id="prod-phase3-b",
        name="Dark Chocolate",
        barcode="8901234002",
        price=100.0,
        brand="ChocoCo",
        category="Snacks",
        is_active=True
    )
    session.add_all([cart, product_a, product_b])
    session.commit()

    yield session
    session.close()
    Base.metadata.drop_all(bind=engine)


# ==============================================================================
# R5: REMOVAL FLOW TESTS
# ==============================================================================

@pytest.mark.anyio
async def test_r5_pending_item_deleted_immediately_without_camera_check(db_session):
    cart_sess = CartSession(
        id=str(uuid.uuid4()),
        cart_id="cart-phase3-01",
        status="ACTIVE",
        subtotal_amount=50.0,
        total_amount=50.0,
        item_count=1
    )
    db_session.add(cart_sess)
    item = CartItem(
        id=str(uuid.uuid4()),
        session_id=cart_sess.id,
        product_id="prod-phase3-a",
        quantity=1,
        unit_price=50.0,
        status="PENDING",
        scanned_at=datetime.utcnow()
    )
    db_session.add(item)
    db_session.commit()

    # Shopper taps delete on PENDING item
    res = await SessionService.initiate_item_removal(db_session, cart_sess.id, item.id)
    assert res["status"] == "DELETED"

    # Verify item is removed completely from database
    item_in_db = db_session.query(CartItem).filter(CartItem.id == item.id).first()
    assert item_in_db is None

    # Verify totals updated to 0
    db_session.refresh(cart_sess)
    assert cart_sess.subtotal_amount == 0.0
    assert cart_sess.item_count == 0


@pytest.mark.anyio
async def test_r5_verified_item_initiate_remove_sets_removing_and_blocks_scan(db_session):
    cart_sess = CartSession(
        id=str(uuid.uuid4()),
        cart_id="cart-phase3-01",
        status="ACTIVE",
        subtotal_amount=50.0,
        total_amount=50.0,
        item_count=1
    )
    db_session.add(cart_sess)
    item = CartItem(
        id=str(uuid.uuid4()),
        session_id=cart_sess.id,
        product_id="prod-phase3-a",
        quantity=1,
        unit_price=50.0,
        status="VERIFIED",
        scanned_at=datetime.utcnow(),
        verified_at=datetime.utcnow()
    )
    db_session.add(item)
    db_session.commit()

    # Shopper initiates removal
    updated_item = await SessionService.initiate_item_removal(db_session, cart_sess.id, item.id)
    assert updated_item.status == "REMOVING"

    # Server must block scanning while any item is REMOVING (HTTP 409 ITEM_REMOVING)
    with pytest.raises(ScanBlockedError) as exc_info:
        CartStateMachine.validate_can_scan(
            session=cart_sess,
            db=db_session,
            cart_empty_verified=True,
            cart_camera_online=True,
            has_reference=True
        )
    assert exc_info.value.reason_code == ScanBlockReason.ITEM_REMOVING


@pytest.mark.anyio
async def test_r5_cancel_removal_restores_verified_and_unblocks_scan(db_session):
    cart_sess = CartSession(
        id=str(uuid.uuid4()),
        cart_id="cart-phase3-01",
        status="ACTIVE",
        subtotal_amount=50.0,
        total_amount=50.0,
        item_count=1
    )
    db_session.add(cart_sess)
    item = CartItem(
        id=str(uuid.uuid4()),
        session_id=cart_sess.id,
        product_id="prod-phase3-a",
        quantity=1,
        unit_price=50.0,
        status="REMOVING",
        previous_status="VERIFIED",
        scanned_at=datetime.utcnow()
    )
    db_session.add(item)
    db_session.commit()

    # Shopper taps Cancel (Keep)
    restored = await SessionService.cancel_item_removal(db_session, cart_sess.id, item.id)
    assert restored.status == "VERIFIED"

    # Scanning is unblocked
    CartStateMachine.validate_can_scan(
        session=cart_sess,
        db=db_session,
        cart_empty_verified=True,
        cart_camera_online=True,
        has_reference=True
    )


def test_r5_camera_confirms_removal_drops_item_from_bill(db_session):
    cart_sess = CartSession(
        id=str(uuid.uuid4()),
        cart_id="cart-phase3-01",
        status="ACTIVE",
        subtotal_amount=50.0,
        total_amount=50.0,
        item_count=1
    )
    db_session.add(cart_sess)
    emb = [0.1] * 512
    item = CartItem(
        id=str(uuid.uuid4()),
        session_id=cart_sess.id,
        product_id="prod-phase3-a",
        quantity=1,
        unit_price=50.0,
        status="REMOVING",
        crop_embedding=json.dumps(emb)
    )
    db_session.add(item)
    db_session.commit()

    # Camera sees empty regions (item is physically gone)
    confirmed = CartStateMachine.confirm_removal(
        db=db_session,
        item=item,
        stored_items=[],
        detected_regions=[]
    )
    assert confirmed is True
    assert item.status == "REMOVED"

    # Recalculated totals drop to 0
    db_session.refresh(cart_sess)
    assert cart_sess.subtotal_amount == 0.0
    assert cart_sess.item_count == 0


# ==============================================================================
# R6: VIOLATIONS & DE-DUPLICATION TESTS
# ==============================================================================

def test_r6_violation_deduplication_and_in_place_update(db_session):
    sess_id = str(uuid.uuid4())
    cart_sess = CartSession(id=sess_id, cart_id="cart-phase3-01", status="ACTIVE")
    db_session.add(cart_sess)
    db_session.commit()

    # First violation recorded
    alert1 = CartStateMachine.record_violation(
        db=db_session,
        session_id=sess_id,
        cart_id="cart-phase3-01",
        violation_type=ViolationType.UNSCANNED_ADD,
        message="Unscanned item: Milk",
        evidence_path="/uploads/evidence/milk_01.jpg"
    )
    assert alert1 is not None
    alert_id = alert1.id

    # Second violation for same (session, type, None item) should update in-place
    alert2 = CartStateMachine.record_violation(
        db=db_session,
        session_id=sess_id,
        cart_id="cart-phase3-01",
        violation_type=ViolationType.UNSCANNED_ADD,
        message="Unscanned item: Milk Updated",
        evidence_path="/uploads/evidence/milk_02.jpg"
    )
    assert alert2.id == alert_id
    assert alert2.message == "Unscanned item: Milk Updated"
    assert alert2.evidence_path == "/uploads/evidence/milk_02.jpg"

    # Total open alerts for this session must equal exactly 1
    open_count = db_session.query(Alert).filter(
        Alert.session_id == sess_id,
        Alert.status == "OPEN"
    ).count()
    assert open_count == 1


def test_r6_violation_blocks_scan_item(db_session):
    sess_id = str(uuid.uuid4())
    cart_sess = CartSession(id=sess_id, cart_id="cart-phase3-01", status="ACTIVE")
    db_session.add(cart_sess)
    db_session.commit()

    CartStateMachine.record_violation(
        db=db_session,
        session_id=sess_id,
        cart_id="cart-phase3-01",
        violation_type=ViolationType.CART_NOT_EMPTY_AT_START,
        message="Please empty the cart"
    )

    with pytest.raises(ScanBlockedError) as exc_info:
        CartStateMachine.validate_can_scan(
            session=cart_sess,
            db=db_session,
            cart_empty_verified=True,
            cart_camera_online=True,
            has_reference=True
        )
    assert exc_info.value.reason_code == ScanBlockReason.VIOLATION_OPEN


# ==============================================================================
# R7: WHICH ITEM WAS REMOVED TESTS
# ==============================================================================

def test_r7_identify_missing_item_reports_confidence_and_candidates():
    emb_milk = [1.0] + [0.0] * 511
    emb_choco = [0.0, 1.0] + [0.0] * 510

    snap_milk = StoredItemSnapshot(
        item_id="item-milk",
        product_id="prod-phase3-a",
        product_name="Organic Milk",
        barcode="8901234001",
        crop_embedding=emb_milk,
        bounding_box=BoundingBox(0.1, 0.1, 0.2, 0.2),
        last_known_crop_path="/uploads/evidence/milk.jpg",
        verified_at=datetime.utcnow()
    )
    snap_choco = StoredItemSnapshot(
        item_id="item-choco",
        product_id="prod-phase3-b",
        product_name="Dark Chocolate",
        barcode="8901234002",
        crop_embedding=emb_choco,
        bounding_box=BoundingBox(0.5, 0.5, 0.2, 0.2),
        last_known_crop_path="/uploads/evidence/choco.jpg",
        verified_at=datetime.utcnow()
    )

    # Frame only contains Dark Chocolate (Milk is missing)
    detected_reg = DetectedRegion(
        region_id="reg_1",
        bounding_box=BoundingBox(0.5, 0.5, 0.2, 0.2),
        embedding=emb_choco,
        confidence=1.0
    )

    missing_item, missing_conf, top_cands = CartStateMachine.identify_missing_item(
        stored_items=[snap_milk, snap_choco],
        detected_regions=[detected_reg]
    )

    assert missing_item is not None
    assert missing_item.item_id == "item-milk"
    assert missing_item.product_name == "Organic Milk"
    assert missing_conf == pytest.approx(1.0, abs=0.01)
    assert len(top_cands) <= 3
    assert top_cands[0]["product_name"] == "Organic Milk"


# ==============================================================================
# R8: RESOLUTION & 60-SECOND COOLDOWN TESTS
# ==============================================================================

def test_r8_resolve_violation_requires_audit_reason(db_session):
    alert = Alert(
        id=str(uuid.uuid4()),
        cart_id="cart-phase3-01",
        session_id="sess-phase3-01",
        alert_type="UNAUTHORIZED_REMOVE",
        violation_type="UNAUTHORIZED_REMOVE",
        message="Item removed",
        status="OPEN"
    )
    db_session.add(alert)
    db_session.commit()

    with pytest.raises(ValueError, match="non-empty audit reason"):
        CartStateMachine.resolve_violation(db_session, alert, staff_user_id="staff-01", reason="")


def test_r8_resolve_violation_marks_staff_approved_and_sets_cooldown(db_session):
    sess_id = str(uuid.uuid4())
    cart_sess = CartSession(id=sess_id, cart_id="cart-phase3-01", status="ACTIVE")
    db_session.add(cart_sess)
    item = CartItem(
        id=str(uuid.uuid4()),
        session_id=sess_id,
        product_id="prod-phase3-a",
        quantity=1,
        unit_price=50.0,
        status="NEEDS_STAFF_CHECK"
    )
    db_session.add(item)
    db_session.commit()

    alert = Alert(
        id=str(uuid.uuid4()),
        cart_id="cart-phase3-01",
        session_id=sess_id,
        item_id=item.id,
        alert_type="UNAUTHORIZED_REMOVE",
        violation_type="UNAUTHORIZED_REMOVE",
        message="Item removed",
        status="OPEN"
    )
    db_session.add(alert)
    db_session.commit()

    # Staff resolves with valid reason
    resolved_alert = CartStateMachine.resolve_violation(
        db=db_session,
        alert=alert,
        staff_user_id="staff-admin-01",
        reason="Shopper placed item into their personal bag with staff permission"
    )
    assert resolved_alert.status == "RESOLVED"
    assert resolved_alert.resolved_by == "staff-admin-01"
    assert resolved_alert.resolution_notes == "Shopper placed item into their personal bag with staff permission"

    # Item is marked staff-approved and verified (who, when, why)
    db_session.refresh(item)
    assert item.status == "VERIFIED"
    assert item.staff_approved is True
    assert item.staff_approved_by == "staff-admin-01"
    assert item.staff_approved_at is not None

    # Recreating same violation within 60s cooldown must be suppressed
    suppressed = CartStateMachine.record_violation(
        db=db_session,
        session_id=sess_id,
        cart_id="cart-phase3-01",
        violation_type=ViolationType.UNAUTHORIZED_REMOVE,
        message="Item removed again",
        item_id=item.id
    )
    assert suppressed is None


# ==============================================================================
# EVIDENCE STORAGE & PRIVACY RETENTION TESTS
# ==============================================================================

def test_evidence_storage_privacy_gate_never_stores_faces():
    detector = ObjectDetector()
    dummy_img = np.zeros((480, 640, 3), dtype=np.uint8)

    with patch("app.services.storage_service.storage_service.upload_bytes", side_effect=lambda object_path, data, content_type="image/jpeg", bucket=None: f"supabase://smartcart-evidence/{object_path}"):
        # When face or hand is present, snapshot save is strictly withheld
        res_face = detector.save_evidence_snapshot(dummy_img, face_present=True)
        assert res_face is None

        res_hand = detector.save_evidence_snapshot(dummy_img, hand_present=True)
        assert res_hand is None

        # Clean product crop succeeds via smartcart-evidence bucket
        res_clean = detector.save_evidence_snapshot(dummy_img, face_present=False, hand_present=False, box=(100, 100, 300, 300))
        assert res_clean is not None
        assert res_clean.startswith("supabase://smartcart-evidence/evidence/")


def test_evidence_retention_cleanup(db_session):
    from datetime import timedelta
    now_dt = datetime.utcnow()
    old_ref = "supabase://smartcart-evidence/evidence/old_evidence.jpg"
    fresh_ref = "supabase://smartcart-evidence/evidence/fresh_evidence.jpg"

    cart = db_session.query(Cart).first()
    old_alert = Alert(
        cart_id=cart.id,
        alert_type="UNSCANNED_ITEM",
        message="old",
        severity="HIGH",
        status="RESOLVED",
        evidence_path=old_ref,
        evidence_snapshot_url=old_ref,
        created_at=now_dt - timedelta(days=20),
    )
    fresh_alert = Alert(
        cart_id=cart.id,
        alert_type="UNSCANNED_ITEM",
        message="fresh",
        severity="HIGH",
        status="OPEN",
        evidence_path=fresh_ref,
        evidence_snapshot_url=fresh_ref,
        created_at=now_dt - timedelta(days=2),
    )
    db_session.add_all([old_alert, fresh_alert])
    db_session.commit()

    deleted = []
    with patch("app.services.storage_service.storage_service.delete_object", side_effect=lambda ref: deleted.append(ref) or True):
        cleaned = cleanup_expired_evidence(db=db_session, retention_days=14)
        assert cleaned == 1
        assert old_ref in deleted
        assert fresh_ref not in deleted
        db_session.refresh(old_alert)
        db_session.refresh(fresh_alert)
        assert old_alert.evidence_path is None
        assert fresh_alert.evidence_path == fresh_ref
