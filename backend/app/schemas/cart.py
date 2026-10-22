from typing import Optional
from datetime import datetime
from pydantic import BaseModel

class CartCreate(BaseModel):
    cart_number: str

class CartStatusUpdate(BaseModel):
    status: Optional[str] = None
    battery_level: Optional[int] = None
    camera_status: Optional[str] = None

class CartResponse(BaseModel):
    id: str
    cart_number: str
    qr_code_token: str
    status: str
    battery_level: int
    camera_status: str
    last_heartbeat: datetime
    active_session_id: Optional[str] = None
    item_count: Optional[int] = 0
    total_amount: Optional[float] = 0.0

    class Config:
        from_attributes = True
