from datetime import datetime
from typing import Optional
from sqlalchemy.orm import Session
from app.models.alert import Alert, ReviewCase
from app.models.cart import Cart
from app.websocket.manager import ws_manager

class AlertService:
    @staticmethod
    async def create_alert(
        db: Session,
        cart_id: str,
        alert_type: str,
        message: str,
        severity: str = "MEDIUM",
        session_id: Optional[str] = None,
        evidence_url: Optional[str] = None,
        create_review_case: bool = False,
        scanned_barcode: Optional[str] = None,
        predicted_product_id: Optional[str] = None,
        confidence: float = 0.5
    ) -> Alert:
        """Create a real-time alert and notify admin channels instantly."""
        alert = Alert(
            cart_id=cart_id,
            session_id=session_id,
            alert_type=alert_type,
            severity=severity,
            message=message,
            evidence_snapshot_url=evidence_url,
            status="OPEN"
        )
        db.add(alert)
        
        # Update physical cart status to ALERT
        cart = db.query(Cart).filter(Cart.id == cart_id).first()
        if cart:
            cart.status = "ALERT"

        db.flush()

        # Create human-in-the-loop review case if low confidence
        if create_review_case:
            case = ReviewCase(
                alert_id=alert.id,
                cart_id=cart_id,
                scanned_barcode=scanned_barcode,
                predicted_product_id=predicted_product_id,
                confidence=confidence,
                evidence_image_url=evidence_url or "https://images.unsplash.com/photo-1542838132-92c53300491e?w=600&auto=format&fit=crop&q=80",
                status="PENDING"
            )
            db.add(case)
            db.flush()

        db.commit()
        db.refresh(alert)

        # Broadcast incident to admin portal
        cart_number = cart.cart_number if cart else cart_id
        await ws_manager.broadcast_to_admin("NEW_INCIDENT_ALERT", {
            "id": alert.id,
            "cart_id": cart.id if cart else cart_id,
            "cart_number": cart_number,
            "alert_type": alert.alert_type,
            "severity": alert.severity,
            "message": alert.message,
            "evidence_snapshot_url": alert.evidence_snapshot_url,
            "created_at": alert.created_at.isoformat()
        })

        return alert

    @staticmethod
    async def resolve_alert(
        db: Session,
        alert_id: str,
        user_id: Optional[str],
        notes: str,
        action: str = "RESOLVED"
    ) -> Optional[Alert]:
        alert = db.query(Alert).filter(Alert.id == alert_id).first()
        if not alert:
            return None

        alert.status = action
        alert.resolved_by = user_id
        alert.resolution_notes = notes
        alert.resolved_at = datetime.utcnow()

        # Check if cart has other open alerts
        remaining_alerts = db.query(Alert).filter(
            Alert.cart_id == alert.cart_id,
            Alert.status == "OPEN",
            Alert.id != alert.id
        ).count()

        cart = db.query(Cart).filter(Cart.id == alert.cart_id).first()
        if cart and remaining_alerts == 0:
            cart.status = "ACTIVE"

        db.commit()
        db.refresh(alert)

        # Notify admin and cart websockets
        await ws_manager.broadcast_to_admin("ALERT_RESOLVED", {
            "alert_id": alert.id,
            "cart_id": alert.cart_id,
            "status": alert.status
        })

        return alert
