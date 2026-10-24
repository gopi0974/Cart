from datetime import datetime
from typing import Optional, Dict, Any, List
import hmac
import hashlib
from sqlalchemy.orm import Session
from app.config import settings
from app.models.cart import Cart
from app.models.session import CartSession, CartItem
from app.models.product import Product
from app.models.alert import Alert
from app.websocket.manager import ws_manager
from app.services.alert_service import AlertService
from app.ai.verification_engine import verification_engine

class SessionService:
    @staticmethod
    def recalculate_session_totals(db: Session, session: CartSession):
        """Recalculate subtotal, tax, and total for active verified/pending items."""
        active_items = db.query(CartItem).filter(
            CartItem.session_id == session.id,
            CartItem.status.in_(["PENDING", "VERIFIED", "WARNING_MISMATCH", "WARNING_UNSCANNED", "REMOVING", "REMOVED_PENDING_RESCAN"])
        ).all()

        subtotal = 0.0
        total_tax = 0.0
        item_count = 0

        for itm in active_items:
            product = itm.product
            item_price = product.discount_price if product.discount_price else product.price
            item_total = item_price * itm.quantity
            tax = item_total * (product.tax_rate / 100.0)
            
            subtotal += item_total
            total_tax += tax
            item_count += itm.quantity

        session.subtotal_amount = round(subtotal, 2)
        session.total_tax = round(total_tax, 2)
        discount = session.total_discount if session.total_discount else 0.0
        session.total_amount = max(0.0, round(subtotal + total_tax - discount, 2))
        session.item_count = item_count
        db.flush()

    @staticmethod
    async def pair_cart(
        db: Session,
        qr_token: str,
        customer_phone: Optional[str] = None,
        signature: Optional[str] = None,
        cart_number: Optional[str] = None
    ) -> CartSession:
        """Pair mobile phone with a physical cart, verifying HMAC signature and single active session policy."""
        # 1. Lookup cart
        cart = db.query(Cart).filter(Cart.qr_code_token == qr_token).first()
        if not cart:
            c_num = (cart_number or qr_token).upper().strip()
            cart = db.query(Cart).filter(Cart.cart_number == c_num).first()
            if not cart:
                raise ValueError("Invalid QR code or Cart Number.")

        # 2. Reject disabled carts
        if not cart.is_enabled:
            raise ValueError(f"Cart '{cart.cart_number}' is currently disabled by store management.")

        # 3. Cryptographic HMAC signature check (if signature provided)
        if signature:
            expected_sig = hmac.new(
                settings.QR_SIGNING_SECRET.encode("utf-8"),
                f"{cart.cart_number}:{cart.qr_code_token}".encode("utf-8"),
                hashlib.sha256
            ).hexdigest()[:16]
            if not hmac.compare_digest(signature, expected_sig):
                raise ValueError("Security verification failed: Invalid or tampered cart QR signature.")

        # 4. Enforce ONE active session per cart rule
        existing_session = db.query(CartSession).filter(
            CartSession.cart_id == cart.id,
            CartSession.status == "ACTIVE"
        ).first()

        if existing_session:
            # If same customer is reconnecting, allow resume
            if customer_phone and existing_session.customer_phone == customer_phone:
                return existing_session
            # Block second shopper from pairing while first shopper is active
            raise ValueError(f"Cart '{cart.cart_number}' is currently occupied by an active shopper. Only one active session is allowed per cart.")

        # 5. Create new shopping session
        session = CartSession(
            cart_id=cart.id,
            customer_phone=customer_phone,
            status="ACTIVE"
        )
        db.add(session)
        cart.status = "ACTIVE"
        cart.last_heartbeat = datetime.utcnow()
        db.commit()
        db.refresh(session)

        # Broadcast cart status change
        await ws_manager.broadcast_to_admin("CART_STATUS_CHANGE", {
            "cart_id": cart.id,
            "cart_number": cart.cart_number,
            "status": "ACTIVE",
            "session_id": session.id
        })

        return session

    @staticmethod
    def get_session_details(db: Session, session_id: str) -> Dict[str, Any]:
        """Fetch complete real-time session state, items, and active warnings."""
        session = db.query(CartSession).filter(CartSession.id == session_id).first()
        if not session:
            raise ValueError("Session not found")

        cart = session.cart
        items = db.query(CartItem).filter(
            CartItem.session_id == session.id,
            CartItem.status != "REMOVED"
        ).order_by(CartItem.scanned_at.desc()).all()

        # Build list of active warnings
        active_warnings = []
        has_pending = False
        has_unverified = False

        for itm in items:
            if itm.status == "PENDING":
                has_pending = True
                has_unverified = True
            elif itm.status == "WARNING_MISMATCH":
                has_unverified = True
                active_warnings.append({
                    "type": "MISMATCH_ITEM",
                    "message": f"Wrong item detected for '{itm.product.name}'. Please verify your scanned item.",
                    "target_barcode": itm.product.barcode,
                    "action_required": "RESCAN_OR_CALL_STAFF"
                })
            elif itm.status == "WARNING_UNSCANNED":
                has_unverified = True
                active_warnings.append({
                    "type": "UNSCANNED_ITEM",
                    "message": "We noticed an item was placed that wasn't scanned. Please scan its barcode.",
                    "target_barcode": None,
                    "action_required": "SCAN_BARCODE"
                })
            elif itm.status == "REMOVING":
                has_unverified = True
                active_warnings.append({
                    "type": "ITEM_REMOVING",
                    "message": f"Take '{itm.product.name}' out of the cart, then rescan its barcode.",
                    "target_barcode": itm.product.barcode,
                    "action_required": "TAKE_OUT_AND_RESCAN",
                    "item_id": itm.id,
                    "product_name": itm.product.name
                })
            elif itm.status == "REMOVED_PENDING_RESCAN":
                has_unverified = True
                active_warnings.append({
                    "type": "REMOVED_PENDING_RESCAN",
                    "message": f"Item removed. Please rescan its barcode to take it off your bill.",
                    "target_barcode": itm.product.barcode,
                    "action_required": "RESCAN_BARCODE",
                    "item_id": itm.id,
                    "product_name": itm.product.name
                })

        # Check for open removal or unscanned warnings in alerts
        unresolved_alerts = db.query(Alert).filter(
            Alert.session_id == session.id,
            Alert.alert_type.in_(["REMOVAL_WITHOUT_RESCAN", "UNSCANNED_ITEM"]),
            Alert.status == "OPEN"
        ).all()

        for r_alert in unresolved_alerts:
            active_warnings.append({
                "type": r_alert.alert_type,
                "message": r_alert.message,
                "target_barcode": None,
                "action_required": "SCAN_BARCODE" if r_alert.alert_type == "UNSCANNED_ITEM" else "RESCAN_TO_REMOVE"
            })

        is_camera_online = (cart.camera_status == "ONLINE") if cart else False
        can_checkout = (
            len(items) > 0 and
            not has_unverified and
            len(active_warnings) == 0 and
            session.status == "ACTIVE" and
            is_camera_online
        )

        return {
            "session": session,
            "cart": cart,
            "camera_status": cart.camera_status if cart else "OFFLINE",
            "items": items,
            "active_warnings": active_warnings,
            "can_checkout": can_checkout
        }

    @staticmethod
    async def scan_item(db: Session, session_id: str, barcode: str) -> CartItem:
        """User scans a product barcode. Sets item in PENDING state awaiting cart placement."""
        session = db.query(CartSession).filter(CartSession.id == session_id).first()
        if not session or session.status != "ACTIVE":
            raise ValueError("No active shopping session found.")

        product = db.query(Product).filter(Product.barcode == barcode).first()
        if not product:
            raise ValueError(f"Product with barcode '{barcode}' not found in supermarket catalog.")

        # Create cart item with status PENDING
        item = CartItem(
            session_id=session.id,
            product_id=product.id,
            quantity=1,
            unit_price=product.discount_price if product.discount_price else product.price,
            status="PENDING",
            scanned_at=datetime.utcnow()
        )
        db.add(item)
        db.flush()
        SessionService.recalculate_session_totals(db, session)
        db.commit()
        db.refresh(item)

        # Notify mobile app and cart camera agent
        await ws_manager.broadcast_to_cart(session.cart_id, "ITEM_SCANNED_PENDING", {
            "item_id": item.id,
            "product_id": product.id,
            "product_name": product.name,
            "barcode": product.barcode,
            "unit_price": item.unit_price,
            "status": "PENDING",
            "message": "Item scanned! Please place this item in your cart."
        })

        return item

    @staticmethod
    async def verify_item_placement(
        db: Session,
        session_id: str,
        barcode: str,
        confidence: float = 0.94,
        evidence_url: Optional[str] = None
    ) -> Optional[CartItem]:
        """AI cart camera confirms matching item has physically been placed in cart."""
        session = db.query(CartSession).filter(CartSession.id == session_id).first()
        if not session:
            return None

        # Find pending item for this product
        item = db.query(CartItem).join(Product).filter(
            CartItem.session_id == session.id,
            Product.barcode == barcode,
            CartItem.status == "PENDING"
        ).order_by(CartItem.scanned_at.desc()).first()

        if not item:
            return None

        item.status = "VERIFIED"
        item.verified_at = datetime.utcnow()
        item.confidence_score = confidence
        item.verification_evidence_url = evidence_url
        SessionService.recalculate_session_totals(db, session)
        db.commit()
        db.refresh(item)

        # Real-time WebSocket announcement: Item is verified!
        await ws_manager.broadcast_to_cart(session.cart_id, "ITEM_VERIFIED", {
            "item_id": item.id,
            "product_name": item.product.name,
            "barcode": item.product.barcode,
            "status": "VERIFIED",
            "confidence": confidence,
            "subtotal": session.subtotal_amount,
            "total": session.total_amount
        })

        return item

    @staticmethod
    async def flag_mismatch(
        db: Session,
        session_id: str,
        scanned_barcode: str,
        detected_product_name: str,
        evidence_url: Optional[str] = None,
        confidence: float = 0.72
    ):
        """AI detected item placed does not match scanned barcode."""
        session = db.query(CartSession).filter(CartSession.id == session_id).first()
        if not session:
            return

        item = db.query(CartItem).join(Product).filter(
            CartItem.session_id == session.id,
            Product.barcode == scanned_barcode,
            CartItem.status == "PENDING"
        ).order_by(CartItem.scanned_at.desc()).first()

        if item:
            item.status = "WARNING_MISMATCH"
            item.confidence_score = confidence
            item.verification_evidence_url = evidence_url

        db.commit()

        # Create alert and push to mobile and admin
        await AlertService.create_alert(
            db=db,
            cart_id=session.cart_id,
            session_id=session.id,
            alert_type="MISMATCH_ITEM",
            message=f"Scanned '{item.product.name if item else scanned_barcode}' but detected '{detected_product_name}'.",
            severity="HIGH",
            evidence_url=evidence_url,
            create_review_case=True,
            scanned_barcode=scanned_barcode,
            confidence=confidence
        )

        await ws_manager.broadcast_to_cart(session.cart_id, "ITEM_MISMATCH", {
            "message": f"We noticed you placed '{detected_product_name}', but scanned '{item.product.name if item else scanned_barcode}'.",
            "scanned_barcode": scanned_barcode,
            "detected_item": detected_product_name
        })

    @staticmethod
    async def flag_unscanned_item(
        db: Session,
        cart_id: str,
        detected_product_id: Optional[str] = None,
        evidence_url: Optional[str] = None
    ):
        """AI camera detected an item placed in the cart without any prior barcode scan."""
        active_session = db.query(CartSession).filter(
            CartSession.cart_id == cart_id,
            CartSession.status == "ACTIVE"
        ).first()

        product = db.query(Product).filter(Product.id == detected_product_id).first() if detected_product_id else None
        item_label = product.name if product else "Unidentified item"

        if active_session and product:
            # Create a placeholder item in WARNING_UNSCANNED state
            unscanned_item = CartItem(
                session_id=active_session.id,
                product_id=product.id,
                quantity=1,
                unit_price=product.discount_price if product.discount_price else product.price,
                status="WARNING_UNSCANNED",
                verification_evidence_url=evidence_url
            )
            db.add(unscanned_item)
            SessionService.recalculate_session_totals(db, active_session)
            db.commit()

        # Create high-severity incident alert
        await AlertService.create_alert(
            db=db,
            cart_id=cart_id,
            session_id=active_session.id if active_session else None,
            alert_type="UNSCANNED_ITEM",
            message=f"Unscanned item placed in cart: {item_label}",
            severity="HIGH",
            evidence_url=evidence_url,
            create_review_case=True,
            predicted_product_id=product.id if product else None,
            confidence=0.88
        )

        # Send alert banner to Shopper phone
        await ws_manager.broadcast_to_cart(cart_id, "UNSCANNED_ITEM_DETECTED", {
            "message": "We noticed an item that wasn't scanned. Please scan its barcode.",
            "detected_name": item_label
        })

    @staticmethod
    async def flag_item_removal(
        db: Session,
        session_id: str,
        barcode: str,
        evidence_url: Optional[str] = None
    ):
        """AI camera confirmed item was taken out of the cart."""
        session = db.query(CartSession).filter(CartSession.id == session_id).first()
        if not session:
            return

        product = db.query(Product).filter(Product.barcode == barcode).first()
        prod_name = product.name if product else "Item"

        # Create persistent warning alert
        await AlertService.create_alert(
            db=db,
            cart_id=session.cart_id,
            session_id=session.id,
            alert_type="REMOVAL_WITHOUT_RESCAN",
            message=f"Item removed: '{prod_name}'. Rescan barcode to remove from bill.",
            severity="MEDIUM",
            evidence_url=evidence_url
        )

        await ws_manager.broadcast_to_cart(session.cart_id, "ITEM_REMOVAL_DETECTED", {
            "message": f"Item '{prod_name}' removed. Please rescan its barcode to remove it from your bill.",
            "barcode": barcode,
            "product_name": prod_name
        })

    @staticmethod
    async def initiate_item_removal(db: Session, session_id: str, item_id: str) -> CartItem:
        """Shopper taps 'Remove' on an item. Sets item to REMOVING state awaiting physical removal."""
        session = db.query(CartSession).filter(CartSession.id == session_id).first()
        if not session or session.status != "ACTIVE":
            raise ValueError("No active shopping session found.")

        item = db.query(CartItem).filter(CartItem.id == item_id, CartItem.session_id == session.id).first()
        if not item or item.status == "REMOVED":
            raise ValueError("Item not found in your cart.")

        item.status = "REMOVING"
        db.commit()
        db.refresh(item)

        prod_name = item.product.name if item.product else "Item"
        barcode = item.product.barcode if item.product else ""

        await ws_manager.broadcast_to_cart(session.cart_id, "ITEM_REMOVAL_INITIATED", {
            "item_id": item.id,
            "product_name": prod_name,
            "barcode": barcode,
            "status": "REMOVING",
            "message": "Take this item out of the cart, then rescan its barcode."
        })

        return item

    @staticmethod
    async def verify_item_removal(
        db: Session,
        session_id: str,
        item_id: str,
        image_data: Optional[Any] = None
    ) -> Dict[str, Any]:
        """
        Cart Camera AI verification of physical item removal.
        - Verify that the item was actually removed from the cart (not still inside, not covered by hand).
        - If item still in cart: show 'We still see this item in the cart. Please take it out.'
        - If AI uncertain: flags for staff review.
        - When verified: item advances to REMOVED_PENDING_RESCAN.
        """
        session = db.query(CartSession).filter(CartSession.id == session_id).first()
        if not session:
            raise ValueError("Session not found.")

        item = db.query(CartItem).filter(CartItem.id == item_id, CartItem.session_id == session.id).first()
        if not item:
            raise ValueError("Item not found.")

        if item.status == "REMOVED_PENDING_RESCAN":
            return {
                "removed": True,
                "status": "REMOVED_PENDING_RESCAN",
                "message": "Item removed. Please rescan its barcode to take it off your bill.",
                "evidence_url": item.verification_evidence_url
            }

        if item.status == "REMOVED":
            return {
                "removed": True,
                "status": "REMOVED",
                "message": f"'{item.product.name}' has already been removed from cart."
            }

        target_bcode = item.product.barcode if item.product else ""
        eval_res = verification_engine.evaluate_item_removal(
            db=db,
            target_barcode=target_bcode,
            image_data=image_data
        )

        decision = eval_res.get("decision")
        evidence_url = eval_res.get("evidence_url")

        if decision == "CONFIRMED_REMOVED":
            item.status = "REMOVED_PENDING_RESCAN"
            item.verification_evidence_url = evidence_url
            db.commit()
            db.refresh(item)

            await ws_manager.broadcast_to_cart(session.cart_id, "ITEM_REMOVED_AWAITING_RESCAN", {
                "item_id": item.id,
                "product_name": item.product.name,
                "barcode": item.product.barcode,
                "status": "REMOVED_PENDING_RESCAN",
                "message": "Item removed. Please rescan its barcode to take it off your bill.",
                "evidence_url": evidence_url
            })

            return {
                "removed": True,
                "status": "REMOVED_PENDING_RESCAN",
                "message": "Item removed. Please rescan its barcode to take it off your bill.",
                "evidence_url": evidence_url
            }

        elif decision == "STILL_IN_CART":
            return {
                "removed": False,
                "status": "REMOVING",
                "message": "We still see this item in the cart. Please take it out.",
                "evidence_url": evidence_url
            }

        elif decision == "HAND_IN_CART":
            return {
                "removed": False,
                "status": "REMOVING",
                "message": eval_res.get("message", "We see a hand in the cart. Please remove your hand so the camera can verify."),
                "evidence_url": evidence_url
            }

        else:
            # Uncertain / Escalate to Staff Review
            await AlertService.create_alert(
                db=db,
                cart_id=session.cart_id,
                session_id=session.id,
                alert_type="UNCERTAIN_REMOVAL",
                severity="MEDIUM",
                message=f"Cart camera uncertain if '{item.product.name}' was removed from cart.",
                evidence_url=evidence_url,
                create_review_case=True,
                confidence=eval_res.get("confidence", 0.5)
            )
            return {
                "removed": False,
                "status": "REMOVING",
                "uncertain": True,
                "message": "AI is uncertain about item removal. Flagged for staff review.",
                "evidence_url": evidence_url
            }

    @staticmethod
    async def cancel_item_removal(db: Session, session_id: str, item_id: str) -> CartItem:
        """Shopper taps 'Cancel' to keep the item in the cart."""
        session = db.query(CartSession).filter(CartSession.id == session_id).first()
        if not session:
            raise ValueError("Session not found.")

        item = db.query(CartItem).filter(CartItem.id == item_id, CartItem.session_id == session.id).first()
        if not item:
            raise ValueError("Item not found.")

        item.status = "VERIFIED"
        db.commit()
        db.refresh(item)

        await ws_manager.broadcast_to_cart(session.cart_id, "REMOVAL_CANCELLED", {
            "item_id": item.id,
            "product_name": item.product.name,
            "status": "VERIFIED",
            "message": f"Removal cancelled. '{item.product.name}' remains in your cart."
        })

        return item

    @staticmethod
    async def rescan_to_remove(db: Session, session_id: str, barcode: str) -> Dict[str, Any]:
        """User rescans the removed item's barcode to confirm removal and drop from bill."""
        session = db.query(CartSession).filter(CartSession.id == session_id).first()
        if not session:
            raise ValueError("Session not found.")

        # Check if an item is currently pending barcode rescan (or in removing state)
        pending_removal_item = db.query(CartItem).join(Product).filter(
            CartItem.session_id == session.id,
            CartItem.status.in_(["REMOVED_PENDING_RESCAN", "REMOVING"])
        ).first()

        if pending_removal_item:
            # Enforce that the scanned barcode matches the removing item
            if pending_removal_item.product.barcode != barcode:
                raise ValueError(
                    f"This barcode does not match the item you are removing. Please scan {pending_removal_item.product.name}."
                )

            prod_name = pending_removal_item.product.name
            pending_removal_item.status = "REMOVED"
            db.flush()
            SessionService.recalculate_session_totals(db, session)

            # Resolve removal alerts for this session
            open_alerts = db.query(Alert).filter(
                Alert.session_id == session.id,
                Alert.alert_type.in_(["REMOVAL_WITHOUT_RESCAN", "ITEM_REMOVAL", "UNCERTAIN_REMOVAL"]),
                Alert.status == "OPEN"
            ).all()
            for al in open_alerts:
                al.status = "RESOLVED"
                al.resolution_notes = f"Customer rescanned barcode; '{prod_name}' successfully dropped from bill."
                al.resolved_at = datetime.utcnow()

            db.commit()

            # Broadcast cleared warning and updated totals to cart
            await ws_manager.broadcast_to_cart(session.cart_id, "WARNING_CLEARED", {
                "message": f"{prod_name} removed from cart.",
                "product_name": prod_name,
                "subtotal": session.subtotal_amount,
                "total": session.total_amount
            })
            return {
                "status": "SUCCESS",
                "message": f"{prod_name} removed from cart.",
                "product_name": prod_name
            }

        # If no item is explicitly in REMOVED_PENDING_RESCAN or REMOVING,
        # check if item exists with that barcode in other active states
        item = db.query(CartItem).join(Product).filter(
            CartItem.session_id == session.id,
            Product.barcode == barcode,
            CartItem.status.in_(["VERIFIED", "PENDING", "WARNING_UNSCANNED", "WARNING_MISMATCH"])
        ).first()

        if not item:
            raise ValueError(f"No active item with barcode '{barcode}' found in your cart to remove.")

        prod_name = item.product.name
        item.status = "REMOVED"
        db.flush()
        SessionService.recalculate_session_totals(db, session)
        db.commit()

        await ws_manager.broadcast_to_cart(session.cart_id, "WARNING_CLEARED", {
            "message": f"{prod_name} removed from cart.",
            "product_name": prod_name,
            "subtotal": session.subtotal_amount,
            "total": session.total_amount
        })
        return {
            "status": "SUCCESS",
            "message": f"{prod_name} removed from cart.",
            "product_name": prod_name
        }
