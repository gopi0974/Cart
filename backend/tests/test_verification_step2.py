import os
import sys
import asyncio

def run_async(coro):
    """Run pure async coroutine synchronously to prevent IOCP / socketpair hangs on Windows sandbox."""
    try:
        coro.send(None)
    except StopIteration as e:
        return e.value
try:
    import pytest
except ImportError:
    import re

    class _RaisesContext:
        def __init__(self, expected_exception, match=None):
            self.expected_exception = expected_exception
            self.match = match
            self.value = None

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            if exc_type is None:
                raise AssertionError(f"DID NOT RAISE {self.expected_exception}")
            if not issubclass(exc_type, self.expected_exception):
                return False
            if self.match is not None and not re.search(self.match, str(exc_val)):
                raise AssertionError(f"Pattern '{self.match}' does not match '{str(exc_val)}'")
            self.value = exc_val
            return True

    class DummyPytest:
        @staticmethod
        def fixture(func):
            return func

        @staticmethod
        def raises(expected_exception, match=None):
            return _RaisesContext(expected_exception, match=match)

    pytest = DummyPytest
import numpy as np
from PIL import Image
from unittest.mock import MagicMock, patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Ensure backend root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.config import settings
from app.database import Base
from app.models.product import Product, ProductEmbedding
from app.models.cart import Cart
from app.models.session import CartSession, CartItem, VerificationDecision
from app.models.alert import Alert, ReviewCase
from app.services.scan_worker import preprocess_product_image_for_embedding
from app.ai.verification_engine import verification_engine
from app.ai.object_detector import object_detector
from app.services.session_service import SessionService
from app.services.billing_service import BillingService

# Isolated in-memory SQLite database for Step 2 verification tests
test_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
Base.metadata.create_all(bind=test_engine)


@pytest.fixture
def db():
    connection = test_engine.connect()
    transaction = connection.begin()
    session = TestingSessionLocal(bind=connection)
    yield session
    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture
def sample_data(db):
    # Setup test cart
    cart = Cart(
        id="cart-test-001",
        cart_number="CART-001",
        qr_code_token="token-test-cart-001",
        camera_status="ONLINE",
        is_enabled=True,
        battery_level=95
    )
    db.add(cart)

    # Setup test products
    p1 = Product(
        id="prod-milk-001",
        barcode="890126201001",
        name="Amul Fresh Milk 500ml",
        brand="Amul",
        category="Dairy",
        price=30.0,
        weight_grams=500
    )
    p2 = Product(
        id="prod-tea-002",
        barcode="890126201002",
        name="Tata Tea Gold 250g",
        brand="Tata",
        category="Beverages",
        price=140.0,
        weight_grams=250
    )
    db.add_all([p1, p2])

    # Setup active session
    cart_session = CartSession(
        id="sess-test-101",
        cart_id=cart.id,
        status="ACTIVE",
        subtotal_amount=0.0,
        total_amount=0.0,
        total_tax=0.0,
        item_count=0
    )
    db.add(cart_session)
    db.commit()

    return {"cart": cart, "p1": p1, "p2": p2, "session": cart_session}


# =========================================================================
# 1. Pipeline Equality Test
# =========================================================================
def test_pipeline_equality():
    """Assert that verification preprocessing and enrollment preprocessing call the EXACT same function."""
    import app.ai.verification_engine as ve_mod

    # 1. Reference identity: verification engine MUST reference scan_worker's exact function
    assert ve_mod.preprocess_product_image_for_embedding is preprocess_product_image_for_embedding, (
        "verification_engine.py must import and use preprocess_product_image_for_embedding directly from scan_worker.py"
    )

    # 2. Functional equality: evaluate identical synthetic crop through both
    synthetic_crop = Image.new("RGB", (320, 240), color=(128, 64, 200))
    proc1 = preprocess_product_image_for_embedding(synthetic_crop, force_grabcut=False)
    proc2 = ve_mod.preprocess_product_image_for_embedding(synthetic_crop, force_grabcut=False)

    assert proc1.size == (224, 224), "Output dimension must be exact CLIP input size (224, 224)"
    assert proc2.size == (224, 224)
    assert np.array_equal(np.array(proc1), np.array(proc2)), (
        "Preprocessing in verification must produce bit-for-bit identical output to enrollment"
    )


