import os
import logging
import hashlib
import hmac
from sqlalchemy.orm import Session
from app.config import settings
from app.models.user import User
from app.models.cart import Cart
from app.models.product import Product, ProductEmbedding
from app.models.transaction import AuditLog, MaintenanceFlag
from app.utils.security import hash_password, verify_password

logger = logging.getLogger("smartcart.seed")

def generate_cart_signature(cart_number: str, qr_token: str) -> str:
    """Generate deterministic HMAC signature for cart connect link."""
    msg = f"{cart_number}:{qr_token}".encode("utf-8")
    return hmac.new(settings.QR_SIGNING_SECRET.encode("utf-8"), msg, hashlib.sha256).hexdigest()[:16]

def purge_fake_vectors_once(db: Session):
    """
    ONE-TIME purge of legacy fake vectors (32x32 color averages and placeholder seeds).
    Uses 'fake_vectors_purged_v1' maintenance flag so it executes only once.
    All real vectors enrolled thereafter survive every restart and redeploy.
    """
    FLAG_NAME = "fake_vectors_purged_v1"
    try:
        flag = db.query(MaintenanceFlag).filter(MaintenanceFlag.flag_name == FLAG_NAME).first()
        if flag:
            logger.info(f"Maintenance flag '{FLAG_NAME}' already applied. Skipping purge; real vectors preserved.")
            return

        count = db.query(ProductEmbedding).count()
        if count > 0:
            deleted_count = db.query(ProductEmbedding).delete(synchronize_session=False)
            logger.info(f"Purged {deleted_count} legacy vectors from ProductEmbedding table (vectors_count now 0).")
        else:
            logger.info("ProductEmbedding table is already empty (vectors_count = 0).")

        # Purge legacy local vector disk cache
        cache_path = os.path.join(settings.BASE_DIR, "models_storage", "vector_cache.json")
        if os.path.exists(cache_path):
            try:
                os.remove(cache_path)
                logger.info("Purged legacy vector_cache.json from disk.")
            except Exception:
                pass

        # Record one-time flag in database
        db.add(MaintenanceFlag(
            flag_name=FLAG_NAME,
            details=f"Purged legacy fake vectors ({count} rows deleted). Reset catalog to needs re-enrollment."
        ))
        db.commit()
        logger.info(f"Maintenance flag '{FLAG_NAME}' committed. This purge will never run again.")

    except Exception as e:
        logger.error(f"Error executing one-time vector purge: {e}")
        db.rollback()

def audit_insecure_admins_once(db: Session):
    """
    ONE-TIME security audit to neutralize accounts accepting insecure default passwords:
    'Admin@123', 'admin123', 'Admin123', 'admin', 'password'.
    Reconciles 'insecure_admin_audited_v1' and 'insecure_passwords_checked_v1' flags
    so expensive bcrypt checks run only once and neither alias triggers a second run.
    Safely handles foreign keys (deactivates if related rows exist; deletes otherwise).
    """
    INSECURE_PASSWORD_FLAGS = ["insecure_admin_audited_v1", "insecure_passwords_checked_v1"]
    insecure_passwords = ["Admin@123", "admin123", "Admin123", "admin", "password"]
    try:
        flag = db.query(MaintenanceFlag).filter(MaintenanceFlag.flag_name.in_(INSECURE_PASSWORD_FLAGS)).first()
        if flag:
            logger.info(f"Maintenance flag '{flag.flag_name}' already applied. Skipping bcrypt audit.")
            # Ensure both aliases exist for full consistency
            for alias in INSECURE_PASSWORD_FLAGS:
                if not db.query(MaintenanceFlag).filter(MaintenanceFlag.flag_name == alias).first():
                    db.add(MaintenanceFlag(flag_name=alias, details=flag.details))
            db.commit()
            return

        users = db.query(User).all()
        neutralized_count = 0
        for u in users:
            matched_pw = None
            for plain_pw in insecure_passwords:
                try:
                    if verify_password(plain_pw, u.password_hash):
                        matched_pw = plain_pw
                        break
                except Exception:
                    continue

            if matched_pw:
                logger.warning(
                    f"SECURITY ACTION: User '{u.email}' (ID: {u.id}, Role: {u.role}) "
                    f"accepts known insecure password '{matched_pw}'."
                )
                # Check for foreign key references in audit_logs before deleting
                has_audit_logs = db.query(AuditLog).filter(AuditLog.user_id == u.id).count() > 0
                if has_audit_logs:
                    u.is_active = False
                    u.password_hash = "DISABLED_INSECURE_ACCOUNT"
                    logger.info(f"User '{u.email}' has related audit records; deactivated and invalidated password.")
                else:
                    db.delete(u)
                    logger.info(f"Deleted user '{u.email}'.")
                neutralized_count += 1

        for alias in INSECURE_PASSWORD_FLAGS:
            db.add(MaintenanceFlag(
                flag_name=alias,
                details=f"Audited and neutralized {neutralized_count} insecure user accounts."
            ))
        db.commit()
        logger.info(f"Maintenance flags {INSECURE_PASSWORD_FLAGS} committed. Bcrypt audit will not run on future boots.")

    except Exception as e:
        logger.error(f"Error during security audit: {e}")
        db.rollback()

def seed_database(db: Session):
    """
    Seed production database:
    1. Executes one-time vector purge (guarded by MaintenanceFlag).
    2. Executes one-time insecure password audit (guarded by MaintenanceFlag).
    3. Provisions admin ONLY from ADMIN_EMAIL & ADMIN_PASSWORD environment variables.
    4. Seeds initial test carts and catalog if empty.
    """
    # 1. One-time legacy vectors purge
    purge_fake_vectors_once(db)

    # 2. One-time insecure accounts audit
    audit_insecure_admins_once(db)

    # 3. Seed Initial Admin Account from Environment Variables
    admin_email = os.getenv("ADMIN_EMAIL")
    admin_password = os.getenv("ADMIN_PASSWORD")

    if admin_email and admin_password:
        clean_email = admin_email.strip().lower()
        existing_user = db.query(User).filter(User.email.ilike(clean_email)).first()
        if not existing_user:
            new_admin = User(
                email=clean_email,
                password_hash=hash_password(admin_password.strip()),
                full_name="Store Administrator",
                role="ADMIN",
                is_active=True
            )
            db.add(new_admin)
            db.commit()
            logger.info(f"Administrator account '{clean_email}' provisioned from environment variables.")
        else:
            # Sync existing admin password with ADMIN_PASSWORD env var
            existing_user.password_hash = hash_password(admin_password.strip())
            existing_user.is_active = True
            db.commit()
            logger.info(f"Administrator account '{clean_email}' password updated from ADMIN_PASSWORD.")
    else:
        if db.query(User).count() == 0:
            logger.warning(
                "No ADMIN_EMAIL / ADMIN_PASSWORD environment variables found, and no users exist in database. "
                "Set ADMIN_EMAIL and ADMIN_PASSWORD in Render/environment to bootstrap admin access."
            )

    # 2. Seed 3 Test Carts (CART-001, CART-002, CART-003) only if table is empty
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
                    camera_status="OFFLINE"  # Start OFFLINE until real camera connects
                )
            )
        db.add_all(carts)
        db.commit()
        logger.info("Seeded 3 initial smart cart records with OFFLINE camera status.")

    # 3. Seed Products only if catalog is completely empty
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

        # Seed products with NO fake embeddings - requires real 360 scan enrollment
        for p_data in sample_products:
            prod = Product(**p_data)
            db.add(prod)

        db.commit()
        logger.info(f"Seeded {len(sample_products)} clean catalog products (embeddings pending 360 scan).")
