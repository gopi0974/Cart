import uuid
from datetime import datetime
from sqlalchemy import Column, String, Integer, DateTime
from sqlalchemy.orm import relationship
from app.database import Base

class Cart(Base):
    """Smart shopping cart physical device registry."""
    __tablename__ = "carts"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    cart_number = Column(String(20), unique=True, index=True, nullable=False)
    qr_code_token = Column(String(100), unique=True, index=True, nullable=False)
    status = Column(String(20), nullable=False, default="IDLE")  # IDLE, ACTIVE, ALERT, MAINTENANCE
    battery_level = Column(Integer, default=100)
    camera_status = Column(String(20), default="ONLINE")  # ONLINE, DEGRADED, OFFLINE
    last_heartbeat = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    sessions = relationship("CartSession", back_populates="cart", cascade="all, delete-orphan")
    alerts = relationship("Alert", back_populates="cart", cascade="all, delete-orphan")
