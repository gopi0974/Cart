import uuid
import secrets
from datetime import datetime
from sqlalchemy import Column, String, Float, Integer, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from app.database import Base

class CartSession(Base):
    """Active shopping session paired with a physical cart."""
    __tablename__ = "cart_sessions"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    cart_id = Column(String(36), ForeignKey("carts.id"), nullable=False, index=True)
    session_token = Column(String(64), nullable=True, index=True, default=lambda: secrets.token_urlsafe(32))
    customer_phone = Column(String(20), nullable=True)
    status = Column(String(20), nullable=False, default="ACTIVE", index=True)  # ACTIVE, COMPLETED, ABANDONED
    started_at = Column(DateTime, default=datetime.utcnow)
    ended_at = Column(DateTime, nullable=True)
    
    subtotal_amount = Column(Float, default=0.0)
    total_tax = Column(Float, default=0.0)
    total_discount = Column(Float, default=0.0)
    total_amount = Column(Float, default=0.0)
    item_count = Column(Integer, default=0)

    # Relationships
    cart = relationship("Cart", back_populates="sessions")
    items = relationship("CartItem", back_populates="session", cascade="all, delete-orphan")
    transaction = relationship("Transaction", back_populates="session", uselist=False)

class CartItem(Base):
    """Specific product scanned or placed in the cart during a session."""
    __tablename__ = "cart_items"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id = Column(String(36), ForeignKey("cart_sessions.id"), nullable=False, index=True)
    product_id = Column(String(36), ForeignKey("products.id"), nullable=False, index=True)
    quantity = Column(Integer, default=1)
    unit_price = Column(Float, nullable=False)
    
    # PENDING: User scanned barcode; waiting for cart camera verification
    # VERIFIED: AI camera confirmed correct item placed in cart
    # WARNING: Wrong item, needs reposition, or unscanned
    # NEEDS_STAFF_CHECK: Camera withheld frame or cannot verify automatically, staff approval required
    # REMOVING: Item taken out or being removed
    # REMOVED_PENDING_RESCAN: Camera confirmed removal, waiting for shopper barcode rescan
    # REMOVED: Item taken out and confirmed removed from bill
    status = Column(String(30), nullable=False, default="PENDING", index=True)
    previous_status = Column(String(30), nullable=True, default="PENDING")
    warning_reason = Column(String(100), nullable=True)
    
    scanned_at = Column(DateTime, default=datetime.utcnow)
    verified_at = Column(DateTime, nullable=True)
    confidence_score = Column(Float, nullable=True)
    top1_score = Column(Float, nullable=True)
    top2_score = Column(Float, nullable=True)
    matched_product_id = Column(String(36), ForeignKey("products.id"), nullable=True)
    verification_evidence_url = Column(Text, nullable=True)

    session = relationship("CartSession", back_populates="items")
    product = relationship("Product", foreign_keys=[product_id], back_populates="cart_items")
    matched_product = relationship("Product", foreign_keys=[matched_product_id])


class VerificationDecision(Base):
    """
    Immutable audit record of every AI camera verification event and decision.
    Tracks exact top-1 and top-2 scores, matched product, scanned product,
    high/low confidence thresholds active at decision time, and evidence crop path.
    """
    __tablename__ = "verification_decisions"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    cart_id = Column(String(36), nullable=False, index=True)
    session_id = Column(String(36), nullable=True, index=True)
    item_id = Column(String(36), nullable=True, index=True)
    decision = Column(String(50), nullable=False, index=True)  # VERIFIED, REPOSITION_PROMPT, WRONG_ITEM, ESCALATE_ADMIN_REVIEW, UNSCANNED_DETECTED, FACE_DETECTED_WITHHELD, CONFIRMED_REMOVED, STILL_IN_CART
    scanned_barcode = Column(String(50), nullable=True)
    scanned_product_name = Column(String(255), nullable=True)
    matched_product_id = Column(String(36), nullable=True)
    matched_product_name = Column(String(255), nullable=True)
    top1_score = Column(Float, nullable=True)
    top2_score = Column(Float, nullable=True)
    threshold_high = Column(Float, nullable=False)
    threshold_low = Column(Float, nullable=False)
    evidence_path = Column(Text, nullable=True)
    preprocessing_version = Column(String(50), nullable=False, default="v2_bilinear_224")
    details_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
