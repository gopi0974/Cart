import asyncio
import logging
import time
from datetime import datetime
from typing import Dict, List, Optional
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models.cart import Cart
from app.websocket.manager import ws_manager

logger = logging.getLogger("smartcart.watchdog")

# In-memory tracking of last active timestamp for each cart device
cart_device_last_seen: Dict[str, datetime] = {}
# Rolling 60-second window of frame timestamps to compute frames per minute
cart_frame_timestamps: Dict[str, List[float]] = {}
# Single latest frame per cart for staff "Test camera" preview (never stored to disk or DB)
cart_latest_frames: Dict[str, dict] = {}

def record_device_activity(cart_id: str):
    """Record heartbeat, motion, or frame activity timestamp in memory."""
    cart_device_last_seen[cart_id] = datetime.utcnow()

def record_device_frame(cart_id: str, frame_data: Optional[str] = None, is_reference: bool = False):
    """Record incoming frame for rolling frames-per-minute metric and staff test preview."""
    now = time.time()
    record_device_activity(cart_id)

    # 1. Update rolling timestamps
    if cart_id not in cart_frame_timestamps:
        cart_frame_timestamps[cart_id] = []
    cart_frame_timestamps[cart_id].append(now)
    # Prune timestamps older than 60s
    cutoff = now - 60.0
    cart_frame_timestamps[cart_id] = [t for t in cart_frame_timestamps[cart_id] if t >= cutoff]

    # 2. Store single latest frame preview in memory (only if frame data provided)
    if frame_data:
        cart_latest_frames[cart_id] = {
            "data": frame_data,
            "captured_at": datetime.utcnow().isoformat(),
            "is_reference": is_reference,
        }

def get_frames_per_minute(cart_id: str) -> int:
    """Return number of frames received in the last 60 seconds."""
    if cart_id not in cart_frame_timestamps:
        return 0
    now = time.time()
    cutoff = now - 60.0
    cart_frame_timestamps[cart_id] = [t for t in cart_frame_timestamps[cart_id] if t >= cutoff]
    return len(cart_frame_timestamps[cart_id])

def get_latest_frame(cart_id: str) -> Optional[dict]:
    """Retrieve latest in-memory preview frame for staff camera verification."""
    return cart_latest_frames.get(cart_id)

def clear_device_activity(cart_id: str):
    """Remove cart device activity and rolling metrics when disconnected."""
    cart_device_last_seen.pop(cart_id, None)
    cart_frame_timestamps.pop(cart_id, None)
    cart_latest_frames.pop(cart_id, None)

async def check_cart_timeouts(db: Session, now: Optional[datetime] = None, timeout_seconds: int = 15) -> List[str]:
    """
    Check for timed-out cart camera devices and transition them to OFFLINE.
    Returns list of timed out cart IDs.
    """
    if now is None:
        now = datetime.utcnow()
    timed_out_ids: List[str] = []
    online_carts = db.query(Cart).filter(Cart.camera_status == "ONLINE").all()
    for cart in online_carts:
        last_seen = cart_device_last_seen.get(cart.id)
        if not last_seen and cart.last_heartbeat:
            last_seen = cart.last_heartbeat
            cart_device_last_seen[cart.id] = last_seen

        if last_seen:
            elapsed = (now - last_seen).total_seconds()
            if elapsed > timeout_seconds:
                logger.warning(
                    f"Cart '{cart.cart_number}' camera watchdog timeout ({elapsed:.1f}s > {timeout_seconds}s). Setting OFFLINE."
                )
                cart.camera_status = "OFFLINE"
                db.commit()

                # Clear rolling preview
                clear_device_activity(cart.id)
                ws_manager.disconnect_device(cart.id)

                # Broadcast status change to Admin portal
                await ws_manager.broadcast_to_admin("CART_STATUS_CHANGE", {
                    "cart_id": cart.id,
                    "cart_number": cart.cart_number,
                    "camera_status": "OFFLINE",
                    "status": cart.status
                })

                # Broadcast status change to Cart channel (for mobile Shopper app)
                await ws_manager.broadcast_to_cart(cart.id, "CART_CAMERA_STATUS", {
                    "cart_id": cart.id,
                    "camera_status": "OFFLINE",
                    "message": "Cart camera disconnected."
                })
                timed_out_ids.append(cart.id)
    return timed_out_ids

async def run_camera_watchdog(check_interval_seconds: int = 2, timeout_seconds: int = 15):
    """
    Background watchdog task that maintains cart camera status.
    If an ONLINE cart receives no frames or heartbeats for > timeout_seconds (15s),
    it transitions to OFFLINE, alerts Admin, and pushes status to Shopper session.
    """
    logger.info(f"Cart camera hardware watchdog service started ({timeout_seconds}s timeout).")
    while True:
        try:
            await asyncio.sleep(check_interval_seconds)
            db = SessionLocal()
            try:
                await check_cart_timeouts(db=db, timeout_seconds=timeout_seconds)
            finally:
                db.close()
        except asyncio.CancelledError:
            logger.info("Cart camera watchdog task cancelled.")
            break
        except Exception as e:
            logger.error(f"Error in camera watchdog loop: {e}")
