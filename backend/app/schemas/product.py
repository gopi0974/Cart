from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel

class ProductImageResponse(BaseModel):
    id: str
    image_url: str
    angle_tag: str
    is_360_scan: bool

    class Config:
        from_attributes = True

class ProductBase(BaseModel):
    barcode: str
    name: str
    brand: str
    category: str
    price: float
    discount_price: Optional[float] = None
    weight_grams: int = 100
    tax_rate: float = 5.0
    stock_quantity: int = 100
    primary_image_url: Optional[str] = None
    is_active: bool = True

class ProductCreate(ProductBase):
    pass

class ProductUpdate(BaseModel):
    name: Optional[str] = None
    brand: Optional[str] = None
    category: Optional[str] = None
    price: Optional[float] = None
    discount_price: Optional[float] = None
    weight_grams: Optional[int] = None
    tax_rate: Optional[float] = None
    stock_quantity: Optional[int] = None
    primary_image_url: Optional[str] = None
    is_active: Optional[bool] = None

class ProductResponse(ProductBase):
    id: str
    created_at: datetime
    images: List[ProductImageResponse] = []
    has_embeddings: bool = False

    class Config:
        from_attributes = True

class BulkUploadResponse(BaseModel):
    success_count: int
    error_count: int
    errors: List[str] = []
