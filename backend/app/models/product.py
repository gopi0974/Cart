import uuid
from datetime import datetime
from sqlalchemy import Column, String, Float, Integer, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from app.database import Base

try:
    from pgvector.sqlalchemy import Vector
    HAS_PGVECTOR = True
except ImportError:
    HAS_PGVECTOR = False
    Vector = None

class Product(Base):

    """Supermarket inventory product item."""
    __tablename__ = "products"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    barcode = Column(String(50), unique=True, index=True, nullable=False)
    name = Column(String(255), nullable=False)
    brand = Column(String(100), nullable=False)
    category = Column(String(100), nullable=False)
    price = Column(Float, nullable=False)
    discount_price = Column(Float, nullable=True)
    weight_grams = Column(Integer, nullable=False, default=100)
    tax_rate = Column(Float, nullable=False, default=5.0)  # Standard 5% GST
    stock_quantity = Column(Integer, nullable=False, default=100)
    primary_image_url = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    images = relationship("ProductImage", back_populates="product", cascade="all, delete-orphan")
    embeddings = relationship("ProductEmbedding", back_populates="product", cascade="all, delete-orphan")
    cart_items = relationship("CartItem", back_populates="product")

class ProductImage(Base):
    """Catalog and multi-angle 360-scan image captures."""
    __tablename__ = "product_images"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    product_id = Column(String(36), ForeignKey("products.id"), nullable=False)
    image_url = Column(Text, nullable=False)
    angle_tag = Column(String(50), nullable=False)  # FRONT, BACK, LEFT, RIGHT, TOP, BOTTOM, LABEL_CLOSEUP
    is_360_scan = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    product = relationship("Product", back_populates="images")

class ProductEmbedding(Base):
    """Vector representations extracted from 360 images for AI verification."""
    __tablename__ = "product_embeddings"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    product_id = Column(String(36), ForeignKey("products.id"), nullable=False)
    barcode = Column(String(50), index=True, nullable=False)
    angle_tag = Column(String(50), nullable=False)
    embedding_json = Column(Text, nullable=False)  # JSON-serialized list of floats (cross-db compatible)
    embedding_vector = Column(Vector(512), nullable=True) if (HAS_PGVECTOR and Vector is not None) else Column(Text, nullable=True)
    image_path = Column(Text, nullable=True)
    model_name = Column(String(100), nullable=False, default="openai/clip-vit-base-patch32")
    model_version = Column(String(50), nullable=False, default="v1.0.0-clip")
    vector_dim = Column(Integer, nullable=False, default=512)
    created_at = Column(DateTime, default=datetime.utcnow)

    product = relationship("Product", back_populates="embeddings")

