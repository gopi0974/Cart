import asyncio
import json
import hashlib
import logging
from datetime import datetime
import numpy as np
from typing import Optional, Any, Dict
from fastapi import WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models.cart import Cart
from app.models.session import CartSession, CartItem
from app.models.transaction import AuditLog
from app.websocket.manager import ws_manager
from app.services.session_service import SessionService
import time
from app.ai.verification_engine import verification_engine
from app.ai.object_detector import object_detector
from app.services.alert_service import AlertService
from app.services.device_watchdog import (
    record_device_activity,
    record_device_frame,
    clear_device_activity,
    get_frames_per_minute
)

logger = logging.getLogger("smartcart.device")

class CartVisionTracker:
    def __init__(self, cart_id: str):
        self.cart_id = cart_id
        self.hand_in_frame: bool = False
        self.hand_left_time: float = 0.0
        self.stable_frame_count: int = 0
        self.stable_start_time: float = 0.0
        self.last_motion_time: float = 0.0
        self.last_judged_time: float = 0.0
        self.face_seen_start_time: float = 0.0
        self.ref_background: Optional[np.ndarray] = None
        self.last_stable_frame: Optional[np.ndarray] = None

cart_trackers: Dict[str, CartVisionTracker] = {}

def get_tracker(cart_id: str) -> CartVisionTracker:
    if cart_id not in cart_trackers:
        cart_trackers[cart_id] = CartVisionTracker(cart_id)
    return cart_trackers[cart_id]