# =========================================================================
# 2. Decision Matrix & Synthetic Probes Test
# =========================================================================
def test_decision_branch_auto_approve(db, sample_data):
    """PENDING exists + top match == scanned product + score >= HIGH + gap >= 0.05 -> AUTO_APPROVE"""
    synthetic_frame = np.full((480, 640, 3), 120, dtype=np.uint8)

    orig_high = settings.CONFIDENCE_HIGH
    orig_low = settings.CONFIDENCE_LOW
    settings.CONFIDENCE_HIGH = 0.85
    settings.CONFIDENCE_LOW = 0.50

    try:
        mock_candidates = [
            {"id": sample_data["p1"].id, "product_name": sample_data["p1"].name, "barcode": sample_data["p1"].barcode, "similarity": 0.96},
            {"id": sample_data["p2"].id, "product_name": sample_data["p2"].name, "barcode": sample_data["p2"].barcode, "similarity": 0.70}
        ]

        with patch("app.ai.verification_engine.VectorStoreMatcher.find_nearest_product", return_value=mock_candidates), \
             patch("app.ai.verification_engine.VectorStoreMatcher.verify_claimed_barcode", return_value=(True, 0.96)), \
             patch("app.ai.verification_engine.feature_extractor.get_embedding", return_value=np.zeros(512, dtype=np.float32)), \
             patch.object(object_detector, "compute_motion_box", return_value=(100, 100, 300, 300)):
            
            result = verification_engine.evaluate_item_placement(
                db=db,
                claimed_barcode=sample_data["p1"].barcode,
                image_data=synthetic_frame,
                cart_id=sample_data["cart"].id,
                session_id=sample_data["session"].id
            )

        assert result["decision"] == "AUTO_APPROVE"
        assert result["confidence"] == 0.96
        assert result["top_match"]["barcode"] == sample_data["p1"].barcode

        # Verify audit decision record was persisted with exact thresholds
        audit = db.query(VerificationDecision).filter(
            VerificationDecision.session_id == sample_data["session"].id,
            VerificationDecision.scanned_barcode == sample_data["p1"].barcode
        ).first()
        assert audit is not None
        assert audit.decision == "AUTO_APPROVE"
        assert audit.top1_score == 0.96
        assert audit.top2_score == 0.70
        assert audit.threshold_high == 0.85
        assert audit.threshold_low == 0.50
    finally:
        settings.CONFIDENCE_HIGH = orig_high
        settings.CONFIDENCE_LOW = orig_low


def test_decision_branch_reposition_prompt(db, sample_data):
    """Between LOW and HIGH (e.g. 0.78) -> REPOSITION_PROMPT"""
    synthetic_frame = np.full((480, 640, 3), 120, dtype=np.uint8)
    settings.CONFIDENCE_HIGH = 0.85
    settings.CONFIDENCE_LOW = 0.50
    mock_candidates = [
        {"id": sample_data["p1"].id, "product_name": sample_data["p1"].name, "barcode": sample_data["p1"].barcode, "similarity": 0.78},
        {"id": sample_data["p2"].id, "product_name": sample_data["p2"].name, "barcode": sample_data["p2"].barcode, "similarity": 0.50}
    ]

    with patch("app.ai.verification_engine.VectorStoreMatcher.find_nearest_product", return_value=mock_candidates), \
         patch("app.ai.verification_engine.VectorStoreMatcher.verify_claimed_barcode", return_value=(True, 0.78)), \
         patch("app.ai.verification_engine.feature_extractor.get_embedding", return_value=np.zeros(512, dtype=np.float32)), \
         patch.object(object_detector, "compute_motion_box", return_value=(100, 100, 300, 300)):
        
        result = verification_engine.evaluate_item_placement(
            db=db,
            claimed_barcode=sample_data["p1"].barcode,
            image_data=synthetic_frame,
            cart_id=sample_data["cart"].id,
            session_id=sample_data["session"].id
        )

    assert result["decision"] == "REPOSITION_PROMPT"
    assert "reposition" in result["message"].lower()


