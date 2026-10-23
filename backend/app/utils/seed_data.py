import json
import hashlib
import hmac
from sqlalchemy.orm import Session
from app.config import settings
from app.models.user import User
from app.models.cart import Cart
from app.models.product import Product, ProductImage, ProductEmbedding
from app.models.transaction import ModelVersion
from app.utils.security import hash_password

def generate_cart_signature(cart_number: str, qr_token: str) -> str:
    """Generate deterministic HMAC signature for cart connect link."""
    msg = f"{cart_number}:{qr_token}".encode("utf-8")
    return hmac.new(settings.QR_SIGNING_SECRET.encode("utf-8"), msg, hashlib.sha256).hexdigest()[:16]

def seed_database(db: Session):
    """Seed production database: one admin account, 3 test carts, sample products, and AI model registry."""
    # 1. Seed Admin Accounts
    if db.query(User).count() == 0:
        admin_users = [
            User(
                email="admin@smartcart.ai",
                password_hash=hash_password("Admin@123"),
                full_name="Sarah Jenkins (Store Admin)",
                role="ADMIN"
            ),
            User(
                email="admin@supermart.com",
                password_hash=hash_password("admin123"),
                full_name="Store SuperAdmin",
                role="ADMIN"
            ),
        ]
        db.add_all(admin_users)
        db.commit()

    # 2. Seed 3 Test Carts (CART-001, CART-002, CART-003)
    if db.query(Cart).count() == 0:
        test_carts = [
            ("CART-001", "CART001_SECRET_TOKEN_2026"),
            ("CART-002", "CART002_SECRET_TOKEN_2026"),
            ("CART-003", "CART003_SECRET_TOKEN_2026"),
        ]
        carts = []
        for cart_num, dev_token in test_carts:
            qr_token = f"QR-{cart_num}"
            sig = generate_cart_signature(cart_num, qr_token)
            token_hash = hashlib.sha256(dev_token.encode("utf-8")).hexdigest()
            signed_url = f"{settings.BASE_URL}/user?cart={cart_num}&token={qr_token}&sig={sig}"

            carts.append(
                Cart(
                    cart_number=cart_num,
                    qr_code_token=qr_token,
                    device_token_hash=token_hash,
                    is_enabled=True,
                    signed_connect_url=signed_url,
                    status="IDLE",
                    battery_level=100,
                    camera_status="ONLINE"
                )
            )
        db.add_all(carts)
        db.commit()

    # 3. Seed Products
    if db.query(Product).count() == 0:

        sample_products = [
            {
                "barcode": "8901262010053",
                "name": "Amul Taaza Fresh Toned Milk 1L",
                "brand": "Amul",
                "category": "Dairy",
                "price": 54.00,
                "discount_price": 52.00,
                "weight_grams": 1030,
                "tax_rate": 5.0,
                "stock_quantity": 85,
                "primary_image_url": "https://images.unsplash.com/photo-1550583724-b2692b85b150?w=600&auto=format&fit=crop&q=80",
            },
            {
                "barcode": "7622201745424",
                "name": "Cadbury Dairy Milk Silk Chocolate 150g",
                "brand": "Cadbury",
                "category": "Confectionery",
                "price": 175.00,
                "discount_price": 165.00,
                "weight_grams": 150,
                "tax_rate": 18.0,
                "stock_quantity": 120,
                "primary_image_url": "https://images.unsplash.com/photo-1548907040-4baa42d10919?w=600&auto=format&fit=crop&q=80",
            },
            {
                "barcode": "8906070430018",
                "name": "Epigamia Greek Yogurt Vanilla 120g",
                "brand": "Epigamia",
                "category": "Dairy",
                "price": 60.00,
                "discount_price": None,
                "weight_grams": 120,
                "tax_rate": 5.0,
                "stock_quantity": 40,
                "primary_image_url": "https://images.unsplash.com/photo-1488477181946-6428a0291777?w=600&auto=format&fit=crop&q=80",
            },
            {
                "barcode": "8901491101934",
                "name": "Quaker Rolled White Oats 1kg",
                "brand": "Quaker",
                "category": "Breakfast & Cereals",
                "price": 199.00,
                "discount_price": 185.00,
                "weight_grams": 1000,
                "tax_rate": 5.0,
                "stock_quantity": 60,
                "primary_image_url": "https://images.unsplash.com/photo-1586201375761-83865001e31c?w=600&auto=format&fit=crop&q=80",
            },
            {
                "barcode": "8901058852300",
                "name": "Nescafe Classic Instant Coffee Jar 200g",
                "brand": "Nescafe",
                "category": "Beverages",
                "price": 410.00,
                "discount_price": 389.00,
                "weight_grams": 200,
                "tax_rate": 12.0,
                "stock_quantity": 90,
                "primary_image_url": "https://images.unsplash.com/photo-1559056199-641a0ac8b55e?w=600&auto=format&fit=crop&q=80",
            },
            {
                "barcode": "8902080000014",
                "name": "Tropicana 100% Real Orange Juice 1L",
                "brand": "Tropicana",
                "category": "Beverages",
                "price": 140.00,
                "discount_price": 129.00,
                "weight_grams": 1050,
                "tax_rate": 12.0,
                "stock_quantity": 45,
                "primary_image_url": "https://images.unsplash.com/photo-1613478223719-2ab802602423?w=600&auto=format&fit=crop&q=80",
            },
            {
                "barcode": "8904043924372",
                "name": "Tata Sampann Unpolished Toor Dal 1kg",
                "brand": "Tata Sampann",
                "category": "Groceries & Staples",
                "price": 185.00,
                "discount_price": None,
                "weight_grams": 1000,
                "tax_rate": 0.0,
                "stock_quantity": 110,
                "primary_image_url": "https://images.unsplash.com/photo-1546069901-ba9599a7e63c?w=600&auto=format&fit=crop&q=80",
            },
            {
                "barcode": "8901491001012",
                "name": "Lay's India's Magic Masala Potato Chips 90g",
                "brand": "Lay's",
                "category": "Snacks",
                "price": 40.00,
                "discount_price": None,
                "weight_grams": 90,
                "tax_rate": 12.0,
                "stock_quantity": 200,
                "primary_image_url": "https://images.unsplash.com/photo-1566478989037-eec170784d0b?w=600&auto=format&fit=crop&q=80",
            },
            {
                "barcode": "8901314010543",
                "name": "Colgate MaxFresh Peppermint Gel Toothpaste 150g",
                "brand": "Colgate",
                "category": "Personal Care",
                "price": 115.00,
                "discount_price": 105.00,
                "weight_grams": 150,
                "tax_rate": 18.0,
                "stock_quantity": 75,
                "primary_image_url": "https://images.unsplash.com/photo-1559591937-e106c62ca058?w=600&auto=format&fit=crop&q=80",
            },
            {
                "barcode": "8901396340010",
                "name": "Dettol Original Germ Protection Liquid Handwash 250ml",
                "brand": "Dettol",
                "category": "Household & Hygiene",
                "price": 99.00,
                "discount_price": 89.00,
                "weight_grams": 275,
                "tax_rate": 18.0,
                "stock_quantity": 95,
                "primary_image_url": "https://images.unsplash.com/photo-1584308666744-24d5c474f2ae?w=600&auto=format&fit=crop&q=80",
            }
        ]

        # Seed products and default multi-angle 360 placeholders
        angles = ["FRONT", "BACK", "LEFT", "RIGHT", "TOP", "BOTTOM", "LABEL_CLOSEUP"]
        for p_data in sample_products:
            prod = Product(**p_data)
            db.add(prod)
            db.flush()

            # Add images for angles
            for ang in angles:
                img = ProductImage(
                    product_id=prod.id,
                    image_url=prod.primary_image_url,
                    angle_tag=ang,
                    is_360_scan=True
                )
                db.add(img)

                # Seed mock visual embedding (512-dim normalized vector placeholder)
                emb_vector = [0.05] * 512
                emb = ProductEmbedding(
                    product_id=prod.id,
                    barcode=prod.barcode,
                    angle_tag=ang,
                    embedding_json=json.dumps(emb_vector),
                    embedding_vector=emb_vector,
                    model_version="v1.0.0-dinov2"
                )
                db.add(emb)

        db.commit()

    # 4. Seed Model Version
    if db.query(ModelVersion).count() == 0:
        model_v = ModelVersion(
            version_tag="v1.0.0-dinov2",
            accuracy=0.984,
            false_positive_rate=0.008,
            false_negative_rate=0.008,
            confidence_threshold=0.85,
            is_active=True,
            notes="Foundation model combining YOLOv8n cart entrance tracking with DINOv2 visual signatures."
        )
        db.add(model_v)
        db.commit()
