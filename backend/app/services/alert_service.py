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
        item_id: Optional[str] = None,
        evidence_url: Optional[str] = None,
        create_review_case: bool = False,
        scanned_barcode: Optional[str] = None,
        predicted_product_id: Optional[str] = None,
        confidence: float = 0.5,
        top_candidates: Optional[list] = None
    ) -> Optional[Alert]:
        """Create or update a real-time alert (enforcing at most one open alert per session, item, and type).
        Never creates an alert for an item that is already VERIFIED or staff-approved."""
        import json
        from app.models.session import CartItem

        # Do not create alerts for items already verified or staff-approved
        if item_id:
            target_item = db.query(CartItem).filter(CartItem.id == item_id).first()
            if target_item and (target_item.staff_approved or target_item.status == "VERIFIED"):
                return None
        elif session_id and scanned_barcode:
            clean_b = str(scanned_barcode).strip()
            existing_approved = db.query(CartItem).join(CartItem.product).filter(
                CartItem.session_id == session_id,
                CartItem.product.has(barcode=clean_b),
                (CartItem.staff_approved.is_(True)) | (CartItem.status == "VERIFIED")
            ).first()
            if existing_approved:
                return None

        # De-duplicate: check for existing open alert for (cart, session, item, alert_type)
        query = db.query(Alert).filter(
            Alert.cart_id == cart_id,
            Alert.alert_type == alert_type,
            Alert.status == "OPEN"
        )
        if session_id:
            query = query.filter(Alert.session_id == session_id)
        if item_id:
            query = query.filter(Alert.item_id == item_id)
        else:
            query = query.filter(Alert.item_id.is_(None))

        existing_alert = query.order_by(Alert.created_at.desc()).first()
        if existing_alert:
            existing_alert.message = message
            existing_alert.severity = severity
            if evidence_url:
                existing_alert.evidence_snapshot_url = evidence_url
            db.commit()
            db.refresh(existing_alert)
            return existing_alert

        alert = Alert(
            cart_id=cart_id,
            session_id=session_id,
            item_id=item_id,
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
                top_candidates_json=json.dumps(top_candidates) if top_candidates else None,
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

        from app.models.session import CartItem
        from app.services.session_service import SessionService

        alert.status = action
        alert.resolved_by = user_id
        alert.resolution_notes = notes
        alert.resolved_at = datetime.utcnow()

        # Find associated cart item to mark as staff-approved and verified
        target_item = None
        if alert.item_id:
            target_item = db.query(CartItem).filter(CartItem.id == alert.item_id).first()
        
        # If not linked by item_id, check review case barcode or session items
        if not target_item and alert.review_case and alert.review_case.scanned_barcode and alert.session_id:
            clean_b = str(alert.review_case.scanned_barcode).strip()
            target_item = db.query(CartItem).join(CartItem.product).filter(
                CartItem.session_id == alert.session_id,
                CartItem.product.has(barcode=clean_b)
            ).order_by(CartItem.scanned_at.desc()).first()

        if not target_item and alert.session_id:
            target_item = db.query(CartItem).filter(
                CartItem.session_id == alert.session_id,
                CartItem.status.in_(["NEEDS_STAFF_CHECK", "PENDING", "WARNING", "WARNING_MISMATCH"])
            ).order_by(CartItem.scanned_at.desc()).first()

        if target_item:
            if not alert.item_id:
                alert.item_id = target_item.id
            target_item.status = "VERIFIED"
            target_item.staff_approved = True
            target_item.staff_approved_at = datetime.utcnow()
            target_item.staff_approved_by = user_id
            target_item.verified_at = datetime.utcnow()
            target_item.warning_reason = None
            if target_item.confidence_score is None:
                target_item.confidence_score = 1.0
            
            # Recalculate session totals
            if target_item.session:
                SessionService.recalculate_session_totals(db, target_item.session)

        # Update associated review case if pending
        review_case = db.query(ReviewCase).filter(ReviewCase.alert_id == alert.id).first()
        if review_case and review_case.status == "PENDING":
            review_case.status = "APPROVED" if action in ("RESOLVED", "APPROVED") else "REJECTED"
            if user_id:
                review_case.assigned_to = user_id

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
        if target_item:
            db.refresh(target_item)

        # Invalidate / update tracker for camera handler
        try:
            from app.websocket.device_handler import get_tracker
            tracker = get_tracker(alert.cart_id)
            if alert.session_id:
                remaining_pending = db.query(CartItem).filter(
                    CartItem.session_id == alert.session_id,
                    CartItem.status.in_(["PENDING", "NEEDS_STAFF_CHECK"]),
                    CartItem.staff_approved.is_(False)
                ).count()
                tracker.has_pending_items = (remaining_pending > 0)
                if not tracker.has_pending_items:
                    tracker.last_pending_item_id = None
        except Exception:
            pass

        # 1. Notify admin portal
        await ws_manager.broadcast_to_admin("ALERT_RESOLVED", {
            "alert_id": alert.id,
            "cart_id": alert.cart_id,
            "status": alert.status
        })

        # 2. Push ITEM_VERIFIED and ALERT_CLEARED to shopper session WebSocket
        session_id = alert.session_id or (target_item.session_id if target_item else None)
        subtotal = 0.0
        total_items = 0
        can_checkout = False
        if session_id:
            try:
                cart_state = SessionService.get_cart_state(db, alert.cart_id)
                sess = cart_state.get("session")
                subtotal = sess.subtotal_amount if sess else 0.0
                total_items = sess.total_items_count if sess else 0
                can_checkout = cart_state.get("can_checkout", False)
            except Exception:
                pass

        if target_item:
            await ws_manager.broadcast_to_cart(alert.cart_id, "ITEM_VERIFIED", {
                "item_id": target_item.id,
                "product_name": target_item.product.name,
                "barcode": target_item.product.barcode,
                "status": "VERIFIED",
                "staff_approved": True,
                "confidence": target_item.confidence_score or 1.0,
                "subtotal": subtotal,
                "total_items": total_items,
                "can_checkout": can_checkout,
                "message": f"Approved by staff ({target_item.product.name})."
            })

        await ws_manager.broadcast_to_cart(alert.cart_id, "ALERT_CLEARED", {
            "alert_id": alert.id,
            "alert_type": alert.alert_type,
            "item_id": target_item.id if target_item else alert.item_id,
            "message": f"Alert cleared by staff ({target_item.product.name if target_item else alert.alert_type})."
        })

        return alert