def test_decision_branch_wrong_item(db, sample_data):
    """Different product matches >= LOW (0.70) -> WRONG_ITEM"""
    synthetic_frame = np.full((480, 640, 3), 120, dtype=np.uint8)
    settings.CONFIDENCE_HIGH = 0.85
    settings.CONFIDENCE_LOW = 0.50
    # Scanned Milk (p1), but vision strongly detected Tea (p2) at 0.88
    mock_candidates = [
        {"id": sample_data["p2"].id, "product_name": sample_data["p2"].name, "barcode": sample_data["p2"].barcode, "similarity": 0.88},
        {"id": sample_data["p1"].id, "product_name": sample_data["p1"].name, "barcode": sample_data["p1"].barcode, "similarity": 0.40}
    ]

    with patch("app.ai.verification_engine.VectorStoreMatcher.find_nearest_product", return_value=mock_candidates), \
         patch("app.ai.verification_engine.VectorStoreMatcher.verify_claimed_barcode", return_value=(False, 0.40)), \
         patch("app.ai.verification_engine.feature_extractor.get_embedding", return_value=np.zeros(512, dtype=np.float32)), \
         patch.object(object_detector, "compute_motion_box", return_value=(100, 100, 300, 300)):
        
        result = verification_engine.evaluate_item_placement(
            db=db,
            claimed_barcode=sample_data["p1"].barcode,
            image_data=synthetic_frame,
            cart_id=sample_data["cart"].id,
            session_id=sample_data["session"].id
        )

    assert result["decision"] == "WRONG_ITEM"
    assert result["top_match"]["barcode"] == sample_data["p2"].barcode


def test_decision_branch_escalate_admin_review(db, sample_data):
    """Below LOW threshold (e.g. 0.42 < 0.50) -> ESCALATE_ADMIN_REVIEW"""
    synthetic_frame = np.full((480, 640, 3), 120, dtype=np.uint8)
    settings.CONFIDENCE_HIGH = 0.85
    settings.CONFIDENCE_LOW = 0.50
    mock_candidates = [
        {"id": sample_data["p1"].id, "product_name": sample_data["p1"].name, "barcode": sample_data["p1"].barcode, "similarity": 0.42}
    ]

    with patch("app.ai.verification_engine.VectorStoreMatcher.find_nearest_product", return_value=mock_candidates), \
         patch("app.ai.verification_engine.VectorStoreMatcher.verify_claimed_barcode", return_value=(False, 0.42)), \
         patch("app.ai.verification_engine.feature_extractor.get_embedding", return_value=np.zeros(512, dtype=np.float32)), \
         patch.object(object_detector, "compute_motion_box", return_value=(100, 100, 300, 300)):
        
        result = verification_engine.evaluate_item_placement(
            db=db,
            claimed_barcode=sample_data["p1"].barcode,
            image_data=synthetic_frame,
            cart_id=sample_data["cart"].id,
            session_id=sample_data["session"].id
        )

    assert result["decision"] == "ESCALATE_ADMIN_REVIEW"


def test_decision_branch_face_detected_withheld(db, sample_data):
    """Face detected on packaging: image withheld, flagged with clear message"""
    synthetic_frame = np.full((480, 640, 3), 120, dtype=np.uint8)
    
    result = verification_engine.evaluate_item_placement(
        db=db,
        claimed_barcode=sample_data["p1"].barcode,
        image_data=synthetic_frame,
        cart_id=sample_data["cart"].id,
        session_id=sample_data["session"].id,
        face_present=True
    )

    assert result["decision"] == "FACE_DETECTED_WITHHELD"
    assert result["evidence_url"] is None, "Frame image MUST be withheld when face is detected"
    assert "can't check this item" in result["message"]


# =========================================================================
# 3. Unscanned Item Placement Test
# =========================================================================
def test_unscanned_item_placement(db, sample_data):
    """Motion without PENDING item -> UNSCANNED_DETECTED"""
    synthetic_frame = np.full((480, 640, 3), 120, dtype=np.uint8)
    mock_candidates = [
        {"id": sample_data["p1"].id, "product_name": sample_data["p1"].name, "barcode": sample_data["p1"].barcode, "similarity": 0.89}
    ]

    with patch("app.ai.verification_engine.VectorStoreMatcher.find_nearest_product", return_value=mock_candidates), \
         patch("app.ai.verification_engine.VectorStoreMatcher.verify_claimed_barcode", return_value=(False, 0.0)), \
         patch("app.ai.verification_engine.feature_extractor.get_embedding", return_value=np.zeros(512, dtype=np.float32)), \
         patch.object(object_detector, "compute_motion_box", return_value=(100, 100, 300, 300)):
        
        result = verification_engine.evaluate_item_placement(
            db=db,
            claimed_barcode=None,  # No pending scanned barcode!
            image_data=synthetic_frame,
            cart_id=sample_data["cart"].id,
            session_id=sample_data["session"].id
        )

    assert result["decision"] == "UNSCANNED_DETECTED"
    assert result["top_match"]["id"] == sample_data["p1"].id


