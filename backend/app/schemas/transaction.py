from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel
from app.schemas.session import CartItemResponse

class CheckoutRequest(BaseModel):
    payment_method: str = "UPI"  # UPI, CARD, SANDBOX
    card_token: Optional[str] = None
    upi_id: Optional[str] = None

class ReceiptItemSummary(BaseModel):
    name: str
    quantity: int
    unit_price: float
    total_price: float

class ReceiptResponse(BaseModel):
    id: str
    receipt_number: str
    session_id: str
    cart_number: str
    customer_phone: Optional[str] = None
    payment_method: str
    subtotal: float
    tax_amount: float
    discount_amount: float
    total_paid: float
    items: List[ReceiptItemSummary]
    timestamp: datetime
    store_name: str = "SuperMart Hypermarket - Downtown"
    store_tax_id: str = "GSTIN29AAACB1234F1Z5"

    class Config:
        from_attributes = True
