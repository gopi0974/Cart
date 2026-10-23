import json
import hashlib
import logging
from datetime import datetime
import numpy as np
from typing import Optional, Any, Dict
from fastapi import WebSocket, WebSocketDisconnect, status
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models.cart import Cart
from app.models.session import CartSession, CartItem
from app.models.product import Product
from app.models.transaction import AuditLog
from app.websocket.manager import ws_manager
from app.services.session_service import SessionService
import time
from app.ai.verification_engine import verification_engine
from app.ai.object_detector import object_detector
from app.services.alert_service import AlertService

logger = logging.getLogger("smartcart.device")

class CartVisionTracker:
    def __init__(self, cart_id: str):
        self.cart_id = cart_id
        self.hand_in_frame: bool = False
        self.hand_left_time: float = 0.0
        self.stable_frame_count: int = 0
        self.ref_background: Optional[np.ndarray] = None
        self.last_evaluated_time: float = 0.0

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
    websocket: WebSocket
):
    """
    Process incoming camera frame from cart device (Laptop webcam or ESP32-CAM).
    Derives cart context solely from authenticated token.
    Uses YOLOv8n to locate hands and objects, waits for hand withdrawal and frame stabilization (~1s),
    and executes tiered CLIP cosine verification against claimed or unscanned items.
    """
    try:
        img_bgr, _ = verification_engine._decode_to_cv2(image_data)
        tracker = get_tracker(cart_id)
        now = time.time()

        # 1. Detect hands and persons via YOLOv8n (COCO class 0)
        detection = object_detector.detect(img_bgr)

        if detection["hand_detected"]:
            tracker.hand_in_frame = True
            tracker.stable_frame_count = 0
            await websocket.send_json({
                "type": "vision_status",
                "status": "HAND_IN_FRAME",
                "message": "Hand in frame: item placement in progress..."
            })
            return

        # 2. Hand is not currently in frame - check stabilization
        if tracker.hand_in_frame:
            # Hand just exited
            tracker.hand_in_frame = False
            tracker.hand_left_time = now
            tracker.stable_frame_count = 1
            await websocket.send_json({
                "type": "vision_status",
                "status": "STABILIZING",
                "message": "Hand withdrawn. Stabilizing basket image..."
            })
            return

        tracker.stable_frame_count += 1

        # 3. Check active session on this cart
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

        # 4. Check for pending item scanned on mobile waiting for camera confirmation
        pending_item = db.query(CartItem).join(Product).filter(
            CartItem.session_id == active_session.id,
            CartItem.status == "PENDING"
        ).order_by(CartItem.scanned_at.desc()).first()

        if pending_item:
            claimed_barcode = pending_item.product.barcode
            eval_result = verification_engine.evaluate_item_placement(
                db=db,
                claimed_barcode=claimed_barcode,
                image_data=img_bgr,
                ref_background=tracker.ref_background
            )
            tracker.ref_background = img_bgr.copy()
            tracker.last_evaluated_time = now

            decision = eval_result.get("decision")
            confidence = float(eval_result.get("confidence", 0.95))
            evidence_url = eval_result.get("evidence_url")

            if decision == "AUTO_APPROVE":
                verified_item = await SessionService.verify_item_placement(
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

            elif decision == "RESCAN_PROMPT":
                # Uncertain confidence: ask shopper to reposition/rescan
                await ws_manager.broadcast_to_cart(cart_id, "ITEM_UNCERTAIN", {
                    "message": eval_result.get("message"),
                    "barcode": claimed_barcode,
                    "confidence": confidence
                })
                await websocket.send_json({
                    "type": "verification_result",
                    "action": "UNCERTAIN_RESCAN",
                    "product_name": pending_item.product.name,
                    "confidence": confidence,
                    "message": eval_result.get("message")
                })

            elif decision == "WRONG_ITEM":
                detected_name = eval_result.get("detected_product_name", "Different Item")
                await SessionService.flag_mismatch(
                    db=db,
                    session_id=active_session.id,
                    scanned_barcode=claimed_barcode,
                    detected_product_name=detected_name,
                    evidence_url=evidence_url,
                    confidence=confidence
                )
                await websocket.send_json({
                    "type": "verification_result",
                    "action": "ITEM_MISMATCH",
                    "scanned_barcode": claimed_barcode,
                    "detected_as": detected_name,
                    "confidence": confidence
                })

            elif decision == "ESCALATE_ADMIN_REVIEW":
                # Low similarity: forward to Admin review queue
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
                    confidence=confidence
                )
                await websocket.send_json({
                    "type": "verification_result",
                    "action": "ESCALATE_ADMIN_REVIEW",
                    "product_name": pending_item.product.name,
                    "confidence": confidence
                })

        else:
            # 5. No pending item: Check for Unscanned Item Placement
            motion_box = object_detector.compute_motion_box(tracker.ref_background, img_bgr)
            detection_has_objects = bool(detection["object_boxes"])

            if motion_box or detection_has_objects:
                eval_result = verification_engine.evaluate_item_placement(
                    db=db,
                    claimed_barcode=None,
                    image_data=img_bgr,
                    ref_background=tracker.ref_background
                )
                tracker.ref_background = img_bgr.copy()
                detected_prod = eval_result.get("detected_product")

                await SessionService.flag_unscanned_item(
                    db=db,
                    cart_id=cart_id,
                    detected_product_id=detected_prod["id"] if detected_prod else None,
                    evidence_url=eval_result.get("evidence_url")
                )
                await websocket.send_json({
                    "type": "verification_result",
                    "action": "UNSCANNED_ITEM_DETECTED",
                    "detected_as": detected_prod["name"] if detected_prod else "Unidentified Item",
                    "confidence": eval_result.get("confidence", 0.88)
                })
            else:
                tracker.ref_background = img_bgr.copy()
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

