import asyncio
import json
import uuid
import hashlib
import logging
from datetime import datetime
import numpy as np
from typing import Optional, Any, Dict
from fastapi import WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models.cart import Cart
from app.models.session import CartItem, CartSession
from app.models.alert import Alert
from app.models.transaction import AuditLog
from app.websocket.manager import ws_manager
from app.services.session_service import SessionService
import os
import time
from app.config import settings
from app.ai.verification_engine import verification_engine
from app.ai.object_detector import object_detector
from app.ai.feature_extractor import feature_extractor
from app.ai.vector_store import VectorStoreMatcher
from app.services.scan_worker import preprocess_product_image_for_embedding
from app.services.alert_service import AlertService
from app.services.cart_state_machine import (
    BoundingBox,
    CartStateMachine,
    DecisionOutcome,
    DetectedRegion,
    ScanBlockReason,
    StoredItemSnapshot,
    ViolationType,
)
from app.services.device_watchdog import (
    record_device_activity,
    record_device_frame,
    clear_device_activity,
    get_frames_per_minute,
    record_device_close,
    record_judgement_memory,
)

# Concurrency limits: 1 judgement at a time per cart, 1 globally across server
cart_judging_active: set[str] = set()
global_judgement_semaphore = asyncio.Semaphore(1)

try:
    import cv2
    HAS_CV2 = True
except Exception:
    cv2 = None
    HAS_CV2 = False

logger = logging.getLogger("smartcart.device")


def load_persisted_cart_reference(cart_id: str) -> Optional[np.ndarray]:
    """Retrieve persisted empty-cart reference image from disk cache."""
    if not HAS_CV2:
        return None
    try:
        ref_dir = os.path.join(settings.MODELS_DIR, "cart_references")
        ref_path = os.path.join(ref_dir, f"{cart_id}.jpg")
        if os.path.exists(ref_path):
            img = cv2.imread(ref_path)
            if img is not None and img.size > 0:
                return img
    except Exception as e:
        logger.warning(f"Failed to load persisted cart reference for {cart_id}: {e}")
    return None


def save_persisted_cart_reference(cart_id: str, img_bgr: np.ndarray) -> None:
    """Save empty-cart reference image to persistent disk cache across server restarts."""
    if img_bgr is None or not HAS_CV2:
        return
    try:
        ref_dir = os.path.join(settings.MODELS_DIR, "cart_references")
        os.makedirs(ref_dir, exist_ok=True)
        ref_path = os.path.join(ref_dir, f"{cart_id}.jpg")
        cv2.imwrite(ref_path, img_bgr)
    except Exception as e:
        logger.warning(f"Failed to persist cart reference for {cart_id}: {e}")


class CartVisionTracker:
    def __init__(self, cart_id: str):
        self.cart_id = cart_id
        self.hand_in_frame: bool = False
        self.hand_left_time: float = 0.0
        self.hand_activity_marker: bool = False
        self.stable_frame_count: int = 0
        self.stable_start_time: float = 0.0
        self.last_motion_time: float = 0.0
        self.motion_start_time: float = 0.0
        self.last_judged_time: float = 0.0
        self.last_scanned_time: float = 0.0
        self.last_pending_barcode: Optional[str] = None
        self.last_pending_item_id: Optional[str] = None
        self.has_pending_items: bool = False
        self.face_seen_start_time: float = 0.0
        self.ref_background: Optional[np.ndarray] = load_persisted_cart_reference(cart_id)
        self.last_stable_frame: Optional[np.ndarray] = None
        self.recent_traces: list = []

    def add_trace(self, trace: dict):
        if not trace:
            return
        self.recent_traces.insert(0, trace)
        if len(self.recent_traces) > 20:
            self.recent_traces = self.recent_traces[:20]

cart_trackers: Dict[str, CartVisionTracker] = {}

def get_tracker(cart_id: str) -> CartVisionTracker:
    if cart_id not in cart_trackers:
        cart_trackers[cart_id] = CartVisionTracker(cart_id)
    return cart_trackers[cart_id]

