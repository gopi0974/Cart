import uuid
from datetime import datetime
from sqlalchemy import Column, String, Float, Integer, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from app.database import Base

class CartSession(Base):
    """Active shopping session paired with a physical cart."""
    __tablename__ = "cart_sessions"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    cart_id = Column(String(36), ForeignKey("carts.id"), nullable=False)
    customer_phone = Column(String(20), nullable=True)
    status = Column(String(20), nullable=False, default="ACTIVE")  # ACTIVE, COMPLETED, ABANDONED
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
    session_id = Column(String(36), ForeignKey("cart_sessions.id"), nullable=False)
    product_id = Column(String(36), ForeignKey("products.id"), nullable=False)
    quantity = Column(Integer, default=1)
    unit_price = Column(Float, nullable=False)
    
    # PENDING: User scanned barcode; waiting for cart camera verification
    # VERIFIED: AI camera confirmed correct item placed in cart
    # WARNING_MISMATCH: AI camera detected different item than scanned
    # WARNING_UNSCANNED: Physical item placed without prior scan
    # REMOVED: Item taken out and confirmed removed
    status = Column(String(30), nullable=False, default="PENDING")
    
    scanned_at = Column(DateTime, default=datetime.utcnow)
    verified_at = Column(DateTime, nullable=True)
    confidence_score = Column(Float, nullable=True)
    verification_evidence_url = Column(Text, nullable=True)

    session = relationship("CartSession", back_populates="items")
    product = relationship("Product", back_populates="cart_items")
