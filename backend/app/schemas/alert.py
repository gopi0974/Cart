from typing import Optional
from datetime import datetime
from pydantic import BaseModel

class AlertResponse(BaseModel):
    id: str
    cart_id: str
    cart_number: Optional[str] = None
    session_id: Optional[str] = None
    alert_type: str
    severity: str
    message: str
    evidence_snapshot_url: Optional[str] = None
    status: str
    resolved_by: Optional[str] = None
    resolution_notes: Optional[str] = None
    created_at: datetime
    resolved_at: Optional[datetime] = None

    class Config:
        from_attributes = True

class AlertResolutionRequest(BaseModel):
    resolution_notes: str
    action: str = "RESOLVED"  # RESOLVED or DISMISSED

class ReviewCaseResponse(BaseModel):
    id: str
    alert_id: str
    cart_id: str
    cart_number: Optional[str] = None
    scanned_barcode: Optional[str] = None
    scanned_product_name: Optional[str] = None
    scanned_product_image: Optional[str] = None
    predicted_product_id: Optional[str] = None
    predicted_product_name: Optional[str] = None
    confidence: float
    evidence_image_url: str
    status: str
    created_at: datetime

    class Config:
        from_attributes = True

class ReviewDecisionRequest(BaseModel):
    decision: str  # APPROVE or REJECT
    notes: Optional[str] = None
    save_for_training: bool = True
