"""Unit tests for Cart State Machine (Phase 1).

Tests all 10 rules R1 through R10:
- R1: Empty Start, calibration reference, camera offline, staff override
- R2: One pending at a time, cancel pending, 60s reminder
- R3: Placement evaluation (VERIFIED, REPOSITION, WRONG_ITEM, REVIEW, face withheld), snapshots
- R4: Multi-object matching, 1-to-1 assignments, count invariant, hand tracking, motion escalation, overlap, ambiguity
- R5: Removal flow (pending direct delete, verified entering REMOVING, camera confirmation, cancel/keep)
- R6: Violations (UNSCANNED_ADD, UNAUTHORIZED_REMOVE, CART_NOT_EMPTY), de-duplication, scan blocking
- R7: Which item was removed identification against stored state
- R8: Resolving violations, staff approval metadata, 60s cooldown
- R9: Checkout enforcement (zero pending, zero removing, zero violations, count match)
- R10: Separate physical items per barcode scan (quantity=1 with independent snapshots)
"""

import json
import uuid
from datetime import datetime, timedelta
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.cart import Cart
from app.models.product import Product
from app.models.session import CartItem, CartSession
from app.models.alert import Alert
from app.services.cart_state_machine import (
    BoundingBox,
    CartStateMachine,
    DecisionOutcome,
    DetectedRegion,
    FullMatchResult,
    ScanBlockedError,
    ScanBlockReason,
    StoredItemSnapshot,
    ViolationType,
)


