"""Cart State Machine Module (Phase 1).

Encapsulates all cart verification logic, states, transitions, and rules R1 to R10
in one central module. Enforces server-side scan blocking with reason codes,
cart-state memory snapshots, full multi-object matching, removal tracking,
violation handling, and checkout authorization.
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any

from sqlalchemy.orm import Session

from app.config import settings
from app.models.alert import Alert
from app.models.product import Product
from app.models.session import CartItem, CartSession
from app.models.transaction import SystemSetting

logger = logging.getLogger("smartcart.state_machine")


# ==============================================================================
# Enumerations & Constants
# ==============================================================================


class CartState(str, Enum):
    """Cart operational state lifecycle."""

    EMPTY_CHECK = "EMPTY_CHECK"  # Session start: verifying physical cart is empty
    READY = "READY"  # Empty confirmed, ready to scan
    ITEM_PENDING = "ITEM_PENDING"  # Barcode scanned, awaiting placement
    VERIFYING = "VERIFYING"  # Placement detected, verifying stability and embeddings
    REMOVING = "REMOVING"  # User initiated delete, awaiting removal confirmation
    VIOLATION = "VIOLATION"  # Discrepancy active (unscanned add, unauthorized removal, etc.)
    STAFF_CHECK = "STAFF_CHECK"  # Requires human intervention (face, ambiguity, low confidence)
    CHECKOUT_READY = "CHECKOUT_READY"  # All items verified, ready to pay
    CHECKED_OUT = "CHECKED_OUT"  # Session finalized


class ScanBlockReason(str, Enum):
    """Server-side scan-item rejection reason codes (HTTP 409)."""

    CART_NOT_EMPTY = "CART_NOT_EMPTY"
    CAMERA_OFFLINE = "CAMERA_OFFLINE"
    NO_REFERENCE = "NO_REFERENCE"
    ITEM_PENDING = "ITEM_PENDING"
    ITEM_REMOVING = "ITEM_REMOVING"
    VIOLATION_OPEN = "VIOLATION_OPEN"
    STAFF_CHECK_REQUIRED = "STAFF_CHECK_REQUIRED"


class ViolationType(str, Enum):
    """Violation classifications (R6)."""

    UNSCANNED_ADD = "UNSCANNED_ADD"
    UNAUTHORIZED_REMOVE = "UNAUTHORIZED_REMOVE"
    WRONG_ITEM_REMOVED = "WRONG_ITEM_REMOVED"
    CART_NOT_EMPTY_AT_START = "CART_NOT_EMPTY_AT_START"


class DecisionOutcome(str, Enum):
    """Placement decision outcomes (R3)."""

    VERIFIED = "VERIFIED"
    REPOSITION = "REPOSITION"
    WRONG_ITEM = "WRONG_ITEM"
    REVIEW = "REVIEW"


class ScanBlockedError(Exception):
    """Raised when server-side business rules refuse barcode scan."""

    def __init__(self, reason_code: ScanBlockReason, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.reason_code = reason_code
        self.message = message
        self.details = details or {}


@dataclass
class BoundingBox:
    x: float
    y: float
    width: float
    height: float

    def to_dict(self) -> dict[str, float]:
        return {"x": self.x, "y": self.y, "width": self.width, "height": self.height}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BoundingBox:
        return cls(
            x=float(data.get("x", 0.0)),
            y=float(data.get("y", 0.0)),
            width=float(data.get("width", 0.0)),
            height=float(data.get("height", 0.0)),
        )


@dataclass
class StoredItemSnapshot:
    """Stored snapshot of an in-cart item verified by camera (R3)."""

    item_id: str
    product_id: str
    product_name: str
    barcode: str
    crop_embedding: list[float]
    bounding_box: BoundingBox
    last_known_crop_path: str | None
    verified_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "product_id": self.product_id,
            "product_name": self.product_name,
            "barcode": self.barcode,
            "crop_embedding": self.crop_embedding,
            "bounding_box": self.bounding_box.to_dict(),
            "last_known_crop_path": self.last_known_crop_path,
            "verified_at": self.verified_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StoredItemSnapshot:
        box_data = data.get("bounding_box", {})
        return cls(
            item_id=str(data["item_id"]),
            product_id=str(data["product_id"]),
            product_name=str(data.get("product_name", "")),
            barcode=str(data.get("barcode", "")),
            crop_embedding=list(data.get("crop_embedding", [])),
            bounding_box=BoundingBox.from_dict(box_data) if isinstance(box_data, dict) else BoundingBox(0, 0, 0, 0),
            last_known_crop_path=data.get("last_known_crop_path"),
            verified_at=str(data.get("verified_at", "")),
        )


@dataclass
class DetectedRegion:
    """Object detection region extracted from cart camera frame."""

    region_id: str
    bounding_box: BoundingBox
    embedding: list[float]
    confidence: float
    crop_path: str | None = None
    is_face_detected: bool = False
    is_hand_present: bool = False


@dataclass
class FullMatchResult:
    """Result of full multi-object matching across cart frame (R4)."""

    matched_pairs: list[tuple[StoredItemSnapshot, DetectedRegion, float]]
    unmatched_objects: list[DetectedRegion]
    unmatched_items: list[StoredItemSnapshot]
    count_matches: bool
    hand_activity_logged: bool
    requires_staff_check: bool
    staff_reason: str | None = None


# ==============================================================================
# Vector Math Utilities
# ==============================================================================


def cosine_similarity(v1: list[float], v2: list[float]) -> float:
    """Computes cosine similarity between two vector embeddings."""
    if not v1 or not v2 or len(v1) != len(v2):
        return 0.0
    dot = sum(a * b for a, b in zip(v1, v2))
    norm_a = math.sqrt(sum(a * a for a in v1))
    norm_b = math.sqrt(sum(b * b for b in v2))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


# ==============================================================================
# Cart State Machine Engine
# ==============================================================================


class CartStateMachine:
    """Core state machine implementing supermarket rules R1 through R10."""

    # Timing & spatial constants (thresholds are sourced from DB system_settings / settings)
    EMPTY_DIFF_THRESHOLD = 0.05
    EMPTY_STABLE_SECONDS = 2.0
    PLACEMENT_STABLE_SECONDS = 1.0
    PENDING_REMINDER_SECONDS = 60.0
    MOTION_WARNING_SECONDS = 20.0
    MOTION_ESCALATE_SECONDS = 60.0
    VIOLATION_COOLDOWN_SECONDS = 60.0

    @classmethod
    def get_active_thresholds(cls, db: Session | None = None) -> tuple[float, float, float]:
        """Return (confidence_high, confidence_low, min_margin) from DB system_settings or settings defaults."""
        high = float(getattr(settings, "CONFIDENCE_HIGH", 0.85))
        low = float(getattr(settings, "CONFIDENCE_LOW", 0.65))
        margin = float(getattr(settings, "MIN_MARGIN", 0.08))
        if db is None:
            return high, low, margin
        try:
            rows = db.query(SystemSetting).filter(
                SystemSetting.key.in_(["confidence_high", "confidence_low", "min_margin"])
            ).all()
            kv = {r.key: r.value for r in rows}
            if "confidence_high" in kv:
                high = float(kv["confidence_high"])
            if "confidence_low" in kv:
                low = float(kv["confidence_low"])
            if "min_margin" in kv:
                margin = float(kv["min_margin"])
        except Exception:
            pass
        return high, low, margin

    @classmethod
    def save_thresholds(
        cls,
        db: Session,
        confidence_high: float,
        confidence_low: float,
        min_margin: float | None = None,
    ) -> tuple[float, float, float]:
        """Persist AI thresholds in DB system_settings and update live settings."""
        high = round(float(confidence_high), 4)
        low = round(float(confidence_low), 4)
        margin = round(float(min_margin if min_margin is not None else getattr(settings, "MIN_MARGIN", 0.08)), 4)
        updates = {
            "confidence_high": str(high),
            "confidence_low": str(low),
            "min_margin": str(margin),
        }
        now_dt = datetime.utcnow()
        for k, v in updates.items():
            row = db.query(SystemSetting).filter(SystemSetting.key == k).first()
            if row:
                row.value = v
                row.updated_at = now_dt
            else:
                db.add(SystemSetting(key=k, value=v, updated_at=now_dt))
        db.commit()
        settings.CONFIDENCE_HIGH = high
        settings.CONFIDENCE_LOW = low
        settings.MIN_MARGIN = margin
        return high, low, margin

    # --------------------------------------------------------------------------
    # R1: EMPTY START
    # --------------------------------------------------------------------------
    @classmethod
    def evaluate_empty_start(
        cls,
        camera_online: bool,
        has_reference: bool,
        diff_from_ref: float,
        stable_seconds: float,
        hand_present: bool,
        face_present: bool,
        detected_objects_count: int,
        staff_override: bool = False,
        staff_reason: str | None = None,
    ) -> tuple[bool, str, ScanBlockReason | None]:
        """Evaluates whether cart is verified empty at session start (R1).

        Returns: (is_empty, message, block_reason)
        """
        if staff_override:
            if not staff_reason or not staff_reason.strip():
                return False, "Staff override requires a valid documented reason.", ScanBlockReason.CART_NOT_EMPTY
            logger.info("R1: Staff override granted for empty start: %s", staff_reason)
            return True, f"Staff override approved: {staff_reason.strip()}", None

        if not camera_online:
            return False, "Cart camera is offline. Scanning is paused.", ScanBlockReason.CAMERA_OFFLINE

        if not has_reference:
            return False, "Cart camera calibration reference missing. Scanning paused.", ScanBlockReason.NO_REFERENCE

        if hand_present or face_present:
            return False, "Hand or person detected in cart view. Please step back.", ScanBlockReason.CART_NOT_EMPTY

        if detected_objects_count > 0 or diff_from_ref > cls.EMPTY_DIFF_THRESHOLD:
            return False, "Please empty the cart. Remove any items inside before scanning.", ScanBlockReason.CART_NOT_EMPTY

        if stable_seconds < cls.EMPTY_STABLE_SECONDS:
            return False, "Waiting for cart camera to stabilize...", ScanBlockReason.CART_NOT_EMPTY

        return True, "Cart verified empty. Ready to scan items.", None

    # --------------------------------------------------------------------------
    # R2: ONE PENDING AT A TIME & SCAN VALIDATION
    # --------------------------------------------------------------------------
    @classmethod
    def validate_can_scan(
        cls,
        session: CartSession,
        db: Session,
        cart_empty_verified: bool = True,
        cart_camera_online: bool = True,
        has_reference: bool = True,
    ) -> None:
        """Enforces all server-side scan blocking rules (R1, R2, R5, R6).

        Raises ScanBlockedError with reason code on rejection.
        """
        # R1 Check: Camera online & Reference
        if not cart_camera_online:
            raise ScanBlockedError(ScanBlockReason.CAMERA_OFFLINE, "Camera is offline. Please wait for camera connection.")
        if not has_reference:
            raise ScanBlockedError(ScanBlockReason.NO_REFERENCE, "Camera calibration reference missing. Scanning paused.")

        # R1 Check: Empty verified at start
        if not cart_empty_verified and not session.cart_empty_verified:
            raise ScanBlockedError(ScanBlockReason.CART_NOT_EMPTY, "Please empty the cart before scanning your first item.")

        # R2 Check: No other item may be PENDING
        pending_items = (
            db.query(CartItem)
            .filter(
                CartItem.session_id == session.id,
                CartItem.status == "PENDING",
            )
            .all()
        )
        if pending_items:
            first_p = pending_items[0]
            prod_name = first_p.product.name if first_p.product else "scanned item"
            raise ScanBlockedError(
                ScanBlockReason.ITEM_PENDING,
                f"Place the scanned item first ('{prod_name}').",
                {"pending_item_id": first_p.id, "pending_barcode": first_p.product.barcode if first_p.product else None},
            )

        # R5 Check: No item may be in REMOVING state
        removing_items = (
            db.query(CartItem)
            .filter(
                CartItem.session_id == session.id,
                CartItem.status.in_(["REMOVING", "REMOVED_PENDING_RESCAN"]),
            )
            .all()
        )
        if removing_items:
            first_r = removing_items[0]
            prod_name = first_r.product.name if first_r.product else "item"
            raise ScanBlockedError(
                ScanBlockReason.ITEM_REMOVING,
                f"Please finish removing '{prod_name}' before scanning another item.",
                {"removing_item_id": first_r.id},
            )

        # R6 Check: No open violation alerts
        open_violations = (
            db.query(Alert)
            .filter(
                Alert.session_id == session.id,
                Alert.status == "OPEN",
                Alert.alert_type.in_(
                    [
                        ViolationType.UNSCANNED_ADD.value,
                        ViolationType.UNAUTHORIZED_REMOVE.value,
                        ViolationType.WRONG_ITEM_REMOVED.value,
                        ViolationType.CART_NOT_EMPTY_AT_START.value,
                        "REMOVAL_WITHOUT_RESCAN",
                        "MISMATCH_ITEM",
                    ]
                ),
            )
            .all()
        )
        if open_violations:
            first_v = open_violations[0]
            raise ScanBlockedError(
                ScanBlockReason.VIOLATION_OPEN,
                f"Scanning paused: {first_v.message}",
                {"alert_id": first_v.id, "alert_type": first_v.alert_type},
            )

    @classmethod
    def cancel_pending_item(cls, db: Session, session_id: str, item_id: str) -> bool:
        """Shopper cancels a PENDING item: deleted directly with no camera check (R2)."""
        item = (
            db.query(CartItem)
            .filter(
                CartItem.id == item_id,
                CartItem.session_id == session_id,
                CartItem.status == "PENDING",
            )
            .first()
        )
        if not item:
            return False

        logger.info("R2: Shopper directly cancelled PENDING item %s without camera check", item_id)
        db.delete(item)
        db.commit()
        return True

    @classmethod
    def check_pending_reminder(cls, item: CartItem, now: datetime | None = None) -> bool:
        """Returns True if pending item has waited > 60 seconds without placement (R2)."""
        if item.status != "PENDING" or not item.scanned_at:
            return False
        current_time = now or datetime.utcnow()
        elapsed = (current_time - item.scanned_at).total_seconds()
        return elapsed >= cls.PENDING_REMINDER_SECONDS

    # --------------------------------------------------------------------------
    # R3: PLACEMENT CHECK & CART STATE SNAPSHOT
    # --------------------------------------------------------------------------
    @classmethod
    def evaluate_placement(
        cls,
        scanned_product_score: float,
        runner_up_score: float,
        runner_up_product_name: str | None = None,
        threshold_high: float | None = None,
        threshold_low: float | None = None,
        min_margin: float | None = None,
        face_detected: bool = False,
    ) -> tuple[DecisionOutcome, str, float]:
        """Evaluates placement frame against confidence and margin thresholds (R3).

        Returns: (DecisionOutcome, reason_text, margin)
        """
        th_high = threshold_high if threshold_high is not None else float(getattr(settings, "CONFIDENCE_HIGH", 0.85))
        th_low = threshold_low if threshold_low is not None else float(getattr(settings, "CONFIDENCE_LOW", 0.65))
        margin_req = min_margin if min_margin is not None else float(getattr(settings, "MIN_MARGIN", 0.08))

        # Privacy rule: never judge with human face in crop
        if face_detected:
            return (
                DecisionOutcome.REVIEW,
                "Frame withheld: person face detected in camera crop. Staff approval required.",
                0.0,
            )

        margin = scanned_product_score - runner_up_score

        # 1. VERIFIED: high confidence and distinct margin
        if scanned_product_score >= th_high and margin >= margin_req:
            return (
                DecisionOutcome.VERIFIED,
                f"Verified: score {scanned_product_score:.3f} >= {th_high:.2f} (margin +{margin:.3f})",
                margin,
            )

        # 2. WRONG_ITEM: runner-up clearly dominates scanned item
        if runner_up_score >= th_high and (runner_up_score - scanned_product_score) >= margin_req:
            other_name = runner_up_product_name or "different product"
            return (
                DecisionOutcome.WRONG_ITEM,
                f"Wrong item: camera detected '{other_name}' ({runner_up_score:.3f}) instead of scanned product",
                margin,
            )

        # 3. REPOSITION: score above low threshold but not confidently high
        if scanned_product_score >= th_low:
            return (
                DecisionOutcome.REPOSITION,
                f"Reposition: score {scanned_product_score:.3f} below high threshold {th_high:.2f}. Please turn label towards camera.",
                margin,
            )

        # 4. REVIEW / UNCERTAIN
        return (
            DecisionOutcome.REVIEW,
            f"Review required: score {scanned_product_score:.3f} below threshold {th_low:.2f}",
            margin,
        )

    @classmethod
    def create_item_snapshot(
        cls,
        item: CartItem,
        crop_embedding: list[float],
        box: BoundingBox,
        crop_path: str | None,
    ) -> StoredItemSnapshot:
        """Creates and stores cart-state snapshot for a VERIFIED item (R3).

        Never stores human faces.
        """
        snapshot = StoredItemSnapshot(
            item_id=item.id,
            product_id=item.product_id,
            product_name=item.product.name if item.product else "",
            barcode=item.product.barcode if item.product else "",
            crop_embedding=crop_embedding,
            bounding_box=box,
            last_known_crop_path=crop_path,
            verified_at=datetime.utcnow().isoformat(),
        )

        item.crop_embedding = json.dumps(crop_embedding)
        item.bounding_box = json.dumps(box.to_dict())
        item.last_known_crop_path = crop_path
        item.status = "VERIFIED"
        item.verified_at = datetime.utcnow()
        return snapshot

    # --------------------------------------------------------------------------
    # R4: FULL MULTI-OBJECT MATCH & MOVEMENT INVARIANTS
    # --------------------------------------------------------------------------
    @classmethod
    def run_full_match(
        cls,
        stored_items: list[StoredItemSnapshot],
        detected_regions: list[DetectedRegion],
        has_pending_item: bool = False,
        hand_activity_occurred: bool = False,
        unstable_motion_seconds: float = 0.0,
        threshold_low: float | None = None,
    ) -> FullMatchResult:
        """Executes full multi-object matching across cart frame (R4).

        Movement is not a change and cannot hide a change.
        """
        # Long motion check (>20s prompt, >60s staff escalation)
        if unstable_motion_seconds > cls.MOTION_ESCALATE_SECONDS:
            return FullMatchResult(
                matched_pairs=[],
                unmatched_objects=detected_regions,
                unmatched_items=stored_items,
                count_matches=False,
                hand_activity_logged=hand_activity_occurred,
                requires_staff_check=True,
                staff_reason="Cart motion unstable for > 60 seconds. Staff inspection required.",
            )

        matched_pairs: list[tuple[StoredItemSnapshot, DetectedRegion, float]] = []
        unmatched_items = list(stored_items)
        unmatched_regions = list(detected_regions)

        # 1-to-1 greedy similarity matching with position tie-breaking
        scored_pairs: list[tuple[float, StoredItemSnapshot, DetectedRegion]] = []
        for itm in stored_items:
            for reg in detected_regions:
                sim = cosine_similarity(itm.crop_embedding, reg.embedding)
                # Position tie-breaker penalty if wildly shifted
                dist = math.hypot(itm.bounding_box.x - reg.bounding_box.x, itm.bounding_box.y - reg.bounding_box.y)
                tie_broken_score = sim - (dist * 0.05)
                scored_pairs.append((tie_broken_score, itm, reg))

        # Sort descending by match score
        scored_pairs.sort(key=lambda x: x[0], reverse=True)

        assigned_items: set[str] = set()
        assigned_regions: set[str] = set()

        th_low = threshold_low if threshold_low is not None else float(getattr(settings, "CONFIDENCE_LOW", 0.65))
        for score, itm, reg in scored_pairs:
            if itm.item_id in assigned_items or reg.region_id in assigned_regions:
                continue
            # Must meet minimum threshold to consider matched
            sim_raw = cosine_similarity(itm.crop_embedding, reg.embedding)
            if sim_raw >= th_low:
                matched_pairs.append((itm, reg, sim_raw))
                assigned_items.add(itm.item_id)
                assigned_regions.add(reg.region_id)

        unmatched_items = [i for i in stored_items if i.item_id not in assigned_items]
        unmatched_regions = [r for r in detected_regions if r.region_id not in assigned_regions]

        # Count invariant check: detected objects == stored items (+ 1 if item is pending)
        expected_count = len(stored_items) + (1 if has_pending_item else 0)
        actual_count = len(detected_regions)
        count_matches = expected_count == actual_count

        requires_staff = False
        staff_reason = None

        # Check for overlap / occlusion (two detected boxes overlapping significantly)
        for i, r1 in enumerate(detected_regions):
            for r2 in detected_regions[i + 1 :]:
                overlap = cls._compute_iou(r1.bounding_box, r2.bounding_box)
                if overlap > 0.45:
                    requires_staff = True
                    staff_reason = "Object overlap/hiding detected in cart. Staff check required."
                    break

        # Check for ambiguous matches (two stored items equally close in appearance)
        if not requires_staff and len(stored_items) >= 2:
            for reg in detected_regions:
                sims = [
                    (itm, cosine_similarity(itm.crop_embedding, reg.embedding))
                    for itm in stored_items
                ]
                sims.sort(key=lambda s: s[1], reverse=True)
                if len(sims) >= 2 and sims[0][1] >= th_low and sims[1][1] >= th_low:
                    if abs(sims[0][1] - sims[1][1]) < 0.03:
                        requires_staff = True
                        staff_reason = (
                            f"Ambiguous match for region {reg.region_id} between "
                            f"'{sims[0][0].product_name}' and '{sims[1][0].product_name}'. Staff check required."
                        )
                        break

        return FullMatchResult(
            matched_pairs=matched_pairs,
            unmatched_objects=unmatched_regions,
            unmatched_items=unmatched_items,
            count_matches=count_matches,
            hand_activity_logged=hand_activity_occurred,
            requires_staff_check=requires_staff,
            staff_reason=staff_reason,
        )

    @staticmethod
    def _compute_iou(b1: BoundingBox, b2: BoundingBox) -> float:
        """Computes intersection over union (IoU) of two bounding boxes."""
        x_left = max(b1.x, b2.x)
        y_top = max(b1.y, b2.y)
        x_right = min(b1.x + b1.width, b2.x + b2.width)
        y_bottom = min(b1.y + b1.height, b2.y + b2.height)

        if x_right <= x_left or y_bottom <= y_top:
            return 0.0

        intersection = (x_right - x_left) * (y_bottom - y_top)
        area1 = b1.width * b1.height
        area2 = b2.width * b2.height
        union = area1 + area2 - intersection
        return intersection / union if union > 0 else 0.0

    # --------------------------------------------------------------------------
    # R5: REMOVAL FLOW
    # --------------------------------------------------------------------------
    @classmethod
    def initiate_removal(cls, db: Session, session: CartSession, item_id: str) -> tuple[CartItem | None, bool]:
        """Shopper taps Delete on an item (R5).

        If PENDING: deleted directly without camera check.
        If VERIFIED: set to REMOVING, server refuses scan-item.
        """
        item = (
            db.query(CartItem)
            .filter(
                CartItem.id == item_id,
                CartItem.session_id == session.id,
            )
            .first()
        )
        if not item:
            return None, False

        if item.status == "PENDING":
            # Direct delete
            logger.info("R5: Deleting PENDING item directly: %s", item_id)
            db.delete(item)
            db.commit()
            return None, True

        # VERIFIED item transitions to REMOVING
        item.previous_status = item.status
        item.status = "REMOVING"
        db.commit()
        db.refresh(item)
        logger.info("R5: Item %s entered REMOVING state. Scan-item now refused.", item_id)
        return item, False

    @classmethod
    def confirm_removal(
        cls,
        db: Session,
        item: CartItem,
        stored_items: list[StoredItemSnapshot],
        detected_regions: list[DetectedRegion],
        threshold_low: float | None = None,
    ) -> bool:
        """Confirms that the REMOVING item is physically gone from the cart (R5).

        On confirmation, item status becomes REMOVED.
        """
        th_low = threshold_low if threshold_low is not None else float(getattr(settings, "CONFIDENCE_LOW", 0.65))
        # Search if any remaining detected region matches the item's stored crop
        item_embedding = json.loads(item.crop_embedding) if item.crop_embedding else None
        if item_embedding:
            for reg in detected_regions:
                sim = cosine_similarity(item_embedding, reg.embedding)
                if sim >= th_low:
                    # Item is still physically present in cart
                    return False

        item.status = "REMOVED"
        db.flush()
        from app.models.session import CartSession
        from app.services.session_service import SessionService
        sess = item.session or db.query(CartSession).filter(CartSession.id == item.session_id).first()
        if sess:
            SessionService.recalculate_session_totals(db, sess)
        db.commit()
        logger.info("R5: Camera confirmed removal of item %s. Dropped from bill.", item.id)
        return True

    @classmethod
    def cancel_removal(cls, db: Session, item: CartItem) -> CartItem:
        """Shopper taps 'Keep' to cancel removal: restores previous verified state (R5)."""
        item.status = item.previous_status or "VERIFIED"
        db.commit()
        db.refresh(item)
        logger.info("R5: Removal cancelled. Item %s restored to %s.", item.id, item.status)
        return item

    # --------------------------------------------------------------------------
    # R6: VIOLATIONS & DE-DUPLICATION
    # --------------------------------------------------------------------------
    @classmethod
    def record_violation(
        cls,
        db: Session,
        session_id: str,
        cart_id: str,
        violation_type: ViolationType,
        message: str,
        evidence_path: str | None = None,
        item_id: str | None = None,
    ) -> Alert | None:
        """Creates or updates a single open violation alert (R6).

        Enforces: exactly ONE open alert per (session, violation_type, item).
        Never creates duplicate open alerts.
        Enforces: resolved violation cannot be re-created within 60s cooldown (R8).
        """
        # 1. Check 60s cooldown against previously resolved violations for this session/condition (R8)
        recent_resolved = (
            db.query(Alert)
            .filter(
                Alert.session_id == session_id,
                Alert.status.in_(["RESOLVED", "DISMISSED"]),
                Alert.violation_type == violation_type.value,
                Alert.item_id == item_id,
            )
            .order_by(Alert.resolved_at.desc())
            .first()
        )
        if recent_resolved and recent_resolved.resolved_at:
            if not cls.can_recreate_violation(recent_resolved.resolved_at):
                logger.info(
                    "R8: Suppressed recreating violation %s for session %s (item %s) within 60s cooldown.",
                    violation_type.value,
                    session_id,
                    item_id,
                )
                return None

        alert_type_val = "UNSCANNED_ITEM" if violation_type == ViolationType.UNSCANNED_ADD else violation_type.value
        existing = (
            db.query(Alert)
            .filter(
                Alert.session_id == session_id,
                Alert.status == "OPEN",
                (Alert.violation_type == violation_type.value) | (Alert.alert_type == alert_type_val),
                Alert.item_id == item_id,
            )
            .first()
        )

        if existing:
            # Update existing alert in-place
            existing.message = message
            existing.alert_type = alert_type_val
            existing.violation_type = violation_type.value
            if evidence_path:
                existing.evidence_path = evidence_path
                existing.evidence_snapshot_url = evidence_path
            db.commit()
            db.refresh(existing)
            logger.info("R6: Updated existing open violation alert %s (%s)", existing.id, violation_type.value)
            return existing

        new_alert = Alert(
            cart_id=cart_id,
            session_id=session_id,
            item_id=item_id,
            alert_type=alert_type_val,
            violation_type=violation_type.value,
            severity="HIGH",
            message=message,
            evidence_snapshot_url=evidence_path,
            evidence_path=evidence_path,
            status="OPEN",
            created_at=datetime.utcnow(),
        )
        db.add(new_alert)
        db.commit()
        db.refresh(new_alert)
        logger.warning("R6: Raised violation %s for session %s (Item: %s)", violation_type.value, session_id, item_id)
        return new_alert

    # --------------------------------------------------------------------------
    # R7: WHICH ITEM WAS REMOVED
    # --------------------------------------------------------------------------
    @classmethod
    def identify_missing_item(
        cls,
        stored_items: list[StoredItemSnapshot],
        detected_regions: list[DetectedRegion],
        threshold_low: float | None = None,
    ) -> tuple[StoredItemSnapshot | None, float, list[dict[str, Any]]]:
        """Identifies which item was removed on UNAUTHORIZED_REMOVE (R7).

        Returns: (missing_item, confidence, top_candidates)
        """
        th_low = threshold_low if threshold_low is not None else float(getattr(settings, "CONFIDENCE_LOW", 0.65))
        candidates: list[dict[str, Any]] = []

        for itm in stored_items:
            best_sim = 0.0
            for reg in detected_regions:
                sim = cosine_similarity(itm.crop_embedding, reg.embedding)
                if sim > best_sim:
                    best_sim = sim
            # Missing score = 1.0 - best_similarity_found
            missing_confidence = max(0.0, 1.0 - best_sim)
            candidates.append({
                "item_id": itm.item_id,
                "product_name": itm.product_name,
                "barcode": itm.barcode,
                "missing_confidence": missing_confidence,
                "last_known_crop_path": itm.last_known_crop_path,
                "snapshot": itm,
            })

        # Sort descending by missing confidence
        candidates.sort(key=lambda c: c["missing_confidence"], reverse=True)

        if not candidates or candidates[0]["missing_confidence"] < (1.0 - th_low):
            return None, 0.0, candidates

        top_cand = candidates[0]
        return top_cand["snapshot"], top_cand["missing_confidence"], candidates[:3]

    # --------------------------------------------------------------------------
    # R8: RESOLVING A VIOLATION
    # --------------------------------------------------------------------------
    @classmethod
    def can_recreate_violation(
        cls,
        resolved_at: datetime | None,
        now: datetime | None = None,
    ) -> bool:
        """Enforces that a resolved violation cannot be recreated within 60s (R8)."""
        if not resolved_at:
            return True
        current_time = now or datetime.utcnow()
        elapsed = (current_time - resolved_at).total_seconds()
        return elapsed >= cls.VIOLATION_COOLDOWN_SECONDS

    @classmethod
    def resolve_violation(
        cls,
        db: Session,
        alert: Alert,
        staff_user_id: str | None = None,
        reason: str = "Cart state verified by staff",
    ) -> Alert:
        """Resolves violation with mandatory audit reason (R8).

        Resolving an alert marks the item as staff approved (who, when, why).
        The item stays VERIFIED even if the camera still sees it in the same place.
        """
        if not reason or not reason.strip():
            raise ValueError("Resolution requires a non-empty audit reason.")

        clean_reason = reason.strip()
        now_dt = datetime.utcnow()
        alert.status = "RESOLVED"
        alert.resolved_by = staff_user_id
        alert.resolution_notes = clean_reason
        alert.resolved_at = now_dt

        # If alert is associated with a cart item, mark item staff approved and keep it VERIFIED
        if alert.item_id:
            item = db.query(CartItem).filter(CartItem.id == alert.item_id).first()
            if item:
                item.staff_approved = True
                item.staff_approved_at = now_dt
                item.staff_approved_by = staff_user_id
                item.status = "VERIFIED"

        # If alert is session empty start violation, unblock session with audit details
        if alert.session_id and alert.violation_type == ViolationType.CART_NOT_EMPTY_AT_START.value:
            sess = db.query(CartSession).filter(CartSession.id == alert.session_id).first()
            if sess:
                sess.cart_empty_verified = True
                sess.empty_override_by = staff_user_id
                sess.empty_override_reason = clean_reason

        db.commit()
        db.refresh(alert)
        logger.info("R8: Violation %s resolved by %s: %s", alert.id, staff_user_id, clean_reason)
        return alert

    # --------------------------------------------------------------------------
    # R9: CHECKOUT ENFORCEMENT
    # --------------------------------------------------------------------------
    @classmethod
    def validate_can_checkout(
        cls,
        session: CartSession,
        db: Session,
        detected_objects_count: int,
    ) -> tuple[bool, str | None, ScanBlockReason | None]:
        """Validates that checkout is allowed only with zero pending/removing items,

        no open violations, and an exact count match with physical cart (R9).
        """
        # 1. No PENDING items
        pending_count = (
            db.query(CartItem)
            .filter(
                CartItem.session_id == session.id,
                CartItem.status == "PENDING",
            )
            .count()
        )
        if pending_count > 0:
            return False, "Cannot checkout: scanned item is still pending placement in cart.", ScanBlockReason.ITEM_PENDING

        # 2. No REMOVING items
        removing_count = (
            db.query(CartItem)
            .filter(
                CartItem.session_id == session.id,
                CartItem.status.in_(["REMOVING", "REMOVED_PENDING_RESCAN"]),
            )
            .count()
        )
        if removing_count > 0:
            return False, "Cannot checkout: item removal is pending confirmation.", ScanBlockReason.ITEM_REMOVING

        # 3. No open violations
        open_alerts = (
            db.query(Alert)
            .filter(
                Alert.session_id == session.id,
                Alert.status == "OPEN",
            )
            .count()
        )
        if open_alerts > 0:
            return False, "Cannot checkout: unresolved security or item alerts remain open.", ScanBlockReason.VIOLATION_OPEN

        # 4. Verified items list count must exactly match camera detected objects count
        verified_items_count = (
            db.query(CartItem)
            .filter(
                CartItem.session_id == session.id,
                CartItem.status == "VERIFIED",
            )
            .count()
        )
        if verified_items_count != detected_objects_count:
            return (
                False,
                f"Cannot checkout: camera sees {detected_objects_count} objects but bill has {verified_items_count} items.",
                ScanBlockReason.VIOLATION_OPEN,
            )

        return True, "Checkout authorized.", None

    # --------------------------------------------------------------------------
    # R10: QUANTITY (SEPARATE ITEMS PER PRODUCT SCAN)
    # --------------------------------------------------------------------------
    @classmethod
    def create_scanned_item(
        cls,
        db: Session,
        session: CartSession,
        product: Product,
    ) -> CartItem:
        """Scanning the same product again creates a separate item (quantity=1)

        with its own stored crop, bounding box, and embedding snapshot (R10).
        """
        unit_price = product.discount_price if product.discount_price else product.price
        item = CartItem(
            session_id=session.id,
            product_id=product.id,
            quantity=1,  # Strict: 1 physical item per record
            unit_price=unit_price,
            status="PENDING",
            scanned_at=datetime.utcnow(),
        )
        db.add(item)
        db.flush()
        return item

    # --------------------------------------------------------------------------
    # SCHEMA READINESS GUARD
    # --------------------------------------------------------------------------
    _schema_readiness_cache: dict[str, Any] = {"ready": None, "checked_at": 0.0, "reason": ""}

    @classmethod
    def check_schema_readiness(cls, db: Session) -> tuple[bool, str]:
        """Verify required migration columns exist before judging writes them.

        Cached for 60 seconds to minimize database reflection overhead.
        """
        import time
        from sqlalchemy import inspect

        now = time.time()
        if cls._schema_readiness_cache["ready"] is not None and (now - cls._schema_readiness_cache["checked_at"] < 60.0):
            return cls._schema_readiness_cache["ready"], cls._schema_readiness_cache["reason"]

        try:
            bind = db.get_bind()
            if bind.dialect.name == "sqlite":
                return True, "Schema ready (sqlite)"
            inspector = inspect(bind)
            required_cols = {
                "cart_items": ["crop_embedding", "bounding_box", "last_known_crop_path"],
                "alerts": ["violation_type", "evidence_path"],
                "cart_sessions": ["cart_empty_verified"],
            }
            for table, cols in required_cols.items():
                existing_cols = {c["name"] for c in inspector.get_columns(table)}
                missing = [c for c in cols if c not in existing_cols]
                if missing:
                    reason = f"Database schema missing columns in table '{table}': {missing}. Migration pending on live database."
                    cls._schema_readiness_cache = {"ready": False, "checked_at": now, "reason": reason}
                    logger.warning(f"Schema readiness check failed: {reason}")
                    return False, reason

            cls._schema_readiness_cache = {"ready": True, "checked_at": now, "reason": "Schema ready"}
            return True, "Schema ready"
        except Exception as e:
            reason = f"Schema check inspection error: {str(e)}"
            cls._schema_readiness_cache = {"ready": False, "checked_at": now, "reason": reason}
            logger.warning(reason)
            return False, reason
