import json
import hashlib
import logging
from datetime import datetime
from typing import Optional, Any
from fastapi import WebSocket, WebSocketDisconnect, status
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models.cart import Cart
from app.models.session import CartSession, CartItem
from app.models.product import Product
from app.models.transaction import AuditLog
from app.websocket.manager import ws_manager
from app.services.session_service import SessionService
from app.ai.verification_engine import verification_engine

logger = logging.getLogger("smartcart.device")

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
    Checks for pending items in active shopping session and executes AI verification.
    """
    try:
        active_session = db.query(CartSession).filter(
            CartSession.cart_id == cart_id,
            CartSession.status == "ACTIVE"
        ).first()

        if not active_session:
            await websocket.send_json({
                "type": "frame_ack",
                "status": "IDLE",
                "message": "Cart is currently idle (no active shopper session)."
            })
            return

        # Look for the most recent item scanned on mobile waiting for camera confirmation
        pending_item = db.query(CartItem).join(Product).filter(
            CartItem.session_id == active_session.id,
            CartItem.status == "PENDING"
        ).order_by(CartItem.scanned_at.desc()).first()

        if pending_item:
            # AI evaluation comparing camera embedding to scanned product
            claimed_barcode = pending_item.product.barcode
            eval_result = verification_engine.evaluate_item_placement(
                db=db,
                claimed_barcode=claimed_barcode,
                image_data=image_data
            )

            # Confirm verified placement
            verified_item = await SessionService.verify_item_placement(
                db=db,
                session_id=active_session.id,
                barcode=claimed_barcode,
                confidence=float(eval_result.get("confidence", 0.95)),
                evidence_url=None
            )

            if verified_item:
                await websocket.send_json({
                    "type": "verification_result",
                    "action": "ITEM_VERIFIED",
                    "product_name": verified_item.product.name,
                    "barcode": claimed_barcode,
                    "confidence": eval_result.get("confidence", 0.95)
                })
                logger.info(f"[{cart_number}] Item '{verified_item.product.name}' verified via camera frame.")
        else:
            await websocket.send_json({
                "type": "frame_ack",
                "status": "VERIFIED_ALL",
                "message": "Frame received. All scanned items currently verified."
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

        logger.info(f"Cart camera device connected and verified: {cart_number} (ID: {cart_id})")

        # Broadcast online status to store admin portal
        await ws_manager.broadcast_to_admin("CART_STATUS_CHANGE", {
            "cart_id": cart_id,
            "cart_number": cart_number,
            "camera_status": "ONLINE",
            "status": cart.status,
            "last_heartbeat": cart.last_heartbeat.isoformat()
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
            except Exception as ex:
                logger.error(f"Error updating cart offline status: {ex}")
        db.close()
