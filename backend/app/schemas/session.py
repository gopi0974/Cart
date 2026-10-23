from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel
from app.schemas.product import ProductResponse

class PairSessionRequest(BaseModel):
    qr_token: str
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

    class Config:
        from_attributes = True

class ActiveWarning(BaseModel):
    type: str  # UNSCANNED_ITEM, MISMATCH_ITEM, REMOVAL_WITHOUT_RESCAN
    message: str
    target_barcode: Optional[str] = None
    action_required: str

class SessionResponse(BaseModel):
    id: str
    cart_id: str
    cart_number: str
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