def mask_face_regions(img_bgr, face_boxes: list):
    """
    Blurs detected face bounding boxes on the frame before embedding extraction.
    Ensures human face features are heavily obscured while preserving surrounding packaging texture.
    Never stores or persists the unmasked image.
    """
    if img_bgr is None or not face_boxes:
        return img_bgr
    import cv2
    h, w = img_bgr.shape[:2]
    masked = img_bgr.copy()
    for fb in face_boxes:
        bx = int(max(0, fb.get("x", 0) * w))
        by = int(max(0, fb.get("y", 0) * h))
        bw = int(min(w - bx, fb.get("width", 0) * w))
        bh = int(min(h - by, fb.get("height", 0) * h))
        if bw > 2 and bh > 2:
            sub = masked[by:by+bh, bx:bx+bw]
            ksize = max(15, (min(bw, bh) // 2) * 2 + 1)
            blurred = cv2.GaussianBlur(sub, (ksize, ksize), 30)
            masked[by:by+bh, bx:bx+bw] = blurred
    return masked


def _run_sync_judgement(
    cart_id: str,
    cart_number: str,
    session_id: str,
    img_bgr: np.ndarray,
    ref_background: Optional[np.ndarray],
    hand_was_present: bool,
    motion_sec: float,
    now: float,
    time_since_scan: float,
    grace_period: float,
    db_bind: Any = None,
) -> dict:
    """Worker thread function executing heavy vision inference and verification.

    Performs:
      - Memory profiling and bounds tracking (RSS MB peak)
      - Database schema readiness check before writing migration columns (R8)
      - Contour / difference object detection
      - PIL preprocessing and ONNX INT8 CLIP feature extraction
      - Vector store cosine similarity lookup
      - Hungarian bipartite state matching (R4)
      - Evidence snapshot generation and disk write
      - DB status updates and transaction commit
    """
    import psutil
    import gc
    proc = psutil.Process()
    try:
        rss_start = proc.memory_info().rss / (1024 * 1024)
        record_judgement_memory(rss_start, active=True)
    except Exception:
        pass

    db = Session(bind=db_bind) if db_bind is not None else SessionLocal()
    broadcasts = []
    websocket_messages = []
    trace_data = None
    item_verified = False

    try:
        # 1. Schema readiness guard (R8)
        schema_ok, schema_msg = CartStateMachine.check_schema_readiness(db)
        if not schema_ok:
            logger.warning(f"[{cart_number}] Judging paused: {schema_msg}")
            return {
                "status": "SCHEMA_ERROR",
                "message": schema_msg,
                "broadcasts": [],
                "websocket_messages": [{
                    "type": "frame_ack",
                    "status": "SCHEMA_MIGRATION_PAUSED",
                    "message": schema_msg
                }],
                "trace_data": None
            }

        active_session = db.query(CartSession).filter(CartSession.id == session_id).first()
        if not active_session:
            return {"status": "NO_SESSION", "broadcasts": [], "websocket_messages": [], "trace_data": None}

        verified_items = db.query(CartItem).join(CartItem.product).filter(
            CartItem.session_id == active_session.id,
            CartItem.status.in_(["VERIFIED", "REMOVING"])
        ).all()

        stored_items: list[StoredItemSnapshot] = []
        for itm in verified_items:
            emb = json.loads(itm.crop_embedding) if itm.crop_embedding else None
            box_dict = json.loads(itm.bounding_box) if itm.bounding_box else {}
            box = BoundingBox.from_dict(box_dict) if box_dict else BoundingBox(0, 0, 0, 0)
            if emb:
                stored_items.append(StoredItemSnapshot(
                    item_id=itm.id,
                    product_id=itm.product_id,
                    product_name=itm.product.name,
                    barcode=itm.product.barcode,
                    crop_embedding=emb,
                    bounding_box=box,
                    last_known_crop_path=itm.last_known_crop_path,
                    verified_at=itm.verified_at.isoformat() if itm.verified_at else ""
                ))

        pending_item = db.query(CartItem).join(CartItem.product).filter(
            CartItem.session_id == active_session.id,
            CartItem.status == "PENDING",
            CartItem.staff_approved.is_(False)
        ).order_by(CartItem.scanned_at.desc()).first()

        has_pending = pending_item is not None

        # 2. Detect ALL objects
        h_frame, w_frame = img_bgr.shape[:2]
        detected_boxes = object_detector.detect_all_objects(ref_background, img_bgr)
        if not detected_boxes:
            mb = object_detector.compute_motion_box(ref_background, img_bgr)
            if mb:
                detected_boxes = [mb]

        detected_regions: list[DetectedRegion] = []
        for idx, dbox in enumerate(detected_boxes):
            x1, y1, x2, y2 = dbox
            norm_box = BoundingBox(
                x=round(x1 / w_frame, 4),
                y=round(y1 / h_frame, 4),
                width=round((x2 - x1) / w_frame, 4),
                height=round((y2 - y1) / h_frame, 4)
            )
            crop_pil = object_detector.crop_object(img_bgr, dbox)
            preprocessed_crop = preprocess_product_image_for_embedding(crop_pil)
            reg_emb = feature_extractor.get_embedding(preprocessed_crop)
            # Free cropped memory immediately to minimize peak RSS
            del crop_pil, preprocessed_crop
            detected_regions.append(DetectedRegion(
                region_id=f"reg_{idx}_{int(now * 1000)}",
                bounding_box=norm_box,
                embedding=reg_emb,
                confidence=1.0,
            ))

        # 3. State Machine Multi-Object Matching (R4)
        full_match = CartStateMachine.run_full_match(
            stored_items=stored_items,
            detected_regions=detected_regions,
            has_pending_item=has_pending,
            hand_activity_occurred=hand_was_present,
            unstable_motion_seconds=motion_sec
        )

        for stored_snap, det_reg, sim in full_match.matched_pairs:
            for itm in verified_items:
                if itm.id == stored_snap.item_id:
                    itm.bounding_box = json.dumps(det_reg.bounding_box.to_dict())
        db.commit()

        if full_match.requires_staff_check:
            al = Alert(
                session_id=active_session.id,
                cart_id=cart_id,
                alert_type="NEEDS_STAFF_CHECK",
                message=full_match.staff_reason or "Staff check required.",
                severity="MEDIUM",
                status="OPEN"
            )
            db.add(al)
            db.commit()
            websocket_messages.append({
                "type": "verification_result",
                "action": "ESCALATE_ADMIN_REVIEW",
                "message": full_match.staff_reason
            })
            return {
                "status": "STAFF_CHECK",
                "broadcasts": broadcasts,
                "websocket_messages": websocket_messages,
                "trace_data": None
            }

        # 4. Handle Unmatched Items (Removal Events - R4.b, R5, R7)
        for missing_snap in full_match.unmatched_items:
            matched_itm = next((i for i in verified_items if i.id == missing_snap.item_id), None)
            if matched_itm and matched_itm.status == "REMOVING":
                CartStateMachine.confirm_removal(db, matched_itm, stored_items, detected_regions)
                broadcasts.append({
                    "channel": "cart",
                    "event": "ITEM_REMOVED",
                    "data": {
                        "item_id": matched_itm.id,
                        "product_name": matched_itm.product.name,
                        "barcode": matched_itm.product.barcode,
                        "status": "REMOVED",
                        "subtotal": active_session.subtotal_amount,
                        "total": active_session.total_amount,
                        "message": f"'{matched_itm.product.name}' removed from cart."
                    }
                })
                websocket_messages.append({
                    "type": "verification_result",
                    "action": "ITEM_REMOVED",
                    "product_name": matched_itm.product.name,
                    "status": "REMOVED"
                })
            elif matched_itm and matched_itm.status == "VERIFIED":
                missing_item, missing_conf, top_cands = CartStateMachine.identify_missing_item(
                    stored_items=stored_items,
                    detected_regions=detected_regions
                )
                ev_url = object_detector.save_evidence_snapshot(img_bgr, status="UNAUTHORIZED_REMOVE")
                alert_msg = f"This item appears to have been removed: {missing_snap.product_name}"
                v_alert = CartStateMachine.record_violation(
                    db=db,
                    session_id=active_session.id,
                    cart_id=cart_id,
                    violation_type=ViolationType.UNAUTHORIZED_REMOVE,
                    message=alert_msg,
                    evidence_path=ev_url,
                    item_id=missing_snap.item_id
                )
                if v_alert and missing_conf < 0.65 and top_cands:
                    from app.models.alert import ReviewCase
                    existing_case = db.query(ReviewCase).filter(ReviewCase.alert_id == v_alert.id).first()
                    if not existing_case:
                        rc = ReviewCase(
                            alert_id=v_alert.id,
                            cart_id=cart_id,
                            confidence=missing_conf,
                            evidence_image_url=ev_url or (missing_snap.last_known_crop_path or ""),
                            top_candidates_json=json.dumps([{
                                "item_id": c["item_id"],
                                "product_name": c["product_name"],
                                "missing_confidence": c["missing_confidence"]
                            } for c in top_cands]),
                            status="PENDING"
                        )
                        db.add(rc)
                        db.commit()

                if v_alert:
                    broadcasts.append({
                        "channel": "admin",
                        "event": "NEW_INCIDENT_ALERT",
                        "data": {
                            "id": v_alert.id,
                            "cart_id": cart_id,
                            "cart_number": cart_number,
                            "session_id": active_session.id,
                            "alert_type": "UNAUTHORIZED_REMOVE",
                            "violation_type": "UNAUTHORIZED_REMOVE",
                            "severity": "HIGH",
                            "message": alert_msg,
                            "item_id": missing_snap.item_id,
                            "product_name": missing_snap.product_name,
                            "confidence": missing_conf,
                            "last_known_image": missing_snap.last_known_crop_path,
                            "evidence_snapshot_url": ev_url,
                            "requires_staff_review": missing_conf < 0.65,
                            "top_candidates": top_cands if missing_conf < 0.65 else None,
                            "created_at": v_alert.created_at.isoformat()
                        }
                    })

                broadcasts.append({
                    "channel": "cart",
                    "event": "ITEM_REMOVAL_DETECTED",
                    "data": {
                        "message": alert_msg,
                        "item_id": missing_snap.item_id,
                        "product_name": missing_snap.product_name,
                        "confidence": missing_conf,
                        "last_known_image": missing_snap.last_known_crop_path,
                        "current_evidence": ev_url,
                        "top_candidates": top_cands if missing_conf < 0.65 else None
                    }
                })
                websocket_messages.append({
                    "type": "verification_result",
                    "action": "UNAUTHORIZED_REMOVE_DETECTED",
                    "product_name": missing_snap.product_name,
                    "confidence": missing_conf
                })

        # 5. R8: Automatic clearance when cart view matches scanned list
        if not full_match.unmatched_items and not full_match.unmatched_objects and not has_pending:
            open_violations = (
                db.query(Alert)
                .filter(
                    Alert.session_id == active_session.id,
                    Alert.status == "OPEN",
                    Alert.violation_type.in_([
                        ViolationType.UNSCANNED_ADD.value,
                        ViolationType.UNAUTHORIZED_REMOVE.value,
                        ViolationType.CART_NOT_EMPTY_AT_START.value,
                    ]),
                )
                .all()
            )
            for ov in open_violations:
                ov.status = "RESOLVED"
                ov.resolved_at = datetime.utcnow()
                ov.resolution_notes = "Auto-cleared: cart items match scanned list over stable frame"
                db.commit()
                broadcasts.append({
                    "channel": "cart",
                    "event": "ALERT_CLEARED",
                    "data": {
                        "alert_id": ov.id,
                        "alert_type": ov.alert_type,
                        "violation_type": ov.violation_type,
                        "message": "Cart items match your scanned list."
                    }
                })
                broadcasts.append({
                    "channel": "admin",
                    "event": "ALERT_RESOLVED",
                    "data": {
                        "alert_id": ov.id,
                        "cart_id": cart_id,
                        "status": "RESOLVED",
                        "reason": "Auto-cleared: cart items match scanned list"
                    }
                })

        # 6. Handle Unmatched Objects (Add Events - R3 & R4.a)
        if full_match.unmatched_objects:
            if pending_item:
                target_barcode = pending_item.product.barcode
                target_region = full_match.unmatched_objects[0]

                nearest_prods = VectorStoreMatcher.find_nearest_product(db, target_region.embedding, top_k=3)
                scanned_score = 0.0
                runner_up_score = 0.0
                runner_up_name = None

                for cand in nearest_prods:
                    if cand.get("barcode") == target_barcode:
                        scanned_score = max(scanned_score, float(cand.get("similarity", 0.0)))
                    else:
                        if float(cand.get("similarity", 0.0)) > runner_up_score:
                            runner_up_score = float(cand.get("similarity", 0.0))
                            runner_up_name = cand.get("product_name")

                outcome, reason_text, margin = CartStateMachine.evaluate_placement(
                    scanned_product_score=scanned_score,
                    runner_up_score=runner_up_score,
                    runner_up_product_name=runner_up_name,
                    face_detected=False
                )

                norm_b = target_region.bounding_box
                pixel_box = (
                    int(norm_b.x * w_frame),
                    int(norm_b.y * h_frame),
                    int((norm_b.x + norm_b.width) * w_frame),
                    int((norm_b.y + norm_b.height) * h_frame)
                )
                evidence_url = object_detector.save_evidence_snapshot(
                    image_bgr=img_bgr,
                    box=pixel_box,
                    label=f"{pending_item.product.name} ({scanned_score * 100:.1f}%)",
                    status="SUCCESS" if outcome == DecisionOutcome.VERIFIED else "UNCERTAIN"
                )

                if outcome == DecisionOutcome.VERIFIED:
                    item_verified = True
                    CartStateMachine.create_item_snapshot(
                        item=pending_item,
                        crop_embedding=target_region.embedding,
                        box=target_region.bounding_box,
                        crop_path=evidence_url
                    )
                    pending_item.status = "VERIFIED"
                    pending_item.verified_at = datetime.utcnow()
                    pending_item.confidence_score = scanned_score
                    pending_item.verification_evidence_url = evidence_url
                    SessionService.recalculate_session_totals(db, active_session)

                    # Auto-clear open alerts
                    open_alerts = db.query(Alert).filter(
                        Alert.session_id == active_session.id,
                        (Alert.alert_type.in_(["UNSCANNED_ITEM", "NEEDS_STAFF_CHECK", "FACE_IN_PACKAGING_WITHHELD", "MISMATCH_ITEM"])) |
                        (Alert.violation_type.in_([ViolationType.UNSCANNED_ADD.value, ViolationType.WRONG_ITEM_REMOVED.value])),
                        Alert.status == "OPEN"
                    ).all()
                    for al in open_alerts:
                        al.status = "RESOLVED"
                        al.resolution_notes = f"Auto-cleared: item verified as '{pending_item.product.name}'."
                        al.resolved_at = datetime.utcnow()
                        broadcasts.append({
                            "channel": "cart",
                            "event": "ALERT_CLEARED",
                            "data": {
                                "alert_type": al.alert_type,
                                "item_id": pending_item.id,
                                "message": f"Alert cleared: item verified as '{pending_item.product.name}'."
                            }
                        })
                    db.commit()

                    websocket_messages.append({
                        "type": "verification_result",
                        "action": "ITEM_VERIFIED",
                        "product_name": pending_item.product.name,
                        "barcode": target_barcode,
                        "confidence": scanned_score,
                        "evidence_url": evidence_url
                    })
                    broadcasts.append({
                        "channel": "cart",
                        "event": "ITEM_VERIFIED",
                        "data": {
                            "item_id": pending_item.id,
                            "product_name": pending_item.product.name,
                            "barcode": target_barcode,
                            "confidence": scanned_score,
                            "evidence_url": evidence_url,
                            "status": "VERIFIED",
                            "subtotal": active_session.subtotal_amount,
                            "total": active_session.total_amount
                        }
                    })

                elif outcome == DecisionOutcome.REPOSITION:
                    pending_item.status = "WARNING"
                    pending_item.warning_reason = "REPOSITION"
                    pending_item.confidence_score = scanned_score
                    pending_item.verification_evidence_url = evidence_url
                    db.commit()
                    broadcasts.append({
                        "channel": "cart",
                        "event": "ITEM_WARNING",
                        "data": {
                            "item_id": pending_item.id,
                            "product_name": pending_item.product.name,
                            "barcode": target_barcode,
                            "status": "WARNING",
                            "reason": "REPOSITION",
                            "message": reason_text
                        }
                    })
                    websocket_messages.append({
                        "type": "verification_result",
                        "action": "UNCERTAIN_REPOSITION",
                        "product_name": pending_item.product.name,
                        "confidence": scanned_score,
                        "message": reason_text
                    })

                elif outcome == DecisionOutcome.WRONG_ITEM:
                    pending_item.status = "WARNING"
                    pending_item.warning_reason = "MISMATCH"
                    pending_item.confidence_score = scanned_score
                    pending_item.verification_evidence_url = evidence_url
                    db.commit()
                    w_alert = CartStateMachine.record_violation(
                        db=db,
                        session_id=active_session.id,
                        cart_id=cart_id,
                        violation_type=ViolationType.WRONG_ITEM_REMOVED,
                        message=reason_text,
                        evidence_path=evidence_url,
                        item_id=pending_item.id
                    )
                    if w_alert:
                        broadcasts.append({
                            "channel": "admin",
                            "event": "NEW_INCIDENT_ALERT",
                            "data": {
                                "id": w_alert.id,
                                "cart_id": cart_id,
                                "cart_number": cart_number,
                                "session_id": active_session.id,
                                "alert_type": "WRONG_ITEM_REMOVED",
                                "violation_type": "WRONG_ITEM_REMOVED",
                                "severity": "HIGH",
                                "message": reason_text,
                                "evidence_snapshot_url": evidence_url,
                                "item_id": pending_item.id,
                                "product_name": pending_item.product.name,
                                "created_at": w_alert.created_at.isoformat()
                            }
                        })
                    broadcasts.append({
                        "channel": "cart",
                        "event": "ITEM_WARNING",
                        "data": {
                            "item_id": pending_item.id,
                            "product_name": pending_item.product.name,
                            "barcode": target_barcode,
                            "status": "WARNING",
                            "reason": "MISMATCH",
                            "detected_as": runner_up_name,
                            "message": reason_text
                        }
                    })
                    websocket_messages.append({
                        "type": "verification_result",
                        "action": "ITEM_MISMATCH",
                        "scanned_barcode": target_barcode,
                        "detected_as": runner_up_name,
                        "confidence": scanned_score
                    })

                else:  # REVIEW
                    pending_item.status = "NEEDS_STAFF_CHECK"
                    pending_item.warning_reason = "LOW_CONFIDENCE"
                    pending_item.confidence_score = scanned_score
                    pending_item.verification_evidence_url = evidence_url
                    db.commit()
                    al = Alert(
                        session_id=active_session.id,
                        cart_id=cart_id,
                        item_id=pending_item.id,
                        alert_type="NEEDS_STAFF_CHECK",
                        message=reason_text,
                        severity="MEDIUM",
                        status="OPEN",
                        evidence_path=evidence_url
                    )
                    db.add(al)
                    db.commit()
                    broadcasts.append({
                        "channel": "cart",
                        "event": "ITEM_WARNING",
                        "data": {
                            "item_id": pending_item.id,
                            "product_name": pending_item.product.name,
                            "barcode": target_barcode,
                            "status": "NEEDS_STAFF_CHECK",
                            "reason": "LOW_CONFIDENCE",
                            "message": reason_text
                        }
                    })
                    websocket_messages.append({
                        "type": "verification_result",
                        "action": "ESCALATE_ADMIN_REVIEW",
                        "product_name": pending_item.product.name,
                        "confidence": scanned_score
                    })

                trace_data = {
                    "id": str(uuid.uuid4()),
                    "cart_id": cart_id,
                    "cart_number": cart_number,
                    "session_id": active_session.id,
                    "item_id": pending_item.id if pending_item else None,
                    "pending_items": [{"id": pending_item.id, "barcode": target_barcode, "product_name": pending_item.product.name}] if pending_item else [],
                    "unscanned_alert_reason": f"N/A (Pending item evaluated: {pending_item.product.name} [{target_barcode}])" if pending_item else None,
                    "timestamp": datetime.utcnow().isoformat(),
                    "frame_received_time": datetime.utcnow().isoformat(),
                    "camera_online": True,
                    "empty_reference_present": ref_background is not None,
                    "hand_present": False,
                    "face_present": False,
                    "frame_stable": True,
                    "score_scanned": scanned_score,
                    "scanned_product_name": pending_item.product.name if pending_item else None,
                    "scanned_barcode": target_barcode if pending_item else None,
                    "decision": outcome.value if hasattr(outcome, "value") else str(outcome),
                    "reason_text": reason_text,
                    "evidence_url": evidence_url,
                    "sent_to_shopper": True,
                }

            else:
                # No pending item: grace check
                if time_since_scan < grace_period:
                    websocket_messages.append({
                        "type": "vision_status",
                        "status": "AWAITING_PLACEMENT",
                        "message": f"Grace period active ({time_since_scan:.1f}s / {grace_period:.1f}s). Waiting for scanned item placement."
                    })
                    return {
                        "status": "GRACE_ACTIVE",
                        "broadcasts": broadcasts,
                        "websocket_messages": websocket_messages,
                        "trace_data": None
                    }

                target_region = full_match.unmatched_objects[0]
                norm_b = target_region.bounding_box
                pixel_box = (
                    int(norm_b.x * w_frame),
                    int(norm_b.y * h_frame),
                    int((norm_b.x + norm_b.width) * w_frame),
                    int((norm_b.y + norm_b.height) * h_frame)
                )
                ev_url = object_detector.save_evidence_snapshot(
                    image_bgr=img_bgr,
                    box=pixel_box,
                    status="UNSCANNED_ADD"
                )
                nearest = VectorStoreMatcher.find_nearest_product(db, target_region.embedding, top_k=1)
                pred_name = nearest[0]["product_name"] if nearest else "Unscanned item"

                u_alert = CartStateMachine.record_violation(
                    db=db,
                    session_id=active_session.id,
                    cart_id=cart_id,
                    violation_type=ViolationType.UNSCANNED_ADD,
                    message=f"Unscanned item placed in cart: {pred_name}",
                    evidence_path=ev_url
                )
                if u_alert:
                    broadcasts.append({
                        "channel": "admin",
                        "event": "NEW_INCIDENT_ALERT",
                        "data": {
                            "id": u_alert.id,
                            "cart_id": cart_id,
                            "cart_number": cart_number,
                            "session_id": active_session.id,
                            "alert_type": "UNSCANNED_ITEM",
                            "violation_type": "UNSCANNED_ADD",
                            "severity": "HIGH",
                            "message": f"Unscanned item placed in cart: {pred_name}",
                            "evidence_snapshot_url": ev_url,
                            "created_at": u_alert.created_at.isoformat()
                        }
                    })
                broadcasts.append({
                    "channel": "cart",
                    "event": "UNSCANNED_ITEM_DETECTED",
                    "data": {
                        "message": "We noticed an item that wasn't scanned. Please scan its barcode.",
                        "detected_name": pred_name
                    }
                })
                unscanned_reason = f"No pending items found and grace period expired ({time_since_scan:.1f}s >= {grace_period:.1f}s)."
                trace_data = {
                    "id": str(uuid.uuid4()),
                    "cart_id": cart_id,
                    "cart_number": cart_number,
                    "session_id": active_session.id,
                    "pending_items": [],
                    "unscanned_alert_reason": unscanned_reason,
                    "timestamp": datetime.utcnow().isoformat(),
                    "frame_received_time": datetime.utcnow().isoformat(),
                    "camera_online": True,
                    "empty_reference_present": ref_background is not None,
                    "hand_present": False,
                    "face_present": False,
                    "frame_stable": True,
                    "decision": "UNSCANNED_DETECTED",
                    "reason_text": f"Unscanned item placed in cart: {pred_name}",
                    "evidence_url": ev_url,
                    "sent_to_shopper": True,
                }
                websocket_messages.append({
                    "type": "verification_result",
                    "action": "UNSCANNED_ITEM_DETECTED",
                    "detected_as": pred_name,
                    "confidence": nearest[0]["similarity"] if nearest else 0.88
                })
        else:
            websocket_messages.append({
                "type": "frame_ack",
                "status": "VERIFIED_ALL",
                "message": "Basket is steady."
            })

        db.commit()
        return {
            "status": "SUCCESS",
            "broadcasts": broadcasts,
            "websocket_messages": websocket_messages,
            "trace_data": trace_data,
            "item_verified": item_verified
        }

    except Exception as e:
        logger.error(f"[{cart_number}] Synchronous judgement worker failed: {e}", exc_info=True)
        return {
            "status": "ERROR",
            "message": str(e),
            "broadcasts": [],
            "websocket_messages": [{
                "type": "frame_error",
                "stage": "worker_judgement",
                "message": str(e)
            }],
            "trace_data": None
        }
    finally:
        try:
            rss_peak = proc.memory_info().rss / (1024 * 1024)
            record_judgement_memory(rss_peak, active=False)
        except Exception:
            pass
        db.close()
        gc.collect()


async def process_camera_frame(
    db: Optional[Session],
    cart_id: str,
    cart_number: str,
    image_data: Any,
    websocket: WebSocket,
    hand_present: bool = False,
    face_present: bool = False,
    motion: bool = False,
    face_boxes: Optional[list] = None,
    detector_profile: str = "privacy"
):
    """
    Process incoming camera frame from cart device using CartStateMachine (Phase 2).
    Implements:
      - Privacy-first face gate: frames with human faces are never stored; withheld for privacy.
      - Stable-frame logic: ignores motion bursts and hand presence; tracks long motion (>20s prompt, >60s staff check).
      - Hand-tracking activity marker: setting marker when hand enters, running full match upon departure.
      - R1: Empty start verification against calibration reference.
      - R4: Full Multi-Object Match detecting all regions (same preprocessing as enrollment).
      - R3: Placement evaluation with margin check and cart-state memory snapshots.
      - R5 & R7: Removal flow and missing item identification against stored cart state.
      - R6: Violation recording with evidence retention.
    """
    close_db_when_done = False
    if db is None:
        db = SessionLocal()
        close_db_when_done = True

    try:
        try:
            db.expire_all()
        except Exception:
            pass

        tracker = get_tracker(cart_id)
        now = time.time()

        # 1. PRIVACY CHECK: Faces on Packaging or in Frame
        face_on_packaging_mode = getattr(settings, "FACE_ON_PACKAGING_MODE", "withhold").lower()
        if face_present:
            if tracker.face_seen_start_time == 0.0:
                tracker.face_seen_start_time = now
            tracker.stable_frame_count = 0
            tracker.stable_start_time = 0.0

            active_session = SessionService.ensure_single_active_session(db, cart_id)
            pending_item = None
            if active_session:
                pending_item = db.query(CartItem).join(CartItem.product).filter(
                    CartItem.session_id == active_session.id,
                    CartItem.status.in_(["PENDING", "NEEDS_STAFF_CHECK"]),
                    CartItem.staff_approved.is_(False)
                ).order_by(CartItem.scanned_at.desc()).first()

            if face_on_packaging_mode == "mask_and_judge" and image_data and not hand_present and not motion:
                try:
                    img_bgr, _ = verification_engine._decode_to_cv2(image_data)
                    masked_bgr = mask_face_regions(img_bgr, face_boxes or [])
                    image_data = masked_bgr
                except Exception as ex:
                    logger.warning(f"Failed to mask face region: {ex}")
            else:
                if (now - tracker.face_seen_start_time) >= 1.0 and active_session and pending_item:
                    pending_item.status = "NEEDS_STAFF_CHECK"
                    pending_item.warning_reason = "FACE_DETECTED"
                    db.commit()

                    await ws_manager.broadcast_to_cart(cart_id, "ITEM_WARNING", {
                        "item_id": pending_item.id,
                        "product_name": pending_item.product.name,
                        "barcode": pending_item.product.barcode,
                        "status": "NEEDS_STAFF_CHECK",
                        "reason": "FACE_DETECTED",
                        "message": "We can't check this item automatically. Please ask staff. (Please hold the cover/barcode toward the camera.)"
                    })

                    await AlertService.create_alert(
                        db=db,
                        cart_id=cart_id,
                        session_id=active_session.id,
                        item_id=pending_item.id,
                        alert_type="NEEDS_STAFF_CHECK",
                        severity="MEDIUM",
                        message="We can't check this item automatically. Please ask staff.",
                        evidence_url=None,
                        create_review_case=True,
                        scanned_barcode=pending_item.product.barcode,
                        confidence=0.0
                    )

                first_box = face_boxes[0] if (face_boxes and len(face_boxes) > 0) else None
                box_coords = None
                face_conf = None
                box_size_pct = None
                if first_box:
                    box_coords = [
                        round(first_box.get("y", 0), 3),
                        round(first_box.get("x", 0), 3),
                        round(first_box.get("y", 0) + first_box.get("height", 0), 3),
                        round(first_box.get("x", 0) + first_box.get("width", 0), 3)
                    ]
                    face_conf = first_box.get("score")
                    box_size_pct = round((first_box.get("areaFraction") or (first_box.get("width", 0) * first_box.get("height", 0))) * 100, 2)

                trace_data = {
                    "id": str(uuid.uuid4()),
                    "cart_id": cart_id,
                    "cart_number": cart_number,
                    "session_id": active_session.id if active_session else None,
                    "item_id": pending_item.id if (active_session and pending_item) else None,
                    "timestamp": datetime.utcnow().isoformat(),
                    "frame_received_time": datetime.utcnow().isoformat(),
                    "camera_online": True,
                    "empty_reference_present": tracker.ref_background is not None,
                    "hand_present": hand_present,
                    "face_present": True,
                    "face_box": box_coords,
                    "face_confidence": face_conf,
                    "face_box_size_percent": box_size_pct,
                    "detector_profile": detector_profile,
                    "frame_stable": not motion,
                    "stable_seconds": round(max(0.0, now - tracker.face_seen_start_time), 1),
                    "crop_status": "withheld",
                    "crop_withheld_reason": "Human face detected in camera view (Privacy Protection Policy)",
                    "decision": "FACE_DETECTED_WITHHELD",
                    "reason_text": "Frame withheld: face detected in camera view.",
                    "stopped_at": "face_present",
                    "sent_to_shopper": bool(active_session and pending_item)
                }
                tracker.add_trace(trace_data)

                await websocket.send_json({
                    "type": "frame_ack",
                    "status": "FACE_REDACTED",
                    "message": "Face detected. Frame withheld for privacy."
                })
                return

        tracker.face_seen_start_time = 0.0

        # 2. Hand Occlusion & Motion Tracking Gate (R4)
        if hand_present:
            tracker.hand_activity_marker = True
            tracker.hand_in_frame = True

        if motion:
            if tracker.motion_start_time == 0.0:
                tracker.motion_start_time = now
            tracker.last_motion_time = now
            motion_dur = now - tracker.motion_start_time
            if motion_dur > CartStateMachine.MOTION_WARNING_SECONDS:
                await ws_manager.broadcast_to_cart(cart_id, "CART_MOTION_WARNING", {
                    "message": "Please keep the cart still for a moment."
                })
            if motion_dur > CartStateMachine.MOTION_ESCALATE_SECONDS:
                active_session_tmp = SessionService.ensure_single_active_session(db, cart_id)
                await AlertService.create_alert(
                    db=db,
                    cart_id=cart_id,
                    session_id=active_session_tmp.id if active_session_tmp else None,
                    alert_type="NEEDS_STAFF_CHECK",
                    message="Cart motion unstable for > 60 seconds. Staff inspection required.",
                    severity="MEDIUM"
                )
        else:
            tracker.motion_start_time = 0.0

        if hand_present or motion:
            tracker.stable_frame_count = 0
            tracker.stable_start_time = 0.0
            status_text = "HAND_IN_FRAME" if hand_present else "MOTION_DETECTED"
            msg_text = "Hand in frame: item placement in progress..." if hand_present else "Cart motion: waiting for basket to steady..."
            await websocket.send_json({
                "type": "vision_status",
                "status": status_text,
                "message": msg_text
            })
            return

        # 3. Stabilization Gate: Frame must be steady for ~1 second (R3 & R4)
        if tracker.stable_start_time == 0.0:
            tracker.stable_start_time = now
        tracker.stable_frame_count += 1
        duration_stable = now - tracker.stable_start_time

        if duration_stable < CartStateMachine.PLACEMENT_STABLE_SECONDS or tracker.stable_frame_count < 2:
            await websocket.send_json({
                "type": "vision_status",
                "status": "STABILIZING",
                "message": "Stabilizing basket image..."
            })
            return

        # Decode stable frame
        img_bgr, pil_full = verification_engine._decode_to_cv2(image_data)
        tracker.last_stable_frame = img_bgr.copy()
        h_frame, w_frame = img_bgr.shape[:2]

        # 4. Check active session on this cart (enforces single active session per cart)
        active_session = SessionService.ensure_single_active_session(db, cart_id)

        if tracker.ref_background is None:
            tracker.ref_background = load_persisted_cart_reference(cart_id)

        if not active_session:
            if tracker.ref_background is None:
                tracker.ref_background = img_bgr.copy()
                save_persisted_cart_reference(cart_id, img_bgr)
            await websocket.send_json({
                "type": "frame_ack",
                "status": "IDLE",
                "message": "Cart is currently idle (no active shopper session)."
            })
            return

        # Auto-initialize empty-cart reference from first stable frame of session with no items
        active_items_count = db.query(CartItem).filter(
            CartItem.session_id == active_session.id,
            CartItem.status != "REMOVED"
        ).count()
        if active_items_count == 0 and tracker.ref_background is None:
            tracker.ref_background = img_bgr.copy()
            save_persisted_cart_reference(cart_id, img_bgr)
            logger.info(f"[{cart_number}] Empty cart reference auto-initialized from first stable frame.")

        # 5. R1: Empty Start Check if not verified
        if not active_session.cart_empty_verified and active_items_count == 0:
            diff_val = 0.0
            if HAS_CV2 and tracker.ref_background is not None:
                ref_res = cv2.resize(tracker.ref_background, (w_frame, h_frame))
                diff_val = float(np.mean(cv2.absdiff(ref_res, img_bgr)) / 255.0)

            detected_empty_objs = object_detector.detect_all_objects(tracker.ref_background, img_bgr)
            is_empty, empty_msg, block_reason = CartStateMachine.evaluate_empty_start(
                camera_online=True,
                has_reference=tracker.ref_background is not None,
                diff_from_ref=diff_val,
                stable_seconds=duration_stable,
                hand_present=hand_present,
                face_present=face_present,
                detected_objects_count=len(detected_empty_objs)
            )
            if is_empty:
                active_session.cart_empty_verified = True
                db.commit()
                # Clear any open CART_NOT_EMPTY_AT_START alert
                open_empty_alerts = db.query(Alert).filter(
                    Alert.session_id == active_session.id,
                    Alert.violation_type == ViolationType.CART_NOT_EMPTY_AT_START.value,
                    Alert.status == "OPEN"
                ).all()
                for al in open_empty_alerts:
                    al.status = "RESOLVED"
                    al.resolved_at = datetime.utcnow()
                    al.resolution_notes = "Cart confirmed empty by camera."
                db.commit()
                await ws_manager.broadcast_to_cart(cart_id, "CART_EMPTY_VERIFIED", {
                    "message": "Cart verified empty. Ready to scan items."
                })
            else:
                if block_reason == ScanBlockReason.CART_NOT_EMPTY:
                    v_alert = CartStateMachine.record_violation(
                        db=db,
                        session_id=active_session.id,
                        cart_id=cart_id,
                        violation_type=ViolationType.CART_NOT_EMPTY_AT_START,
                        message=empty_msg
                    )
                    if v_alert:
                        await ws_manager.broadcast_to_admin("NEW_INCIDENT_ALERT", {
                            "id": v_alert.id,
                            "cart_id": cart_id,
                            "cart_number": cart_number,
                            "session_id": active_session.id,
                            "alert_type": "CART_NOT_EMPTY_AT_START",
                            "violation_type": "CART_NOT_EMPTY_AT_START",
                            "severity": "HIGH",
                            "message": empty_msg,
                            "created_at": v_alert.created_at.isoformat()
                        })
                    await ws_manager.broadcast_to_cart(cart_id, "CART_NOT_EMPTY", {
                        "message": "Please empty the cart. Remove any items inside before scanning."
                    })
                await websocket.send_json({
                    "type": "vision_status",
                    "status": "CART_NOT_EMPTY",
                    "message": empty_msg
                })
                return

        # 6. Load Verified Items for Cart-State Memory (R3 & R4)
        verified_items = db.query(CartItem).join(CartItem.product).filter(
            CartItem.session_id == active_session.id,
            CartItem.status.in_(["VERIFIED", "REMOVING"])
        ).all()

        stored_items: list[StoredItemSnapshot] = []
        for itm in verified_items:
            emb = json.loads(itm.crop_embedding) if itm.crop_embedding else None
            box_dict = json.loads(itm.bounding_box) if itm.bounding_box else {}
            box = BoundingBox.from_dict(box_dict) if box_dict else BoundingBox(0, 0, 0, 0)
            if emb:
                stored_items.append(StoredItemSnapshot(
                    item_id=itm.id,
                    product_id=itm.product_id,
                    product_name=itm.product.name,
                    barcode=itm.product.barcode,
                    crop_embedding=emb,
                    bounding_box=box,
                    last_known_crop_path=itm.last_known_crop_path,
                    verified_at=itm.verified_at.isoformat() if itm.verified_at else ""
                ))

        # Check for pending item scanned on mobile
        pending_item = db.query(CartItem).join(CartItem.product).filter(
            CartItem.session_id == active_session.id,
            CartItem.status == "PENDING",
            CartItem.staff_approved.is_(False)
        ).order_by(CartItem.scanned_at.desc()).first()

        has_pending = pending_item is not None
        tracker.has_pending_items = has_pending
        if pending_item:
            tracker.last_pending_item_id = pending_item.id
            tracker.last_pending_barcode = pending_item.product.barcode

        # Evaluation eligibility rules (R4):
        # Full match is executed when:
        # A) PENDING item exists (wait for steady placement)
        # B) REMOVING item exists (confirm departure)
        # C) Hand was inside cart and left (R4 hand-activity marker)
        # D) Physical motion occurred since last judgement
        # E) Periodic match check every 2.0s
        should_evaluate = (
            has_pending or
            len(verified_items) > 0 or
            tracker.hand_activity_marker or
            (tracker.last_motion_time > tracker.last_judged_time) or
            (now - tracker.last_judged_time) >= 2.0
        )

        if not should_evaluate:
            await websocket.send_json({
                "type": "frame_ack",
                "status": "VERIFIED_ALL",
                "message": "Basket is steady."
            })
            return

        if cart_id in cart_judging_active:
            await websocket.send_json({
                "type": "frame_ack",
                "status": "BUSY_SKIPPED",
                "message": "Cart judgement active; frame dropped."
            })
            return

        if global_judgement_semaphore.locked():
            await websocket.send_json({
                "type": "frame_ack",
                "status": "BUSY_SKIPPED",
                "message": "Server judgement capacity busy; frame dropped."
            })
            return

        tracker.last_judged_time = now
        hand_was_present = tracker.hand_activity_marker
        tracker.hand_activity_marker = False

        motion_sec = (now - tracker.motion_start_time) if tracker.motion_start_time > 0 else 0.0
        grace_period = getattr(settings, "UNSCANNED_GRACE_PERIOD_SECONDS", 10.0)
        time_since_scan = (now - tracker.last_scanned_time) if tracker.last_scanned_time > 0 else 999.0

        cart_judging_active.add(cart_id)
        try:
            async with global_judgement_semaphore:
                judgement_res = await asyncio.to_thread(
                    _run_sync_judgement,
                    cart_id,
                    cart_number,
                    active_session.id,
                    img_bgr.copy(),
                    tracker.ref_background.copy() if tracker.ref_background is not None else None,
                    hand_was_present,
                    motion_sec,
                    now,
                    time_since_scan,
                    grace_period,
                    db.get_bind() if db else None
                )
        finally:
            cart_judging_active.discard(cart_id)

        # Dispatch broadcasts
        for bc in judgement_res.get("broadcasts", []):
            if bc["channel"] == "cart":
                await ws_manager.broadcast_to_cart(cart_id, bc["event"], bc["data"])
            elif bc["channel"] == "admin":
                await ws_manager.broadcast_to_admin(bc["event"], bc["data"])

        if judgement_res.get("item_verified"):
            tracker.has_pending_items = False
            tracker.last_pending_item_id = None

        # Dispatch websocket messages to cart camera client
        for ws_msg in judgement_res.get("websocket_messages", []):
            try:
                await websocket.send_json(ws_msg)
            except Exception:
                pass

        # Add trace to tracker if evaluated
        if judgement_res.get("trace_data"):
            tracker.add_trace(judgement_res["trace_data"])

    except Exception as e:
        logger.error(f"Error processing camera frame on cart {cart_number}: {e}")
        try:
            await websocket.send_json({
                "type": "frame_error",
                "message": str(e)
            })
        except Exception:
            pass
    finally:
        if close_db_when_done and db:
            db.close()

async def handle_device_websocket(
    websocket: WebSocket,
    token: Optional[str] = None,
    db: Optional[Session] = None
):
    """
    Dedicated WebSocket handler for Smart Cart Camera Hardware / Laptop Webcam.
    Authenticates via device token in the FIRST MESSAGE (not in the URL).
    The server derives the cart ID from the token hash only, never from the message body.
    Rejects unknown or disabled tokens with close codes and log lines without secrets.
    Limits: max frame size (200 KB), max rate, single connection per cart (replaces previous).
    """
    # 1. STRICT URL SECURITY: Reject any token in URL query string or parameter
    if websocket.query_params.get("token") or token:
        logger.warning("Device connection rejected: Device token in URL query string is forbidden. Must authenticate via first message.")
        await websocket.close(code=4003, reason="Token in URL forbidden. Use first-message auth.")
        return

    # 2. Accept WebSocket and await first message with 5s timeout
    await websocket.accept()

    try:
        raw_first = await asyncio.wait_for(websocket.receive_text(), timeout=5.0)
        first_payload = json.loads(raw_first)
    except asyncio.TimeoutError:
        logger.warning("Device connection rejected: Auth timeout (no first message within 5s).")
        await websocket.close(code=4001, reason="Auth timeout")
        return
    except Exception:
        logger.warning("Device connection rejected: Malformed first message.")
        await websocket.close(code=4001, reason="Malformed auth message")
        return

    if not isinstance(first_payload, dict) or first_payload.get("type") != "auth" or not first_payload.get("token"):
        logger.warning("Device connection rejected: First message must be type 'auth' with token.")
        await websocket.close(code=4001, reason="First message must be type 'auth'")
        return

    raw_token = str(first_payload.get("token")).strip()
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()

    # 3. Derive cart identity solely from token hash in database
    created_db = False
    if db is None:
        db = SessionLocal()
        created_db = True
    cart = None

    try:
        cart = db.query(Cart).filter(Cart.device_token_hash == token_hash).first()

        if not cart:
            logger.warning(f"Device auth failed: Unknown device token prefix '{raw_token[:4] if len(raw_token) >= 4 else '***'}...'")
            audit = AuditLog(
                action="DEVICE_AUTH_FAILURE",
                entity_type="CART_DEVICE",
                details_json=json.dumps({"token_prefix": raw_token[:4] if len(raw_token) >= 4 else "none"})
            )
            db.add(audit)
            db.commit()
            await websocket.close(code=4004, reason="Unknown device token")
            return

        if not cart.is_enabled:
            logger.warning(f"Device connection rejected: Cart '{cart.cart_number}' is disabled.")
            audit = AuditLog(
                action="DISABLED_DEVICE_ATTEMPT",
                entity_type="CART_DEVICE",
                entity_id=cart.id,
                details_json=json.dumps({"cart_number": cart.cart_number})
            )
            db.add(audit)
            db.commit()
            await websocket.close(code=4005, reason="Cart is disabled by store staff")
            return

        cart_id = cart.id
        cart_number = cart.cart_number

        # 4. Concurrency Policy: Single device connection per cart (new connection replaces previous)
        await ws_manager.connect_device(cart_id, websocket)

        cart.camera_status = "ONLINE"
        cart.last_heartbeat = datetime.utcnow()
        db.commit()

        # Record activity timestamp in watchdog
        record_device_activity(cart_id)

        logger.info(f"Cart camera device connected and verified: {cart_number} (ID: {cart_id})")

        # Broadcast online status to store admin portal
        await ws_manager.broadcast_to_admin("CART_STATUS_CHANGE", {
            "cart_id": cart_id,
            "cart_number": cart_number,
            "camera_status": "ONLINE",
            "status": cart.status,
            "last_heartbeat": cart.last_heartbeat.isoformat()
        })

        # Broadcast online status to cart channel for mobile shopper app
        await ws_manager.broadcast_to_cart(cart_id, "CART_CAMERA_STATUS", {
            "cart_id": cart_id,
            "camera_status": "ONLINE",
            "message": "Cart camera connected."
        })

        # Send welcome ACK to device
        await websocket.send_json({
            "type": "auth_ok",
            "cart_id": cart_id,
            "cart_number": cart_number,
            "camera_status": "ONLINE",
            "server_time": datetime.utcnow().isoformat()
        })

        # 5. Independent Server Ping Loop (15s interval < Render 55s proxy timeout)
        async def _server_ping_loop(ws: WebSocket, c_num: str):
            try:
                while True:
                    await asyncio.sleep(15.0)
                    try:
                        if ws.client_state.name == "CONNECTED":
                            await ws.send_text("ping")
                        else:
                            break
                    except Exception:
                        break
            except asyncio.CancelledError:
                pass

        ping_task = asyncio.create_task(_server_ping_loop(websocket, cart_number))

        # 6. Receive loop: limits (max frame size 200 KB, rate throttling, busy frame drops)
        MAX_FRAME_CHARS = 200 * 1024 * 2  # base64 representation max
        last_frame_processed_time = 0.0
        active_frame_task: Optional[asyncio.Task] = None

        while True:
            current_stage = "websocket_receive"
            try:
                msg = await websocket.receive()
            except WebSocketDisconnect:
                break
            except Exception as e:
                if "disconnect" in str(e).lower():
                    break
                raise e

            if msg.get("type") == "websocket.disconnect":
                break

            record_device_activity(cart_id)

            try:
                # Binary JPEG payload (ESP32-CAM direct buffer stream)
                if "bytes" in msg and msg["bytes"]:
                    current_stage = "binary_payload_validation"
                    jpeg_bytes = msg["bytes"]
                    if len(jpeg_bytes) > 200 * 1024:
                        await websocket.send_json({"type": "frame_error", "stage": current_stage, "message": "Frame exceeds 200 KB limit"})
                        continue
                    if active_frame_task and not active_frame_task.done():
                        await websocket.send_json({
                            "type": "frame_ack",
                            "status": "BUSY_SKIPPED",
                            "message": "Cart judgement active; frame dropped."
                        })
                        continue
                    record_device_frame(cart_id)
                    current_stage = "binary_frame_processing"
                    active_frame_task = asyncio.create_task(
                        process_camera_frame(db, cart_id, cart_number, jpeg_bytes, websocket)
                    )

                # Text payload (JSON or ping)
                elif "text" in msg and msg["text"]:
                    raw_text = msg["text"].strip()
                    if raw_text == "ping":
                        await websocket.send_text("pong")
                        continue
                    if raw_text == "pong":
                        continue

                    current_stage = "json_parse"
                    try:
                        payload = json.loads(raw_text)
                    except json.JSONDecodeError:
                        continue

                    event_type = payload.get("type")

                    if event_type == "heartbeat":
                        current_stage = "heartbeat"
                        db_cart = db.query(Cart).filter(Cart.id == cart_id).first()
                        if db_cart:
                            db_cart.last_heartbeat = datetime.utcnow()
                            db_cart.camera_status = "ONLINE"
                            if "battery" in payload:
                                try:
                                    db_cart.battery_level = int(payload["battery"])
                                except (ValueError, TypeError):
                                    pass
                            db.commit()

                        await websocket.send_json({
                            "type": "heartbeat_ack",
                            "cart_number": cart_number,
                            "timestamp": datetime.utcnow().isoformat()
                        })

                    elif event_type in ("frame", "reference_frame"):
                        current_stage = "frame_metadata_validation"
                        is_reference = event_type == "reference_frame" or bool(payload.get("is_reference", False))
                        face_present = bool(payload.get("face_present", False))
                        hand_present = bool(payload.get("hand_present", False))
                        face_boxes = payload.get("face_boxes") or []
                        detector_profile = payload.get("profile") or "privacy"
                        frame_data = payload.get("data") or payload.get("image")

                        # PRIVACY ENFORCEMENT: If face detected, image is discarded unless mode is mask_and_judge
                        face_mode = getattr(settings, "FACE_ON_PACKAGING_MODE", "withhold").lower()
                        if face_present and face_mode != "mask_and_judge":
                            frame_data = None

                        # Size check (200 KB)
                        if frame_data and len(frame_data) > MAX_FRAME_CHARS:
                            await websocket.send_json({"type": "frame_error", "stage": current_stage, "message": "Frame exceeds 200 KB limit"})
                            continue

                        # Rate throttle: max 10 FPS (0.08s min gap)
                        now_ts = time.time()
                        if now_ts - last_frame_processed_time < 0.08:
                            await websocket.send_json({
                                "type": "frame_ack",
                                "status": "BUSY_SKIPPED",
                                "message": "Frame rate throttled (>10 FPS); frame dropped."
                            })
                            continue
                        last_frame_processed_time = now_ts

                        # Record frame in watchdog (updates rolling frames per minute & in-memory preview)
                        record_device_frame(cart_id, frame_data, is_reference=is_reference)

                        if is_reference and frame_data:
                            current_stage = "reference_frame_save"
                            try:
                                img_bgr, _ = verification_engine._decode_to_cv2(frame_data)
                                tracker = get_tracker(cart_id)
                                tracker.ref_background = img_bgr.copy()
                            except Exception:
                                pass
                            await websocket.send_json({
                                "type": "reference_ack",
                                "status": "REFERENCE_SAVED",
                                "cart_number": cart_number,
                                "timestamp": datetime.utcnow().isoformat()
                            })
                            continue

                        if active_frame_task and not active_frame_task.done():
                            await websocket.send_json({
                                "type": "frame_ack",
                                "status": "BUSY_SKIPPED",
                                "message": "Cart judgement active; frame dropped."
                            })
                            continue

                        current_stage = "camera_frame_processing"
                        if face_present:
                            # Privacy: frame image is withheld (None) in withhold mode, metadata sent to processor
                            active_frame_task = asyncio.create_task(process_camera_frame(
                                db,
                                cart_id,
                                cart_number,
                                frame_data if face_mode == "mask_and_judge" else None,
                                websocket,
                                hand_present=hand_present,
                                face_present=True,
                                motion=bool(payload.get("motion", False)),
                                face_boxes=face_boxes,
                                detector_profile=detector_profile
                            ))
                        elif frame_data:
                            # Process frame if not a face and under limit
                            active_frame_task = asyncio.create_task(process_camera_frame(
                                db,
                                cart_id,
                                cart_number,
                                frame_data,
                                websocket,
                                hand_present=hand_present,
                                face_present=False,
                                motion=bool(payload.get("motion", False)),
                                face_boxes=face_boxes,
                                detector_profile=detector_profile
                            ))
                        else:
                            await websocket.send_json({
                                "type": "frame_ack",
                                "status": "METADATA_ONLY",
                                "frames_per_minute": get_frames_per_minute(cart_id)
                            })

                    elif event_type == "motion":
                        current_stage = "motion_event"
                        state = payload.get("state")
                        logger.debug(f"[{cart_number}] Motion sensor event: {state}")
                        await websocket.send_json({
                            "type": "motion_ack",
                            "state": state
                        })

            except Exception as frame_err:
                logger.error(
                    f"[{cart_number}] Frame processing failed at stage '{current_stage}' (cart_id={cart_id}): {frame_err}"
                )
                try:
                    await websocket.send_json({
                        "type": "frame_error",
                        "stage": current_stage,
                        "cart_id": cart_id,
                        "message": f"Frame error at stage '{current_stage}': {str(frame_err)}"
                    })
                except Exception:
                    pass
                continue

    except WebSocketDisconnect as ws_disc:
        close_code = getattr(ws_disc, "code", 1006)
        close_reason = getattr(ws_disc, "reason", None) or "Device disconnected"
        logger.info(f"[{cart.cart_number if cart else 'UNKNOWN'}] Cart camera device disconnected: code={close_code}, reason='{close_reason}'")
        if cart:
            record_device_close(cart.id, cart.cart_number, close_code, close_reason)
    except Exception as e:
        logger.error(f"[{cart.cart_number if cart else 'UNKNOWN'}] Cart camera device WebSocket error: {e}")
        if cart:
            record_device_close(cart.id, cart.cart_number, 1006, f"Unhandled server error: {str(e)[:100]}")
    finally:
        if 'ping_task' in locals() and ping_task and not ping_task.done():
            ping_task.cancel()
        if 'active_frame_task' in locals() and active_frame_task and not active_frame_task.done():
            active_frame_task.cancel()
        if cart:
            try:
                ws_manager.disconnect_device(cart.id, websocket)
                clear_device_activity(cart.id)
                db_cart = db.query(Cart).filter(Cart.id == cart.id).first()
                if db_cart:
                    db_cart.camera_status = "OFFLINE"
                    db.commit()
                    await ws_manager.broadcast_to_admin("CART_STATUS_CHANGE", {
                        "cart_id": cart.id,
                        "cart_number": cart.cart_number,
                        "camera_status": "OFFLINE",
                        "status": db_cart.status
                    })
                    await ws_manager.broadcast_to_cart(cart.id, "CART_CAMERA_STATUS", {
                        "cart_id": cart.id,
                        "camera_status": "OFFLINE",
                        "message": "Cart camera disconnected."
                    })
            except Exception as ex:
                logger.error(f"Error updating cart offline status: {ex}")
        if created_db and db:
            db.close()
