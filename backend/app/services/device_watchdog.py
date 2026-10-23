import asyncio
import logging
from datetime import datetime
from typing import Dict
from app.database import SessionLocal
from app.models.cart import Cart
from app.websocket.manager import ws_manager

logger = logging.getLogger("smartcart.watchdog")

# In-memory tracking of last active timestamp for each cart device
cart_device_last_seen: Dict[str, datetime] = {}

def record_device_activity(cart_id: str):
    """Record heartbeat, motion, or frame activity timestamp in memory."""
    cart_device_last_seen[cart_id] = datetime.utcnow()

def clear_device_activity(cart_id: str):
    """Remove cart device activity timestamp when disconnected."""
    cart_device_last_seen.pop(cart_id, None)

async def run_camera_watchdog(check_interval_seconds: int = 3, timeout_seconds: int = 10):
    """
    Background watchdog task that maintains cart camera status.
    If an ONLINE cart receives no frames or heartbeats for > timeout_seconds,
    it transitions to OFFLINE, alerts Admin, and gates Shopper checkout.
    """
    logger.info("Cart camera hardware watchdog service started (10s timeout).")
    while True:
        try:
            await asyncio.sleep(check_interval_seconds)
            now = datetime.utcnow()
            db = SessionLocal()
            try:
                # Find all carts currently marked ONLINE
                online_carts = db.query(Cart).filter(Cart.camera_status == "ONLINE").all()
                for cart in online_carts:
                    last_seen = cart_device_last_seen.get(cart.id)
                    # Fallback to database last_heartbeat if not yet in memory
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
            finally:
                db.close()
        except asyncio.CancelledError:
            logger.info("Cart camera watchdog task cancelled.")
            break
        except Exception as e:
            logger.error(f"Error in camera watchdog loop: {e}")