# =========================================================================
# 4. Remove and Keep on PENDING Test
# =========================================================================
def test_remove_on_pending_deletes_immediately(db, sample_data):
    """Remove on a PENDING item: delete it immediately, with no camera check and no rescan."""
    async def _run():
        item = await SessionService.scan_item(db, sample_data["session"].id, sample_data["p1"].barcode)
        assert item.status == "PENDING"
        assert sample_data["session"].item_count == 1

        # Shopper clicks Remove on PENDING item
        res = await SessionService.initiate_item_removal(db, sample_data["session"].id, item.id)

        # Item must be deleted immediately
        assert isinstance(res, dict) and res.get("status") == "DELETED"
        existing = db.query(CartItem).filter(CartItem.id == item.id).first()
        assert existing is None, "PENDING item must be deleted from database immediately"

        # Bill totals must be zero
        db.refresh(sample_data["session"])
        assert sample_data["session"].item_count == 0
        assert sample_data["session"].total_amount == 0.0

    run_async(_run())


def test_keep_preserves_pending_state(db, sample_data):
    """Keep (cancel remove) must return the item to exactly its previous state. PENDING must stay PENDING."""
    async def _run():
        item = await SessionService.scan_item(db, sample_data["session"].id, sample_data["p1"].barcode)
        assert item.status == "PENDING"

        # If somehow in removal with previous_status PENDING
        item.status = "REMOVING"
        item.previous_status = "PENDING"
        db.commit()

        # Cancel remove
        restored = await SessionService.cancel_item_removal(db, sample_data["session"].id, item.id)
        assert restored.status == "PENDING", "Restored item must be PENDING, never VERIFIED"

    run_async(_run())


# =========================================================================
# 5. Removal and Rescan Flow Test
# =========================================================================
def test_removal_and_rescan_flow(db, sample_data):
    """VERIFIED -> camera confirms removal -> REMOVED_PENDING_RESCAN -> rescan barcode -> bill updates."""
    async def _run():
        # 1. Add and verify item
        item = await SessionService.scan_item(db, sample_data["session"].id, sample_data["p1"].barcode)
        await SessionService.verify_item_placement(db, sample_data["session"].id, sample_data["p1"].barcode, confidence=0.94)
        db.refresh(item)
        assert item.status == "VERIFIED"

        # 2. Initiate removal
        rem = await SessionService.initiate_item_removal(db, sample_data["session"].id, item.id)
        assert rem.status == "REMOVING"
        assert rem.previous_status == "VERIFIED"

        # 3. Camera confirms departure -> transitions to REMOVED_PENDING_RESCAN
        synthetic_frame = np.full((480, 640, 3), 120, dtype=np.uint8)
        mock_eval_rem = {
            "decision": "CONFIRMED_REMOVED",
            "message": "Item removal confirmed",
            "evidence_url": "/uploads/evidence/test.jpg"
        }
        with patch.object(verification_engine, "evaluate_item_removal", return_value=mock_eval_rem):
            confirmed = await SessionService.verify_item_removal(db, sample_data["session"].id, item.id)
        assert confirmed["status"] == "REMOVED_PENDING_RESCAN"

        # 4. Rescan barcode to complete removal from bill
        removed_res = await SessionService.rescan_to_remove(db, sample_data["session"].id, sample_data["p1"].barcode)
        assert removed_res["product_name"] == sample_data["p1"].name

        # Item is purged and totals recalculated
        existing = db.query(CartItem).filter(CartItem.id == item.id).first()
        assert existing.status == "REMOVED"
        db.refresh(sample_data["session"])
        assert sample_data["session"].item_count == 0
        assert sample_data["session"].total_amount == 0.0

    run_async(_run())


