import uuid
from datetime import datetime
from sqlalchemy import Column, String, Integer, Text, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from app.database import Base


class ScanJob(Base):
    """
    Background job tracking multi-angle 360-degree product scans.
    Persisted in database so job state survives server restarts.
    """
    __tablename__ = "scan_jobs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    product_id = Column(String(36), ForeignKey("products.id"), nullable=False, index=True)
    status = Column(String(20), nullable=False, default="PENDING", index=True)  # PENDING, PROCESSING, ENROLLED, FAILED
    stage = Column(String(50), nullable=False, default="QUEUED")  # QUEUED, SAVING_FRAMES, REMOVING_BACKGROUND, COMPUTING_VECTORS, SAVING_TO_DATABASE, COMPLETED, FAILED
    stage_message = Column(String(255), nullable=True)  # e.g. "Saving frames 12/48", "Removing background 24/48"
    done = Column(Integer, nullable=False, default=0)
    total = Column(Integer, nullable=False, default=0)
    error = Column(Text, nullable=True)  # Sanitized failure reason
    frame_paths_json = Column(Text, nullable=True)  # JSON-serialized list of saved frame references for safe retry without re-upload
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    product = relationship("Product", backref="scan_jobs")