@pytest.fixture
def db_session():
    """In-memory SQLite database for state machine unit testing."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(bind=engine)
    session = TestingSession()

    # Seed basic cart and products
    cart = Cart(
        id="cart-test-01",
        cart_number="CART-01",
        qr_code_token="QR-TEST-01",
        camera_status="ONLINE",
        is_enabled=True,
        status="IDLE",
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
        id="prod-biscuit-uuid",
        name="Parle-G 100g",
        brand="Parle",
        category="Snacks",
        barcode="8901719101012",
        price=10.0,
        stock_quantity=100,
    )
    session.add_all([cart, product_a, product_b])
    session.commit()

    yield session
    session.close()


# ==============================================================================
# R1: EMPTY START TESTS
# ==============================================================================


def test_r1_empty_start_camera_offline():
    is_empty, msg, reason = CartStateMachine.evaluate_empty_start(
        camera_online=False,
        has_reference=True,
        diff_from_ref=0.01,
        stable_seconds=3.0,
        hand_present=False,
        face_present=False,
        detected_objects_count=0,
    )
    assert not is_empty
    assert reason == ScanBlockReason.CAMERA_OFFLINE
    assert "offline" in msg.lower()


def test_r1_empty_start_no_reference():
    is_empty, msg, reason = CartStateMachine.evaluate_empty_start(
        camera_online=True,
        has_reference=False,
        diff_from_ref=0.01,
        stable_seconds=3.0,
        hand_present=False,
        face_present=False,
        detected_objects_count=0,
    )
    assert not is_empty
    assert reason == ScanBlockReason.NO_REFERENCE
    assert "reference missing" in msg.lower()


def test_r1_empty_start_not_empty_blocks_scan():
    # Objects detected inside cart
    is_empty, msg, reason = CartStateMachine.evaluate_empty_start(
        camera_online=True,
        has_reference=True,
        diff_from_ref=0.01,
        stable_seconds=3.0,
        hand_present=False,
        face_present=False,
        detected_objects_count=1,
    )
    assert not is_empty
    assert reason == ScanBlockReason.CART_NOT_EMPTY
    assert "empty the cart" in msg.lower()

    # High difference from empty reference
    is_empty2, _, reason2 = CartStateMachine.evaluate_empty_start(
        camera_online=True,
        has_reference=True,
        diff_from_ref=0.15,
        stable_seconds=3.0,
        hand_present=False,
        face_present=False,
        detected_objects_count=0,
    )
    assert not is_empty2
    assert reason2 == ScanBlockReason.CART_NOT_EMPTY


def test_r1_empty_start_hand_or_face_present():
    is_empty, msg, reason = CartStateMachine.evaluate_empty_start(
        camera_online=True,
        has_reference=True,
        diff_from_ref=0.01,
        stable_seconds=3.0,
        hand_present=True,
        face_present=False,
        detected_objects_count=0,
    )
    assert not is_empty
    assert reason == ScanBlockReason.CART_NOT_EMPTY
    assert "hand or person" in msg.lower()


def test_r1_empty_start_stabilization_period():
    # Only 1.0s stable, needs >= 2.0s
    is_empty, msg, reason = CartStateMachine.evaluate_empty_start(
        camera_online=True,
        has_reference=True,
        diff_from_ref=0.01,
        stable_seconds=1.0,
        hand_present=False,
        face_present=False,
        detected_objects_count=0,
    )
    assert not is_empty
    assert reason == ScanBlockReason.CART_NOT_EMPTY
    assert "stabilize" in msg.lower()


def test_r1_empty_start_success():
    is_empty, msg, reason = CartStateMachine.evaluate_empty_start(
        camera_online=True,
        has_reference=True,
        diff_from_ref=0.02,
        stable_seconds=2.5,
        hand_present=False,
        face_present=False,
        detected_objects_count=0,
    )
    assert is_empty
    assert reason is None
    assert "verified empty" in msg.lower()


def test_r1_empty_start_staff_override():
    # Override without reason rejected
    is_empty, _, _ = CartStateMachine.evaluate_empty_start(
        camera_online=True,
        has_reference=True,
        diff_from_ref=0.2,
        stable_seconds=2.5,
        hand_present=False,
        face_present=False,
        detected_objects_count=1,
        staff_override=True,
        staff_reason="",
    )
    assert not is_empty

    # Override with documented reason accepted (e.g., shopper personal bag)
    is_empty_ok, msg_ok, reason_ok = CartStateMachine.evaluate_empty_start(
        camera_online=True,
        has_reference=True,
        diff_from_ref=0.2,
        stable_seconds=2.5,
        hand_present=False,
        face_present=False,
        detected_objects_count=1,
        staff_override=True,
        staff_reason="Shopper personal tote bag inspected by staff member EMP-12",
    )
    assert is_empty_ok
    assert reason_ok is None
    assert "staff override approved" in msg_ok.lower()


# ==============================================================================
# R2: ONE PENDING AT A TIME TESTS
# ==============================================================================


def test_r2_one_pending_at_a_time(db_session):
    cart_sess = CartSession(
        id=str(uuid.uuid4()),
        cart_id="cart-test-01",
        status="ACTIVE",
        cart_empty_verified=True,
    )
    db_session.add(cart_sess)
    db_session.commit()

    # Initial scan passes
    CartStateMachine.validate_can_scan(cart_sess, db_session)

    # First item becomes PENDING
    item1 = CartItem(
        session_id=cart_sess.id,
        product_id="prod-milk-uuid",
        quantity=1,
        unit_price=32.0,
        status="PENDING",
        scanned_at=datetime.utcnow(),
    )
    db_session.add(item1)
    db_session.commit()

    # Second scan while first is PENDING MUST FAIL with ITEM_PENDING (HTTP 409)
    with pytest.raises(ScanBlockedError) as exc_info:
        CartStateMachine.validate_can_scan(cart_sess, db_session)
    assert exc_info.value.reason_code == ScanBlockReason.ITEM_PENDING
    assert "Place the scanned item first" in exc_info.value.message


def test_r2_cancel_pending_item_direct_delete(db_session):
    cart_sess = CartSession(
        id=str(uuid.uuid4()),
        cart_id="cart-test-01",
        status="ACTIVE",
        cart_empty_verified=True,
    )
    db_session.add(cart_sess)
    item = CartItem(
        id="pending-item-uuid",
        session_id=cart_sess.id,
        product_id="prod-milk-uuid",
        quantity=1,
        unit_price=32.0,
        status="PENDING",
        scanned_at=datetime.utcnow(),
    )
    db_session.add(item)
    db_session.commit()

    # Shopper cancels pending item -> deleted directly, no camera check
    success = CartStateMachine.cancel_pending_item(db_session, cart_sess.id, "pending-item-uuid")
    assert success
    persisted = db_session.query(CartItem).filter(CartItem.id == "pending-item-uuid").first()
    assert persisted is None


def test_r2_pending_reminder_60s():
    item_fresh = CartItem(
        status="PENDING",
        scanned_at=datetime.utcnow() - timedelta(seconds=30),
    )
    assert not CartStateMachine.check_pending_reminder(item_fresh)

    item_stale = CartItem(
        status="PENDING",
        scanned_at=datetime.utcnow() - timedelta(seconds=65),
    )
    assert CartStateMachine.check_pending_reminder(item_stale)


# ==============================================================================
# R3: PLACEMENT CHECK & CART STATE SNAPSHOT TESTS
# ==============================================================================


def test_r3_placement_check_verified():
    outcome, reason, margin = CartStateMachine.evaluate_placement(
        scanned_product_score=0.92,
        runner_up_score=0.45,
    )
    assert outcome == DecisionOutcome.VERIFIED
    assert margin > 0.08
    assert "Verified" in reason


def test_r3_placement_check_wrong_item():
    outcome, reason, _ = CartStateMachine.evaluate_placement(
        scanned_product_score=0.42,
        runner_up_score=0.91,
        runner_up_product_name="Parle-G 100g",
    )
    assert outcome == DecisionOutcome.WRONG_ITEM
    assert "Wrong item" in reason


def test_r3_placement_check_reposition():
    outcome, reason, _ = CartStateMachine.evaluate_placement(
        scanned_product_score=0.74,
        runner_up_score=0.30,
    )
    assert outcome == DecisionOutcome.REPOSITION
    assert "Reposition" in reason


def test_r3_placement_check_review():
    outcome, reason, _ = CartStateMachine.evaluate_placement(
        scanned_product_score=0.55,
        runner_up_score=0.50,
    )
    assert outcome == DecisionOutcome.REVIEW
    assert "Review required" in reason


def test_r3_placement_check_face_detected_withheld():
    # Privacy rule: never judge or verify with face in frame crop
    outcome, reason, _ = CartStateMachine.evaluate_placement(
        scanned_product_score=0.99,
        runner_up_score=0.10,
        face_detected=True,
    )
    assert outcome == DecisionOutcome.REVIEW
    assert "face detected" in reason.lower()


def test_r3_cart_state_snapshot(db_session):
    cart_sess = CartSession(id=str(uuid.uuid4()), cart_id="cart-test-01", status="ACTIVE")
    db_session.add(cart_sess)
    item = CartItem(
        id=str(uuid.uuid4()),
        session_id=cart_sess.id,
        product_id="prod-milk-uuid",
        quantity=1,
        unit_price=32.0,
        status="PENDING",
    )
    db_session.add(item)
    db_session.commit()

    box = BoundingBox(x=0.15, y=0.25, width=0.30, height=0.40)
    embedding = [0.12] * 512
    crop_path = "/uploads/evidence/crop_milk_01.jpg"

    snapshot = CartStateMachine.create_item_snapshot(
        item=item,
        crop_embedding=embedding,
        box=box,
        crop_path=crop_path,
    )

    assert item.status == "VERIFIED"
    assert item.crop_embedding == json.dumps(embedding)
    assert json.loads(item.bounding_box) == {"x": 0.15, "y": 0.25, "width": 0.30, "height": 0.40}
    assert item.last_known_crop_path == crop_path
    assert snapshot.item_id == item.id


# ==============================================================================
# R4: MULTI-OBJECT MATCHING & MOVEMENT INVARIANTS TESTS
# ==============================================================================


def test_r4_movement_position_update_silently():
    # Item moved to new location in cart -> embeddings match -> silently paired
    emb_milk = [0.2] * 128
    stored_item = StoredItemSnapshot(
        item_id="item-milk-1",
        product_id="prod-milk-uuid",
        product_name="Amul Milk 500ml",
        barcode="8901262010053",
        crop_embedding=emb_milk,
        bounding_box=BoundingBox(0.1, 0.1, 0.2, 0.2),
        last_known_crop_path=None,
        verified_at=datetime.utcnow().isoformat(),
    )

    detected_reg = DetectedRegion(
        region_id="reg-new-pos",
        bounding_box=BoundingBox(0.7, 0.8, 0.2, 0.2),  # Shifted position
        embedding=emb_milk,  # Identical embedding
        confidence=0.95,
    )

    res: FullMatchResult = CartStateMachine.run_full_match(
        stored_items=[stored_item],
        detected_regions=[detected_reg],
    )
    assert len(res.matched_pairs) == 1
    assert len(res.unmatched_items) == 0
    assert len(res.unmatched_objects) == 0
    assert res.count_matches
    assert not res.requires_staff_check


def test_r4_count_check_mismatch():
    stored_item = StoredItemSnapshot(
        item_id="item-milk-1",
        product_id="prod-milk-uuid",
        product_name="Amul Milk 500ml",
        barcode="8901262010053",
        crop_embedding=[0.2] * 128,
        bounding_box=BoundingBox(0.1, 0.1, 0.2, 0.2),
        last_known_crop_path=None,
        verified_at=datetime.utcnow().isoformat(),
    )

    # Camera sees 2 objects, but only 1 verified item on bill
    detected1 = DetectedRegion("r1", BoundingBox(0.1, 0.1, 0.2, 0.2), [0.2] * 128, 0.95)
    detected2 = DetectedRegion("r2", BoundingBox(0.5, 0.5, 0.2, 0.2), [0.8] * 128, 0.90)

    res = CartStateMachine.run_full_match(
        stored_items=[stored_item],
        detected_regions=[detected1, detected2],
        has_pending_item=False,
    )
    assert not res.count_matches
    assert len(res.unmatched_objects) == 1


def test_r4_hand_tracking_activity_logged():
    res = CartStateMachine.run_full_match(
        stored_items=[],
        detected_regions=[],
        hand_activity_occurred=True,
    )
    assert res.hand_activity_logged


def test_r4_long_motion_escalation_after_60s():
    res = CartStateMachine.run_full_match(
        stored_items=[],
        detected_regions=[],
        unstable_motion_seconds=65.0,
    )
    assert res.requires_staff_check
    assert "motion unstable" in res.staff_reason.lower()


def test_r4_overlap_occlusion_staff_check():
    # Two boxes heavily overlapping (IoU > 0.45)
    r1 = DetectedRegion("r1", BoundingBox(0.2, 0.2, 0.4, 0.4), [0.1] * 128, 0.9)
    r2 = DetectedRegion("r2", BoundingBox(0.25, 0.25, 0.4, 0.4), [0.2] * 128, 0.9)

    res = CartStateMachine.run_full_match(
        stored_items=[],
        detected_regions=[r1, r2],
    )
    assert res.requires_staff_check
    assert "overlap" in res.staff_reason.lower()


def test_r4_ambiguous_matches_go_to_staff():
    # Two stored items with nearly identical similarity to one detected region
    item_a = StoredItemSnapshot(
        item_id="i1",
        product_id="p1",
        product_name="Product A",
        barcode="111",
        crop_embedding=[0.3, 0.3, 0.3],
        bounding_box=BoundingBox(0.1, 0.1, 0.2, 0.2),
        last_known_crop_path=None,
        verified_at="",
    )
    item_b = StoredItemSnapshot(
        item_id="i2",
        product_id="p2",
        product_name="Product B",
        barcode="222",
        crop_embedding=[0.31, 0.3, 0.3],
        bounding_box=BoundingBox(0.5, 0.5, 0.2, 0.2),
        last_known_crop_path=None,
        verified_at="",
    )
    reg = DetectedRegion("r1", BoundingBox(0.2, 0.2, 0.2, 0.2), [0.3, 0.3, 0.3], 0.9)

    res = CartStateMachine.run_full_match(
        stored_items=[item_a, item_b],
        detected_regions=[reg],
    )
    assert res.requires_staff_check
    assert "Ambiguous match" in res.staff_reason


# ==============================================================================
# R5: REMOVAL FLOW TESTS
# ==============================================================================


def test_r5_removal_pending_item_deleted_directly(db_session):
    cart_sess = CartSession(id=str(uuid.uuid4()), cart_id="cart-test-01", status="ACTIVE")
    db_session.add(cart_sess)
    item = CartItem(
        id="pending-del-item",
        session_id=cart_sess.id,
        product_id="prod-milk-uuid",
        quantity=1,
        unit_price=32.0,
        status="PENDING",
    )
    db_session.add(item)
    db_session.commit()

    res_item, was_deleted = CartStateMachine.initiate_removal(db_session, cart_sess, "pending-del-item")
    assert was_deleted
    assert res_item is None
    assert db_session.query(CartItem).filter(CartItem.id == "pending-del-item").first() is None


def test_r5_removal_verified_item_sets_removing_and_blocks_scan(db_session):
    cart_sess = CartSession(
        id=str(uuid.uuid4()),
        cart_id="cart-test-01",
        status="ACTIVE",
        cart_empty_verified=True,
    )
    db_session.add(cart_sess)
    item = CartItem(
        id="verified-remove-item",
        session_id=cart_sess.id,
        product_id="prod-milk-uuid",
        quantity=1,
        unit_price=32.0,
        status="VERIFIED",
    )
    db_session.add(item)
    db_session.commit()

    res_item, was_deleted = CartStateMachine.initiate_removal(db_session, cart_sess, "verified-remove-item")
    assert not was_deleted
    assert res_item.status == "REMOVING"

    # Server MUST block scan-item while item is in REMOVING state
    with pytest.raises(ScanBlockedError) as exc_info:
        CartStateMachine.validate_can_scan(cart_sess, db_session)
    assert exc_info.value.reason_code == ScanBlockReason.ITEM_REMOVING
    assert "finish removing" in exc_info.value.message


def test_r5_confirm_removal_confirmed(db_session):
    cart_sess = CartSession(id=str(uuid.uuid4()), cart_id="cart-test-01", status="ACTIVE")
    db_session.add(cart_sess)
    item = CartItem(
        id="rem-conf-item",
        session_id=cart_sess.id,
        product_id="prod-milk-uuid",
        quantity=1,
        unit_price=32.0,
        status="REMOVING",
        crop_embedding=json.dumps([0.5, 0.5]),
    )
    db_session.add(item)
    db_session.commit()

    # Camera frame contains no matching item
    detected_other = [DetectedRegion("r1", BoundingBox(0, 0, 0, 0), [-0.5, -0.5], 0.9)]
    confirmed = CartStateMachine.confirm_removal(db_session, item, [], detected_other)
    assert confirmed
    assert item.status == "REMOVED"


def test_r5_cancel_removal_restores_verified(db_session):
    cart_sess = CartSession(id=str(uuid.uuid4()), cart_id="cart-test-01", status="ACTIVE")
    db_session.add(cart_sess)
    item = CartItem(
        id="cancel-rem-item",
        session_id=cart_sess.id,
        product_id="prod-milk-uuid",
        quantity=1,
        unit_price=32.0,
        status="REMOVING",
        previous_status="VERIFIED",
    )
    db_session.add(item)
    db_session.commit()

    restored = CartStateMachine.cancel_removal(db_session, item)
    assert restored.status == "VERIFIED"


# ==============================================================================
# R6: VIOLATIONS & DE-DUPLICATION TESTS
# ==============================================================================


def test_r6_violation_blocks_scan(db_session):
    cart_sess = CartSession(
        id=str(uuid.uuid4()),
        cart_id="cart-test-01",
        status="ACTIVE",
        cart_empty_verified=True,
    )
    db_session.add(cart_sess)
    alert = Alert(
        cart_id="cart-test-01",
        session_id=cart_sess.id,
        alert_type="UNSCANNED_ADD",
        violation_type="UNSCANNED_ADD",
        message="Unscanned item added to cart.",
        status="OPEN",
    )
    db_session.add(alert)
    db_session.commit()

    with pytest.raises(ScanBlockedError) as exc_info:
        CartStateMachine.validate_can_scan(cart_sess, db_session)
    assert exc_info.value.reason_code == ScanBlockReason.VIOLATION_OPEN


def test_r6_violation_deduplication(db_session):
    cart_sess = CartSession(id=str(uuid.uuid4()), cart_id="cart-test-01", status="ACTIVE")
    db_session.add(cart_sess)
    db_session.commit()

    # First violation recorded
    a1 = CartStateMachine.record_violation(
        db=db_session,
        session_id=cart_sess.id,
        cart_id="cart-test-01",
        violation_type=ViolationType.UNSCANNED_ADD,
        message="First event",
        evidence_path="/uploads/ev1.jpg",
        item_id=None,
    )

    # Second violation of same type on same session MUST update existing in place
    a2 = CartStateMachine.record_violation(
        db=db_session,
        session_id=cart_sess.id,
        cart_id="cart-test-01",
        violation_type=ViolationType.UNSCANNED_ADD,
        message="Second event updated",
        evidence_path="/uploads/ev2.jpg",
        item_id=None,
    )

    assert a1.id == a2.id
    total_open = db_session.query(Alert).filter(Alert.session_id == cart_sess.id, Alert.status == "OPEN").count()
    assert total_open == 1
    assert a2.message == "Second event updated"
    assert a2.evidence_path == "/uploads/ev2.jpg"


# ==============================================================================
# R7: WHICH ITEM WAS REMOVED TESTS
# ==============================================================================


def test_r7_identify_missing_item():
    item_milk = StoredItemSnapshot(
        item_id="item-milk",
        product_id="prod-milk-uuid",
        product_name="Amul Milk 500ml",
        barcode="8901262010053",
        crop_embedding=[1.0, 0.0, 0.0],
        bounding_box=BoundingBox(0.1, 0.1, 0.2, 0.2),
        last_known_crop_path="/uploads/milk.jpg",
        verified_at="",
    )
    item_biscuit = StoredItemSnapshot(
        item_id="item-biscuit",
        product_id="prod-biscuit-uuid",
        product_name="Parle-G 100g",
        barcode="8901719101012",
        crop_embedding=[0.0, 1.0, 0.0],
        bounding_box=BoundingBox(0.5, 0.5, 0.2, 0.2),
        last_known_crop_path="/uploads/biscuit.jpg",
        verified_at="",
    )

    # In current frame, only biscuit is detected; milk is missing
    detected_biscuit = DetectedRegion("r1", BoundingBox(0.5, 0.5, 0.2, 0.2), [0.0, 1.0, 0.0], 0.95)

    missing, confidence, candidates = CartStateMachine.identify_missing_item(
        stored_items=[item_milk, item_biscuit],
        detected_regions=[detected_biscuit],
    )

    assert missing is not None
    assert missing.item_id == "item-milk"
    assert missing.product_name == "Amul Milk 500ml"
    assert confidence > 0.9
    assert len(candidates) >= 1


# ==============================================================================
# R8: RESOLVING A VIOLATION TESTS
# ==============================================================================


def test_r8_resolve_violation_requires_reason(db_session):
    alert = Alert(
        cart_id="cart-test-01",
        session_id="sess-01",
        alert_type="UNSCANNED_ADD",
        violation_type="UNSCANNED_ADD",
        message="Unscanned add",
        status="OPEN",
    )
    db_session.add(alert)
    db_session.commit()

    with pytest.raises(ValueError):
        CartStateMachine.resolve_violation(db_session, alert, staff_user_id="staff-1", reason="")


def test_r8_resolve_violation_marks_staff_approved_and_verified(db_session):
    cart_sess = CartSession(id=str(uuid.uuid4()), cart_id="cart-test-01", status="ACTIVE")
    db_session.add(cart_sess)
    item = CartItem(
        id=str(uuid.uuid4()),
        session_id=cart_sess.id,
        product_id="prod-milk-uuid",
        quantity=1,
        unit_price=32.0,
        status="NEEDS_STAFF_CHECK",
    )
    db_session.add(item)
    db_session.commit()

    alert = Alert(
        cart_id="cart-test-01",
        session_id=cart_sess.id,
        item_id=item.id,
        alert_type="NEEDS_STAFF_CHECK",
        violation_type="NEEDS_STAFF_CHECK",
        message="Staff check needed",
        status="OPEN",
    )
    db_session.add(alert)
    db_session.commit()

    CartStateMachine.resolve_violation(
        db_session,
        alert,
        staff_user_id="staff-uuid-007",
        reason="Visual packaging inspection passed by supervisor",
    )

    assert alert.status == "RESOLVED"
    assert alert.resolved_by == "staff-uuid-007"
    assert alert.resolution_notes == "Visual packaging inspection passed by supervisor"
    assert alert.resolved_at is not None

    # Cart item MUST transition to VERIFIED with staff approved flags
    assert item.status == "VERIFIED"
    assert item.staff_approved is True
    assert item.staff_approved_by == "staff-uuid-007"
    assert item.staff_approved_at is not None


def test_r8_resolve_violation_cooldown_60s():
    resolved_time = datetime.utcnow() - timedelta(seconds=25)
    # Inside 60s cooldown: cannot recreate violation
    assert not CartStateMachine.can_recreate_violation(resolved_time)

    resolved_time_old = datetime.utcnow() - timedelta(seconds=65)
    # After 60s cooldown: can recreate violation if fresh infraction occurs
    assert CartStateMachine.can_recreate_violation(resolved_time_old)


# ==============================================================================
# R9: CHECKOUT ENFORCEMENT TESTS
# ==============================================================================


def test_r9_checkout_blocked_when_pending(db_session):
    cart_sess = CartSession(id=str(uuid.uuid4()), cart_id="cart-test-01", status="ACTIVE")
    db_session.add(cart_sess)
    item = CartItem(
        session_id=cart_sess.id,
        product_id="prod-milk-uuid",
        quantity=1,
        unit_price=32.0,
        status="PENDING",
    )
    db_session.add(item)
    db_session.commit()

    can_checkout, msg, reason = CartStateMachine.validate_can_checkout(
        session=cart_sess,
        db=db_session,
        detected_objects_count=1,
    )
    assert not can_checkout
    assert reason == ScanBlockReason.ITEM_PENDING
    assert "pending placement" in msg.lower()


def test_r9_checkout_blocked_when_count_mismatch(db_session):
    cart_sess = CartSession(id=str(uuid.uuid4()), cart_id="cart-test-01", status="ACTIVE")
    db_session.add(cart_sess)
    item = CartItem(
        session_id=cart_sess.id,
        product_id="prod-milk-uuid",
        quantity=1,
        unit_price=32.0,
        status="VERIFIED",
    )
    db_session.add(item)
    db_session.commit()

    # Camera sees 2 objects but bill has only 1 verified item
    can_checkout, msg, _ = CartStateMachine.validate_can_checkout(
        session=cart_sess,
        db=db_session,
        detected_objects_count=2,
    )
    assert not can_checkout
    assert "camera sees 2 objects but bill has 1" in msg.lower()


def test_r9_checkout_allowed_when_clean(db_session):
    cart_sess = CartSession(id=str(uuid.uuid4()), cart_id="cart-test-01", status="ACTIVE")
    db_session.add(cart_sess)
    item = CartItem(
        session_id=cart_sess.id,
        product_id="prod-milk-uuid",
        quantity=1,
        unit_price=32.0,
        status="VERIFIED",
    )
    db_session.add(item)
    db_session.commit()

    can_checkout, msg, reason = CartStateMachine.validate_can_checkout(
        session=cart_sess,
        db=db_session,
        detected_objects_count=1,
    )
    assert can_checkout
    assert reason is None
    assert "authorized" in msg.lower()


# ==============================================================================
# R10: QUANTITY (SEPARATE ITEMS PER PRODUCT SCAN) TESTS
# ==============================================================================


def test_r10_quantity_creates_separate_items_with_own_snapshots(db_session):
    cart_sess = CartSession(id=str(uuid.uuid4()), cart_id="cart-test-01", status="ACTIVE")
    db_session.add(cart_sess)
    prod = db_session.query(Product).filter(Product.barcode == "8901262010053").first()

    # First scan of product
    item1 = CartStateMachine.create_scanned_item(db_session, cart_sess, prod)
    # Second scan of identical product
    item2 = CartStateMachine.create_scanned_item(db_session, cart_sess, prod)

    # Must be two distinct rows, each with quantity 1
    assert item1.id != item2.id
    assert item1.quantity == 1
    assert item2.quantity == 1
    assert item1.status == "PENDING"
    assert item2.status == "PENDING"

    # Each gets independent crop snapshot
    CartStateMachine.create_item_snapshot(
        item1,
        crop_embedding=[0.1] * 128,
        box=BoundingBox(0.1, 0.1, 0.2, 0.2),
        crop_path="/uploads/milk_unit1.jpg",
    )
    CartStateMachine.create_item_snapshot(
        item2,
        crop_embedding=[0.2] * 128,
        box=BoundingBox(0.4, 0.4, 0.2, 0.2),
        crop_path="/uploads/milk_unit2.jpg",
    )

    db_session.commit()

    db_session.refresh(item1)
    db_session.refresh(item2)
    assert item1.last_known_crop_path == "/uploads/milk_unit1.jpg"
    assert item2.last_known_crop_path == "/uploads/milk_unit2.jpg"