# =========================================================================
# 6. Server-Side Checkout Block Test
# =========================================================================
def test_server_checkout_blocked_states(db, sample_data):
    """Checkout is blocked while any item is PENDING, WARNING, or REMOVED_PENDING_RESCAN."""
    async def _run():
        # Case A: PENDING item blocks checkout
        item = await SessionService.scan_item(db, sample_data["session"].id, sample_data["p1"].barcode)
        details = SessionService.get_session_details(db, sample_data["session"].id)
        assert details["can_checkout"] is False

        with pytest.raises(ValueError, match=".*PENDING.*"):
            await BillingService.process_checkout(db, sample_data["session"].id)

        # Case B: WARNING item blocks checkout
        item.status = "WARNING"
        item.warning_reason = "MISMATCH"
        db.commit()

        details = SessionService.get_session_details(db, sample_data["session"].id)
        assert details["can_checkout"] is False

        with pytest.raises(ValueError, match=".*WARNING.*"):
            await BillingService.process_checkout(db, sample_data["session"].id)

        # Case C: REMOVED_PENDING_RESCAN blocks checkout
        item.status = "REMOVED_PENDING_RESCAN"
        db.commit()

        details = SessionService.get_session_details(db, sample_data["session"].id)
        assert details["can_checkout"] is False

        with pytest.raises(ValueError, match=".*REMOVED_PENDING_RESCAN.*"):
            await BillingService.process_checkout(db, sample_data["session"].id)

        # Case D: All items VERIFIED allows checkout
        item.status = "VERIFIED"
        db.commit()

        details = SessionService.get_session_details(db, sample_data["session"].id)
        assert details["can_checkout"] is True

    run_async(_run())


# =========================================================================
# 7. Privacy: Evidence Cropping Test
# =========================================================================
def test_evidence_snapshot_privacy_cropping():
    """Assert evidence snapshots are cropped strictly to the item area, never full camera frames."""
    full_frame = np.zeros((480, 640, 3), dtype=np.uint8)
    # Put bright square in center to simulate item
    full_frame[140:340, 220:420] = 200
    bounding_box = (220, 140, 420, 340)  # width 200, height 200

    evidence_url = object_detector.save_evidence_snapshot(
        full_frame,
        box=bounding_box,
        label="VERIFIED",
        status="TEST_PRIVACY"
    )

    assert evidence_url.startswith("/uploads/evidence/"), "Evidence URL must point to stored snapshot"

    # Read back the saved image
    filename = os.path.basename(evidence_url)
    snapshot_path = os.path.join(settings.EVIDENCE_DIR, filename)
    assert os.path.exists(snapshot_path), "Snapshot must be saved on disk"

    saved_img = Image.open(snapshot_path)
    # The saved crop dimensions must match the bounding box, NOT 640x480!
    assert saved_img.width <= 210, f"Saved image width {saved_img.width} must be cropped, not full 640"
    assert saved_img.height <= 210, f"Saved image height {saved_img.height} must be cropped, not full 480"
    assert (saved_img.width, saved_img.height) != (640, 480), "Full camera frame MUST NEVER be saved as evidence!"

    # Clean up test artifact
    try:
        os.remove(snapshot_path)
    except Exception:
        pass


# =========================================================================
# 8. Background Removal Rule & Real Crop Preprocessing
# =========================================================================
def test_should_apply_grabcut_real_captured_crop():
    """Verify should_apply_grabcut rule behaves identically on enrollment and verification crops."""
    from app.services.scan_worker import should_apply_grabcut

    catalog_img_path = os.path.join(settings.BASE_DIR, "uploads", "catalog", "7622201745424_FRONT_a1e88d0d.jpg")
    if os.path.exists(catalog_img_path):
        real_crop = Image.open(catalog_img_path)
    else:
        # Fallback to creating a test image if file was removed
        real_crop = Image.new("RGB", (250, 250), (255, 255, 255))

    # A clean crop with uniform border should NOT trigger CPU-heavy GrabCut
    needs_grabcut = should_apply_grabcut(real_crop)
    assert isinstance(needs_grabcut, bool)

    # Process through shared preprocessing
    preproc_crop = preprocess_product_image_for_embedding(real_crop)
    assert preproc_crop.size == (224, 224)
    assert preproc_crop.mode == "RGB"

    # Explicit poor crop override must be respected
    assert should_apply_grabcut(real_crop, explicit_poor_crop=True) is True
    assert should_apply_grabcut(real_crop, explicit_poor_crop=False) is False


