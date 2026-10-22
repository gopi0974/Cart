import uuid
from datetime import datetime
from sqlalchemy import Column, String, Float, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from app.database import Base

class Alert(Base):
    """Real-time store incident, theft prevention, or cart health alert."""
    __tablename__ = "alerts"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    cart_id = Column(String(36), ForeignKey("carts.id"), nullable=False)
    session_id = Column(String(36), ForeignKey("cart_sessions.id"), nullable=True)
    alert_type = Column(String(50), nullable=False)  # UNSCANNED_ITEM, MISMATCH_ITEM, REMOVAL_WITHOUT_RESCAN, CAMERA_OCCLUSION, CART_OFFLINE
    severity = Column(String(20), nullable=False, default="MEDIUM")  # LOW, MEDIUM, HIGH, CRITICAL
    message = Column(Text, nullable=False)
    evidence_snapshot_url = Column(Text, nullable=True)
    status = Column(String(20), nullable=False, default="OPEN")  # OPEN, IN_REVIEW, RESOLVED, DISMISSED
    resolved_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    resolution_notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    resolved_at = Column(DateTime, nullable=True)

    cart = relationship("Cart", back_populates="alerts")
    review_case = relationship("ReviewCase", back_populates="alert", uselist=False, cascade="all, delete-orphan")

class ReviewCase(Base):
    """Human-in-the-loop low confidence review item for supermarket staff."""
    __tablename__ = "review_cases"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    alert_id = Column(String(36), ForeignKey("alerts.id"), nullable=False)
    cart_id = Column(String(36), nullable=False)
    scanned_barcode = Column(String(50), nullable=True)
    predicted_product_id = Column(String(36), ForeignKey("products.id"), nullable=True)
    confidence = Column(Float, nullable=False)
    evidence_image_url = Column(Text, nullable=False)
    status = Column(String(20), nullable=False, default="PENDING")  # PENDING, APPROVED, REJECTED
    assigned_to = Column(String(36), ForeignKey("users.id"), nullable=True)
    feedback_saved_for_training = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    alert = relationship("Alert", back_populates="review_case")
    predicted_product = relationship("Product")
