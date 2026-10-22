import uuid
from datetime import datetime
from sqlalchemy import Column, String, Float, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from app.database import Base

class Transaction(Base):
    """Payment transaction and finalized digital receipt record."""
    __tablename__ = "transactions"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id = Column(String(36), ForeignKey("cart_sessions.id"), unique=True, nullable=False)
    payment_method = Column(String(50), nullable=False, default="UPI")  # UPI, CARD, SANDBOX
    payment_gateway_ref = Column(String(100), nullable=True)
    amount = Column(Float, nullable=False)
    status = Column(String(20), nullable=False, default="SUCCESS")  # PENDING, SUCCESS, FAILED
    receipt_number = Column(String(50), unique=True, index=True, nullable=False)
    receipt_pdf_url = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    session = relationship("CartSession", back_populates="transaction")

class AuditLog(Base):
    """Immutable audit trail for compliance, product changes, and model actions."""
    __tablename__ = "audit_logs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    action = Column(String(100), nullable=False)
    entity_type = Column(String(50), nullable=False)
    entity_id = Column(String(36), nullable=True)
    details_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class ModelVersion(Base):
    """AI Model checkpoint registry and accuracy tracking."""
    __tablename__ = "model_versions"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    version_tag = Column(String(50), unique=True, nullable=False)
    accuracy = Column(Float, nullable=False, default=0.984)
    false_positive_rate = Column(Float, nullable=False, default=0.008)
    false_negative_rate = Column(Float, nullable=False, default=0.008)
    confidence_threshold = Column(Float, nullable=False, default=0.85)
    is_active = Column(Boolean, default=False)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
