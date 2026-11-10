import os
import sys
import asyncio
import pytest
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

    asyncio.run(_run())


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

    asyncio.run(_run())


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

    asyncio.run(_run())


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

    asyncio.run(_run())


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
