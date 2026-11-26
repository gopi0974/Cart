import asyncio
import logging
import time
from collections import deque
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
# Ring buffer tracking last 20 close events per cart
cart_close_events: Dict[str, deque] = {}

# Global memory tracking for judging process
_peak_judgement_memory_mb: float = 0.0
_is_judging_active: bool = False

def record_device_activity(cart_id: str):
    """Record heartbeat, motion, or frame activity timestamp in memory."""
    cart_device_last_seen[cart_id] = datetime.utcnow()

def record_device_close(cart_id: str, cart_number: str, code: int, reason: Optional[str] = None):
    """Record WebSocket close event with code and reason into rolling 20-event buffer."""
    if cart_id not in cart_close_events:
        cart_close_events[cart_id] = deque(maxlen=20)
    event = {
        "closed_at": datetime.utcnow().isoformat(),
        "code": code,
        "reason": reason or ("Abnormal closure / network cut" if code == 1006 else "Normal close" if code == 1000 else "Connection closed"),
        "cart_id": cart_id,
        "cart_number": cart_number
    }
    cart_close_events[cart_id].appendleft(event)
    logger.info(f"[{cart_number}] Logged WebSocket close event: code={code}, reason='{event['reason']}'")

def get_recent_close_events(cart_id: str) -> List[dict]:
    """Retrieve last 20 WebSocket close events for a cart."""
    return list(cart_close_events.get(cart_id, []))

def record_judgement_memory(rss_mb: float, active: bool = False):
    """Record peak memory RSS during a verification judgement."""
    global _peak_judgement_memory_mb, _is_judging_active
    _is_judging_active = active
    if rss_mb > _peak_judgement_memory_mb:
        _peak_judgement_memory_mb = round(rss_mb, 1)

def get_judgement_memory_metrics() -> dict:
    """Return live peak judgement memory metrics for /admin/system-health."""
    return {
        "memory_peak_judgement_mb": _peak_judgement_memory_mb,
        "memory_judgement_active": _is_judging_active
    }

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

async def release_idle_sessions(
    db: Session,
    now: Optional[datetime] = None,
    empty_timeout_minutes: Optional[float] = None,
    active_timeout_minutes: Optional[float] = None,
) -> List[str]:
    """
    End ACTIVE sessions that have been idle beyond configured thresholds:
    - Empty session (0 non-removed items): IDLE_EMPTY_SESSION_MINUTES (default 30 min)
    - Non-empty session (>=1 item, no checkout): IDLE_ACTIVE_SESSION_MINUTES (default 120 min)
    Writes an AuditLog entry, resolves open alerts, frees the cart, and notifies shopper via WebSocket.
    """
    import json
    from app.config import settings
    from app.models.session import CartSession, CartItem
    from app.models.alert import Alert
    from app.models.transaction import AuditLog

    if now is None:
        now = datetime.utcnow()

    empty_mins = empty_timeout_minutes if empty_timeout_minutes is not None else float(
        getattr(settings, "IDLE_EMPTY_SESSION_MINUTES", 30.0)
    )
    active_mins = active_timeout_minutes if active_timeout_minutes is not None else float(
        getattr(settings, "IDLE_ACTIVE_SESSION_MINUTES", 120.0)
    )

    released_ids: List[str] = []
    active_sessions = db.query(CartSession).filter(CartSession.status == "ACTIVE").all()

    for sess in active_sessions:
        items = db.query(CartItem).filter(
            CartItem.session_id == sess.id,
            CartItem.status != "REMOVED",
        ).all()

        last_activity = sess.started_at or now
        for itm in items:
            if itm.scanned_at and itm.scanned_at > last_activity:
                last_activity = itm.scanned_at
            if itm.verified_at and itm.verified_at > last_activity:
                last_activity = itm.verified_at

        idle_seconds = max(0.0, (now - last_activity).total_seconds())
        limit_seconds = (empty_mins * 60.0) if len(items) == 0 else (active_mins * 60.0)

        if idle_seconds < limit_seconds:
            continue

        reason = (
            f"Idle empty session released after {idle_seconds / 60.0:.1f} min (limit {empty_mins:.0f} min)."
            if len(items) == 0
            else f"Idle active session with {len(items)} item(s) released after {idle_seconds / 60.0:.1f} min (limit {active_mins:.0f} min)."
        )

        sess.status = "ENDED"
        sess.ended_at = now

        open_alerts = db.query(Alert).filter(
            Alert.session_id == sess.id,
            Alert.status == "OPEN",
        ).all()
        for al in open_alerts:
            al.status = "RESOLVED"
            al.resolved_at = now
            al.resolution_notes = reason

        cart = db.query(Cart).filter(Cart.id == sess.cart_id).first()
        if cart and cart.status != "NEEDS_REFERENCE":
            cart.status = "IDLE"

        db.add(AuditLog(
            user_id=None,
            action="IDLE_SESSION_RELEASED",
            entity_type="SESSION",
            entity_id=sess.id,
            details_json=json.dumps({
                "session_id": sess.id,
                "cart_id": sess.cart_id,
                "cart_number": cart.cart_number if cart else None,
                "item_count": len(items),
                "idle_minutes": round(idle_seconds / 60.0, 2),
                "reason": reason,
                "released_at": now.isoformat(),
            }),
            created_at=now,
        ))
        db.commit()
        released_ids.append(sess.id)
        logger.info(f"Released idle session {sess.id} on cart {sess.cart_id}: {reason}")

        await ws_manager.broadcast_to_cart(sess.cart_id, "SESSION_ENDED_IDLE", {
            "session_id": sess.id,
            "cart_id": sess.cart_id,
            "reason": reason,
            "message": "Your shopping session ended due to inactivity.",
        })
        await ws_manager.broadcast_to_admin("CART_STATUS_CHANGE", {
            "cart_id": sess.cart_id,
            "cart_number": cart.cart_number if cart else sess.cart_id,
            "status": cart.status if cart else "IDLE",
            "session_id": None,
        })

    return released_ids


async def run_camera_watchdog(check_interval_seconds: int = 2, timeout_seconds: int = 15):
    """
    Background watchdog task that maintains cart camera status and releases idle sessions.
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
                await release_idle_sessions(db=db)
            finally:
                db.close()
        except asyncio.CancelledError:
            logger.info("Cart camera watchdog task cancelled.")
            break
        except Exception as e:
            logger.error(f"Error in camera watchdog loop: {e}")
