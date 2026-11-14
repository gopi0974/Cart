from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel

class PairSessionRequest(BaseModel):
    qr_token: Optional[str] = None
    customer_phone: Optional[str] = None
    signature: Optional[str] = None
    cart_number: Optional[str] = None


class CartItemResponse(BaseModel):
    id: str
    product_id: str
    product_name: str
    product_barcode: str
    product_image_url: Optional[str] = None
    brand: str
    category: str
    quantity: int
    unit_price: float
    status: str  # PENDING, VERIFIED, WARNING_MISMATCH, WARNING_UNSCANNED, REMOVED
    scanned_at: datetime
    verified_at: Optional[datetime] = None
    confidence_score: Optional[float] = None
    verification_evidence_url: Optional[str] = None
    pending_reason: Optional[str] = None

    class Config:
        from_attributes = True

class ActiveWarning(BaseModel):
    type: str  # UNSCANNED_ITEM, MISMATCH_ITEM, REMOVAL_WITHOUT_RESCAN, ITEM_REMOVING, REMOVED_PENDING_RESCAN
    message: str
    target_barcode: Optional[str] = None
    action_required: str
    item_id: Optional[str] = None
    product_name: Optional[str] = None

class SessionResponse(BaseModel):
    id: str
    cart_id: str
    cart_number: str
    session_token: Optional[str] = None
    camera_status: str = "ONLINE"
    status: str
    started_at: datetime
    subtotal_amount: float
    total_tax: float
    total_discount: float
    total_amount: float
    item_count: int
    items: List[CartItemResponse] = []
    active_warnings: List[ActiveWarning] = []
    can_checkout: bool = True

    class Config:
        from_attributes = True

class ScanItemRequest(BaseModel):
    barcode: str

class RescanRemoveRequest(BaseModel):
    barcode: str

class VerifyRemovalRequest(BaseModel):
    image_data_url: Optional[str] = None