async def handle_device_websocket(websocket: WebSocket, token: Optional[str] = None):
    """
    Dedicated WebSocket handler for Smart Cart Camera Hardware / Laptop Webcam.
    Authenticates via device token, derives cart identity strictly from server database,
    and handles heartbeats and motion-triggered frame streams.
    Compatible with ESP32-CAM binary or JSON payloads.
    """
    # 1. Extract device token (from query string or headers)
    if not token:
        token = websocket.query_params.get("token") or websocket.headers.get("x-device-token")

    if not token:
        logger.warning("Device connection rejected: Missing device authentication token.")
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Missing device token")
        return

    # 2. Hash token and authenticate against database
    token_hash = hashlib.sha256(token.strip().encode("utf-8")).hexdigest()
    db = SessionLocal()
    cart = None

    try:
        cart = db.query(Cart).filter(Cart.device_token_hash == token_hash).first()

        if not cart:
            logger.warning(f"Security Alert: Unknown device token hash '{token_hash[:8]}...'")
            audit = AuditLog(
                action="DEVICE_AUTH_FAILURE",
                entity_type="CART_DEVICE",
                details_json=json.dumps({"token_prefix": token[:6] if token else "none"})
            )
            db.add(audit)
            db.commit()
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Unknown device token")
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
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Cart is disabled by store staff")
            return

        # 3. Connection approved - derive cart identity strictly from server record
        cart_id = cart.id
        cart_number = cart.cart_number

        await websocket.accept()
        cart.camera_status = "ONLINE"
        cart.last_heartbeat = datetime.utcnow()
        db.commit()

        # Record activity timestamp in watchdog
        from app.services.device_watchdog import record_device_activity, clear_device_activity
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
            "type": "connected",
            "cart_id": cart_id,
            "cart_number": cart_number,
            "status": "ONLINE",
            "server_time": datetime.utcnow().isoformat()
        })

        # 4. Receive loop: binary frames (ESP32-CAM) and JSON messages (Heartbeats / Base64 frames)
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

            # Any incoming message counts as activity for watchdog
            record_device_activity(cart_id)

            # Binary JPEG payload (ESP32-CAM direct buffer stream)
            if "bytes" in msg and msg["bytes"]:
                jpeg_bytes = msg["bytes"]
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
                    # Update heartbeat and battery
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

                elif event_type == "frame":
                    frame_data = payload.get("data") or payload.get("image")
                    if frame_data:
                        await process_camera_frame(db, cart_id, cart_number, frame_data, websocket)

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
                from app.services.device_watchdog import clear_device_activity
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
        db.close()