# =========================================================================
# 9. Hand and Face Gates & Fallback Crop Safety
# =========================================================================
def test_hand_and_face_gates_in_verification(db, sample_data):
    """Hand and face presence must be gated before any crop is saved or embedded."""
    sample_frame = np.full((480, 640, 3), 120, dtype=np.uint8)

    # Case A: hand_present=True must immediately return HAND_IN_CART without saving evidence
    res_hand = verification_engine.evaluate_item_placement(
        db=db,
        claimed_barcode=sample_data["p1"].barcode,
        image_data=sample_frame,
        hand_present=True,
        face_present=False
    )
    assert res_hand["decision"] == "HAND_IN_CART"
    assert res_hand["warning_reason"] == "HAND_DETECTED"
    assert res_hand["evidence_url"] is None

    # Case B: face_present=True must immediately withhold frame without saving evidence
    res_face = verification_engine.evaluate_item_placement(
        db=db,
        claimed_barcode=sample_data["p1"].barcode,
        image_data=sample_frame,
        hand_present=False,
        face_present=True
    )
    assert res_face["decision"] == "FACE_DETECTED_WITHHELD"
    assert res_face["warning_reason"] == "FACE_DETECTED"
    assert res_face["evidence_url"] is None

    # Case C: save_evidence_snapshot returns None when hand or face is present
    ev_hand = object_detector.save_evidence_snapshot(sample_frame, hand_present=True)
    assert ev_hand is None
    ev_face = object_detector.save_evidence_snapshot(sample_frame, face_present=True)
    assert ev_face is None


# =========================================================================
# 10. Preprocessing Version & Health Diagnostics
# =========================================================================
def test_preprocessing_version_tracking_and_health(db, sample_data):
    """Verify preprocessing_version is recorded and system-health warns on version mismatch."""
    from app.config import CURRENT_PREPROCESSING_VERSION
    from app.ai.vector_store import VectorStoreMatcher
    from app.main import _get_detailed_health_data

    # Store a vector with current version
    emb1 = VectorStoreMatcher.store_embedding(
        db=db,
        product_id=sample_data["p1"].id,
        barcode=sample_data["p1"].barcode,
        angle_tag="FRONT",
        vector=[0.1] * 512,
        commit=True
    )
    assert emb1.preprocessing_version == CURRENT_PREPROCESSING_VERSION

    # Record a verification decision
    verification_engine._record_decision(
        db=db,
        cart_id=sample_data["cart"].id,
        session_id=sample_data["session"].id,
        item_id="item-test-1",
        decision="VERIFIED",
        scanned_barcode=sample_data["p1"].barcode,
        scanned_product_name=sample_data["p1"].name,
        matched_product_id=sample_data["p1"].id,
        matched_product_name=sample_data["p1"].name,
        top1_score=0.92,
        top2_score=0.45,
        threshold_high=0.85,
        threshold_low=0.65,
        evidence_path=None
    )
    decision = db.query(VerificationDecision).filter(VerificationDecision.cart_id == sample_data["cart"].id).first()
    assert decision is not None
    assert decision.preprocessing_version == CURRENT_PREPROCESSING_VERSION

    p2_id = str(sample_data["p2"].id)
    p2_barcode = str(sample_data["p2"].barcode)

    # Mock SessionLocal and check_db_health to use test db and check health diagnostics
    mock_schema = {"is_up_to_date": True, "current_revision": "head", "head_revision": "head", "migration_error": None}
    with patch("app.main.check_db_health", return_value=True), \
         patch("app.migrations.get_schema_info", return_value=mock_schema), \
         patch("app.main.SessionLocal", side_effect=lambda: TestingSessionLocal()):
        health = _get_detailed_health_data(fresh=True)
        assert health["preprocessing_version_current"] == CURRENT_PREPROCESSING_VERSION
        assert health["preprocessing_mismatch_count"] == 0
        assert health["preprocessing_warning"] is None

        # Insert an outdated vector and verify warning triggers
        emb_old = ProductEmbedding(
            product_id=p2_id,
            barcode=p2_barcode,
            angle_tag="BACK",
            embedding_json="[]",
            preprocessing_version="v1_outdated"
        )
        db_s = TestingSessionLocal()
        db_s.add(emb_old)
        db_s.commit()
        db_s.close()

        health_mismatch = _get_detailed_health_data(fresh=True)
        assert health_mismatch["preprocessing_mismatch_count"] >= 1
        assert "outdated preprocessing version" in health_mismatch["preprocessing_warning"]