async def process_camera_frame(
    db: Session,
    cart_id: str,
    cart_number: str,
    image_data: Any,
    websocket: WebSocket,
    hand_present: bool = False,
    face_present: bool = False,
    motion: bool = False
):
    """
    Process incoming camera frame from cart device (Laptop webcam or ESP32-CAM).
    Derives cart context solely from authenticated token.
    Rules:
      1. Empty-cart reference stored from "Capture empty cart reference" or first stable frame.
      2. Judge ONLY when hand_present=False, face_present=False, and frame stable for ~1 second.
      3. Faces on packaging: if face_present stays true for stable object, frame withheld and
         shopper alerted "We can't check this item. Please ask staff" + Admin review case.
      4. Detect changed region and run recognition matching enrollment pipeline.
    """
    try:
        tracker = get_tracker(cart_id)
        now = time.time()

        # 1. PRIVACY CHECK: Faces on Packaging or in Frame
        if face_present:
            if tracker.face_seen_start_time == 0.0:
                tracker.face_seen_start_time = now
            tracker.stable_frame_count = 0
            tracker.stable_start_time = 0.0

            # If face_present stays true for about 1 second on a stable object:
            if (now - tracker.face_seen_start_time) >= 1.0:
                active_session = db.query(CartSession).filter(
                    CartSession.cart_id == cart_id,
                    CartSession.status == "ACTIVE"
                ).first()
                if active_session:
                    pending_item = db.query(CartItem).join(CartItem.product).filter(
                        CartItem.session_id == active_session.id,
                        CartItem.status == "PENDING"
                    ).order_by(CartItem.scanned_at.desc()).first()

                    if pending_item:
                        pending_item.status = "WARNING"
                        pending_item.warning_reason = "FACE_DETECTED"
                        db.commit()

                        # Shopper notice
                        await ws_manager.broadcast_to_cart(cart_id, "ITEM_WARNING", {
                            "item_id": pending_item.id,
                            "product_name": pending_item.product.name,
                            "barcode": pending_item.product.barcode,
                            "status": "WARNING",
                            "reason": "FACE_DETECTED",
                            "message": "We can't check this item. Please ask staff"
                        })

                        # Admin review case: "frame withheld (face detected)"
                        await AlertService.create_alert(
                            db=db,
                            cart_id=cart_id,
                            session_id=active_session.id,
                            alert_type="FACE_IN_PACKAGING_WITHHELD",
                            severity="MEDIUM",
                            message=f"frame withheld (face detected) for '{pending_item.product.name}'.",
                            evidence_url=None,
                            create_review_case=True,
                            scanned_barcode=pending_item.product.barcode,
                            confidence=0.0
                        )

            await websocket.send_json({
                "type": "frame_ack",
                "status": "FACE_REDACTED",
                "message": "Face detected. Frame withheld for privacy."
            })
            return

        tracker.face_seen_start_time = 0.0

        # 2. Hand Occlusion & Motion Gate: Ignore frames with motion or hands
        if hand_present or motion:
            tracker.hand_in_frame = hand_present
            tracker.stable_frame_count = 0
            tracker.stable_start_time = 0.0
            tracker.last_motion_time = now
            status_text = "HAND_IN_FRAME" if hand_present else "MOTION_DETECTED"
            msg_text = "Hand in frame: item placement in progress..." if hand_present else "Cart motion: waiting for basket to steady..."
            await websocket.send_json({
                "type": "vision_status",
                "status": status_text,
                "message": msg_text
            })
            return

        # 3. Stabilization: Frame must be steady for about 1 second
        if tracker.stable_start_time == 0.0:
            tracker.stable_start_time = now
        tracker.stable_frame_count += 1
        duration_stable = now - tracker.stable_start_time

        if duration_stable < 1.0 or tracker.stable_frame_count < 2:
            await websocket.send_json({
                "type": "vision_status",
                "status": "STABILIZING",
                "message": "Stabilizing basket image..."
            })
            return

        # Prevent duplicate judgments on the exact same static scene
        if tracker.last_judged_time >= tracker.last_motion_time:
            await websocket.send_json({
                "type": "frame_ack",
                "status": "VERIFIED_ALL",
                "message": "Basket is steady."
            })
            return
        tracker.last_judged_time = now

        # Decode frame
        img_bgr, _ = verification_engine._decode_to_cv2(image_data)

        # 4. Check active session on this cart
        active_session = db.query(CartSession).filter(
            CartSession.cart_id == cart_id,
            CartSession.status == "ACTIVE"
        ).first()

        if not active_session:
            tracker.ref_background = img_bgr.copy()
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
            logger.info(f"[{cart_number}] Empty cart reference auto-initialized from first stable frame.")

        # 5. Check for item in REMOVING status (verified item being taken out)
        removing_item = db.query(CartItem).join(CartItem.product).filter(
            CartItem.session_id == active_session.id,
            CartItem.status == "REMOVING"
        ).first()

        if removing_item:
            claimed_barcode = removing_item.product.barcode
            eval_rem = verification_engine.evaluate_item_removal(
                db=db,
                target_barcode=claimed_barcode,
                image_data=img_bgr,
                ref_background=tracker.ref_background,
                cart_id=cart_id,
                session_id=active_session.id,
                item_id=removing_item.id
            )
            decision = eval_rem.get("decision")
            if decision == "CONFIRMED_REMOVED":
                removing_item.status = "REMOVED_PENDING_RESCAN"
                removing_item.verification_evidence_url = eval_rem.get("evidence_url")
                db.commit()

                # Persistent warning: "Rescan the barcode to remove this item"
                await ws_manager.broadcast_to_cart(cart_id, "ITEM_REMOVED_AWAITING_RESCAN", {
                    "item_id": removing_item.id,
                    "product_name": removing_item.product.name,
                    "barcode": claimed_barcode,
                    "status": "REMOVED_PENDING_RESCAN",
                    "message": "Rescan the barcode to remove this item",
                    "evidence_url": eval_rem.get("evidence_url")
                })
                await websocket.send_json({
                    "type": "verification_result",
                    "action": "ITEM_REMOVED_AWAITING_RESCAN",
                    "product_name": removing_item.product.name,
                    "status": "REMOVED_PENDING_RESCAN"
                })
            elif decision == "STILL_IN_CART":
                await ws_manager.broadcast_to_cart(cart_id, "ITEM_WARNING", {
                    "item_id": removing_item.id,
                    "product_name": removing_item.product.name,
                    "status": "REMOVING",
                    "message": "We still see this item in the cart. Please take it out."
                })
            return

        # 6. Check for pending item scanned on mobile waiting for camera confirmation
        pending_item = db.query(CartItem).join(CartItem.product).filter(
            CartItem.session_id == active_session.id,
            CartItem.status == "PENDING"
        ).order_by(CartItem.scanned_at.desc()).first()

        if pending_item:
            claimed_barcode = pending_item.product.barcode
            eval_result = verification_engine.evaluate_item_placement(
                db=db,
                claimed_barcode=claimed_barcode,
                image_data=img_bgr,
                ref_background=tracker.ref_background,
                cart_id=cart_id,
                session_id=active_session.id,
                item_id=pending_item.id
            )
            tracker.last_stable_frame = img_bgr.copy()

            decision = eval_result.get("decision")
            confidence = float(eval_result.get("confidence", 0.0))
            evidence_url = eval_result.get("evidence_url")

            if decision == "AUTO_APPROVE":
                await SessionService.verify_item_placement(
                    db=db,
                    session_id=active_session.id,
                    barcode=claimed_barcode,
                    confidence=confidence,
                    evidence_url=evidence_url
                )
                await websocket.send_json({
                    "type": "verification_result",
                    "action": "ITEM_VERIFIED",
                    "product_name": pending_item.product.name,
                    "barcode": claimed_barcode,
                    "confidence": confidence,
                    "evidence_url": evidence_url
                })
                logger.info(f"[{cart_number}] Item '{pending_item.product.name}' VERIFIED (Confidence: {confidence*100:.1f}%).")

            elif decision == "REPOSITION_PROMPT":
                pending_item.status = "WARNING"
                pending_item.warning_reason = "REPOSITION"
                pending_item.confidence_score = confidence
                pending_item.verification_evidence_url = evidence_url
                db.commit()

                await ws_manager.broadcast_to_cart(cart_id, "ITEM_WARNING", {
                    "item_id": pending_item.id,
                    "product_name": pending_item.product.name,
                    "barcode": claimed_barcode,
                    "status": "WARNING",
                    "reason": "REPOSITION",
                    "confidence": confidence,
                    "message": eval_result.get("message")
                })
                await websocket.send_json({
                    "type": "verification_result",
                    "action": "UNCERTAIN_REPOSITION",
                    "product_name": pending_item.product.name,
                    "confidence": confidence,
                    "message": eval_result.get("message")
                })

            elif decision == "WRONG_ITEM":
                wrong_match = eval_result.get("top_match")
                wrong_name = wrong_match.get("product_name") if wrong_match else "Different Item"
                pending_item.status = "WARNING"
                pending_item.warning_reason = "MISMATCH"
                pending_item.confidence_score = confidence
                pending_item.verification_evidence_url = evidence_url
                db.commit()

                await AlertService.create_alert(
                    db=db,
                    cart_id=cart_id,
                    session_id=active_session.id,
                    alert_type="MISMATCH_ITEM",
                    message=f"Scanned '{pending_item.product.name}' but detected '{wrong_name}'.",
                    severity="HIGH",
                    evidence_url=evidence_url,
                    create_review_case=True,
                    scanned_barcode=claimed_barcode,
                    predicted_product_id=wrong_match.get("id") if wrong_match else None,
                    confidence=confidence,
                    top_candidates=eval_result.get("top_candidates")
                )

                await ws_manager.broadcast_to_cart(cart_id, "ITEM_WARNING", {
                    "item_id": pending_item.id,
                    "product_name": pending_item.product.name,
                    "barcode": claimed_barcode,
                    "status": "WARNING",
                    "reason": "MISMATCH",
                    "detected_as": wrong_name,
                    "confidence": confidence,
                    "message": eval_result.get("message")
                })
                await websocket.send_json({
                    "type": "verification_result",
                    "action": "ITEM_MISMATCH",
                    "scanned_barcode": claimed_barcode,
                    "detected_as": wrong_name,
                    "confidence": confidence
                })

            elif decision == "ESCALATE_ADMIN_REVIEW":
                pending_item.status = "WARNING"
                pending_item.warning_reason = "LOW_CONFIDENCE"
                pending_item.confidence_score = confidence
                pending_item.verification_evidence_url = evidence_url
                db.commit()

                await AlertService.create_alert(
                    db=db,
                    cart_id=cart_id,
                    session_id=active_session.id,
                    alert_type="LOW_CONFIDENCE_VERIFICATION",
                    severity="MEDIUM",
                    message=f"Visual confidence below threshold ({confidence*100:.1f}%) for '{pending_item.product.name}'.",
                    evidence_url=evidence_url,
                    create_review_case=True,
                    scanned_barcode=claimed_barcode,
                    confidence=confidence,
                    top_candidates=eval_result.get("top_candidates")
                )
                await ws_manager.broadcast_to_cart(cart_id, "ITEM_WARNING", {
                    "item_id": pending_item.id,
                    "product_name": pending_item.product.name,
                    "barcode": claimed_barcode,
                    "status": "WARNING",
                    "reason": "LOW_CONFIDENCE",
                    "confidence": confidence,
                    "message": eval_result.get("message")
                })
                await websocket.send_json({
                    "type": "verification_result",
                    "action": "ESCALATE_ADMIN_REVIEW",
                    "product_name": pending_item.product.name,
                    "confidence": confidence
                })

        else:
            # 7. No pending item: Check for Unscanned Item Placement
            motion_box = object_detector.compute_motion_box(tracker.ref_background, img_bgr)

            if motion_box is not None:
                eval_result = verification_engine.evaluate_item_placement(
                    db=db,
                    claimed_barcode=None,
                    image_data=img_bgr,
                    ref_background=tracker.ref_background,
                    cart_id=cart_id,
                    session_id=active_session.id
                )
                tracker.last_stable_frame = img_bgr.copy()
                detected_prod = eval_result.get("top_match")

                await SessionService.flag_unscanned_item(
                    db=db,
                    cart_id=cart_id,
                    detected_product_id=(detected_prod.get("id") or detected_prod.get("product_id")) if detected_prod else None,
                    evidence_url=eval_result.get("evidence_url")
                )
                await websocket.send_json({
                    "type": "verification_result",
                    "action": "UNSCANNED_ITEM_DETECTED",
                    "detected_as": detected_prod["product_name"] if detected_prod else "Unidentified Item",
                    "confidence": eval_result.get("confidence", 0.88)
                })
            else:
                await websocket.send_json({
                    "type": "frame_ack",
                    "status": "VERIFIED_ALL",
                    "message": "Frame received. Basket is steady."
                })

    except Exception as e:
        logger.error(f"Error processing camera frame on cart {cart_number}: {e}")
        try:
            await websocket.send_json({
                "type": "frame_error",
                "message": str(e)
            })
        except Exception:
            pass

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

        # 5. Receive loop: limits (max frame size 200 KB, rate throttling, busy frame drops)
        MAX_FRAME_CHARS = 200 * 1024 * 2  # base64 representation max
        last_frame_processed_time = 0.0

        while True:
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

            # Binary JPEG payload (ESP32-CAM direct buffer stream)
            if "bytes" in msg and msg["bytes"]:
                jpeg_bytes = msg["bytes"]
                if len(jpeg_bytes) > 200 * 1024:
                    await websocket.send_json({"type": "frame_error", "message": "Frame exceeds 200 KB limit"})
                    continue
                record_device_frame(cart_id)
                await process_camera_frame(db, cart_id, cart_number, jpeg_bytes, websocket)

            # Text payload (JSON or ping)
            elif "text" in msg and msg["text"]:
                raw_text = msg["text"].strip()
                if raw_text == "ping":
                    await websocket.send_text("pong")
                    continue

                try:
                    payload = json.loads(raw_text)
                except json.JSONDecodeError:
                    continue

                event_type = payload.get("type")

                if event_type == "heartbeat":
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
                    is_reference = event_type == "reference_frame" or bool(payload.get("is_reference", False))
                    face_present = bool(payload.get("face_present", False))
                    hand_present = bool(payload.get("hand_present", False))
                    frame_data = payload.get("data") or payload.get("image")

                    # PRIVACY ENFORCEMENT: If face detected, image is discarded immediately
                    if face_present:
                        frame_data = None

                    # Size check (200 KB)
                    if frame_data and len(frame_data) > MAX_FRAME_CHARS:
                        await websocket.send_json({"type": "frame_error", "message": "Frame exceeds 200 KB limit"})
                        continue

                    # Rate throttle: max 10 FPS (0.08s min gap)
                    now_ts = time.time()
                    if now_ts - last_frame_processed_time < 0.08:
                        # Drop frame to protect server load
                        continue
                    last_frame_processed_time = now_ts

                    # Record frame in watchdog (updates rolling frames per minute & in-memory preview)
                    record_device_frame(cart_id, frame_data, is_reference=is_reference)

                    if is_reference and frame_data:
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

                    if face_present:
                        # Privacy: frame image is withheld (None), metadata sent to processor
                        await process_camera_frame(
                            db,
                            cart_id,
                            cart_number,
                            None,
                            websocket,
                            hand_present=hand_present,
                            face_present=True,
                            motion=bool(payload.get("motion", False))
                        )
                    elif frame_data:
                        # Process frame if not a face and under limit
                        await process_camera_frame(
                            db,
                            cart_id,
                            cart_number,
                            frame_data,
                            websocket,
                            hand_present=hand_present,
                            face_present=False,
                            motion=bool(payload.get("motion", False))
                        )
                    else:
                        await websocket.send_json({
                            "type": "frame_ack",
                            "status": "METADATA_ONLY",
                            "frames_per_minute": get_frames_per_minute(cart_id)
                        })

                elif event_type == "motion":
                    state = payload.get("state")
                    logger.debug(f"[{cart_number}] Motion sensor event: {state}")
                    await websocket.send_json({
                        "type": "motion_ack",
                        "state": state
                    })

    except WebSocketDisconnect:
        logger.info(f"Cart camera device disconnected: {cart.cart_number if cart else 'Unknown'}")
    except Exception as e:
        logger.error(f"Cart camera device WebSocket error: {e}")
    finally:
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