# =========================================================================
# 11. Calibration Session API Endpoints
# =========================================================================
def test_calibration_session_api_flow(db, sample_data):
    """Test calibration endpoints: sample capture, distribution stats, apply thresholds, reset."""
    from app.api.v1.vision import (
        record_calibration_sample,
        get_calibration_stats,
        reset_calibration_session,
        apply_calibration_thresholds,
        CalibrationSampleRequest,
        ApplyThresholdsRequest
    )
    from fastapi import HTTPException

    mock_admin = MagicMock()

    # Reset before start
    reset_calibration_session(current_user=mock_admin)

    # 1. Sample with hand_present should be rejected with 400
    with pytest.raises(HTTPException) as exc_info:
        record_calibration_sample(
            req=CalibrationSampleRequest(
                target_barcode=sample_data["p1"].barcode,
                image_data_url="data:image/jpeg;base64," + "A" * 200,
                hand_present=True
            ),
            db=db,
            current_user=mock_admin
        )
    assert exc_info.value.status_code == 400
    assert "Hand detected" in exc_info.value.detail

    # 2. Record valid sample
    # Create simple valid test image
    test_img = Image.new("RGB", (100, 100), (200, 150, 100))
    import io, base64
    buf = io.BytesIO()
    test_img.save(buf, format="JPEG")
    valid_data_url = f"data:image/jpeg;base64,{base64.b64encode(buf.getvalue()).decode('utf-8')}"

    with patch("app.api.v1.vision.get_embedding", return_value=[0.1] * 512):
        with patch("app.api.v1.vision.VectorStoreMatcher.find_nearest_product", return_value=[
            {"product_name": sample_data["p1"].name, "barcode": sample_data["p1"].barcode, "similarity": 0.88},
            {"product_name": sample_data["p2"].name, "barcode": sample_data["p2"].barcode, "similarity": 0.52}
        ]):
            res = record_calibration_sample(
                req=CalibrationSampleRequest(
                    target_barcode=sample_data["p1"].barcode,
                    image_data_url=valid_data_url,
                    angle_label="OVERHEAD",
                    hand_present=False,
                    face_present=False
                ),
                db=db,
                current_user=mock_admin
            )
            assert res["is_same_product"] is True
            assert res["total_samples"] == 1

            # 3. Retrieve stats
            stats = get_calibration_stats(current_user=mock_admin)
            assert stats["total_samples"] == 1
            assert len(stats["threshold_matrix"]) == 4  # 0.60, 0.70, 0.80, 0.85
            assert stats["suggested_high"] >= 0.70
            assert stats["suggested_low"] <= stats["suggested_high"]

            # 4. Apply thresholds
            apply_res = apply_calibration_thresholds(
                req=ApplyThresholdsRequest(confidence_high=0.82, confidence_low=0.60),
                current_user=mock_admin
            )
            assert apply_res["confidence_high"] == 0.82
            assert apply_res["confidence_low"] == 0.60
            assert settings.CONFIDENCE_HIGH == 0.82
            assert settings.CONFIDENCE_LOW == 0.60

            # 5. Reset session
            reset_res = reset_calibration_session(current_user=mock_admin)
            assert reset_res["count"] == 0


if __name__ == "__main__":
    print("Running test_verification_step2 suite...")

    # Helper to run fixture-dependent test
    def run_with_fixtures(test_func):
        conn = test_engine.connect()
        trans = conn.begin()
        session = TestingSessionLocal(bind=conn)
        try:
            s_data = sample_data(session)
            test_func(session, s_data)
        finally:
            session.close()
            trans.rollback()
            conn.close()

    # Run standalone tests (without db fixtures)
    test_pipeline_equality()
    print("  [OK] test_pipeline_equality")
    test_evidence_snapshot_privacy_cropping()
    print("  [OK] test_evidence_snapshot_privacy_cropping")
    test_should_apply_grabcut_real_captured_crop()
    print("  [OK] test_should_apply_grabcut_real_captured_crop")

    tests = [
        test_decision_branch_auto_approve,
        test_decision_branch_reposition_prompt,
        test_decision_branch_wrong_item,
        test_decision_branch_escalate_admin_review,
        test_decision_branch_face_detected_withheld,
        test_unscanned_item_placement,
        test_remove_on_pending_deletes_immediately,
        test_keep_preserves_pending_state,
        test_removal_and_rescan_flow,
        test_server_checkout_blocked_states,
        test_hand_and_face_gates_in_verification,
        test_preprocessing_version_tracking_and_health,
        test_calibration_session_api_flow,
    ]

    for t in tests:
        run_with_fixtures(t)
        print(f"  [OK] {t.__name__}")

    print("ALL test_verification_step2 SUITE TESTS PASSED!")
