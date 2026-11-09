import pytest
from starlette.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi import Request

from app.main import app
from app.database import Base, get_db
from app.models.user import User
from app.models.product import Product, ProductEmbedding
from app.models.transaction import MaintenanceFlag
from app.models.cart import Cart
from app.models.session import CartSession
from app.utils.security import hash_password, create_access_token
from app.api.v1.auth import get_client_ip, login_rate_limiter
from app.utils.cache import catalog_cache
from app.utils.sanitization import sanitize_secrets, SanitizingLogFilter
from app.utils.seed_data import purge_fake_vectors_once, audit_insecure_admins_once
import logging

# In-memory SQLite test database with StaticPool so all threads share memory
TEST_DB_URL = "sqlite:///:memory:"
engine = create_engine(
    TEST_DB_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(scope="function")
def test_db():
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    try:
        # Seed an admin user
        admin = User(
            email="admin@smartcart.internal",
            full_name="Super Admin",
            role="ADMIN",
            password_hash=hash_password("SafeAdminSecret!2026"),
            is_active=True
        )
        db.add(admin)
        db.commit()
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def client(test_db):
    def override_get_db():
        try:
            yield test_db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    catalog_cache.clear()
    login_rate_limiter.clear()
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
    catalog_cache.clear()
    login_rate_limiter.clear()


# 1. Test Client IP Extraction and Rate Limiter
def test_get_client_ip_extracts_first_hop():
    # Simulated Request with X-Forwarded-For proxy chain
    class FakeClient:
        host = "10.0.0.1"

    class FakeRequest:
        def __init__(self, headers, client=None):
            self.headers = headers
            self.client = client

    # Multi-hop proxy chain: first IP is true client
    req1 = FakeRequest(headers={"x-forwarded-for": "203.0.113.195, 10.1.2.3, 10.4.5.6"}, client=FakeClient())
    assert get_client_ip(req1) == "203.0.113.195"

    # Single hop
    req2 = FakeRequest(headers={"x-forwarded-for": "198.51.100.44"}, client=FakeClient())
    assert get_client_ip(req2) == "198.51.100.44"

    # X-Real-IP fallback
    req3 = FakeRequest(headers={"x-real-ip": "192.0.2.77"}, client=FakeClient())
    assert get_client_ip(req3) == "192.0.2.77"

    # Direct connection without headers
    req4 = FakeRequest(headers={}, client=FakeClient())
    assert get_client_ip(req4) == "10.0.0.1"


def test_rate_limiter_keys_on_real_client_ip(client):
    # 5 failed attempts from client IP 203.0.113.195
    ip1 = "203.0.113.195"
    ip2 = "203.0.113.196"

    for _ in range(5):
        resp = client.post(
            "/api/v1/auth/login",
            json={"email": "wrong@test.com", "password": "wrong"},
            headers={"X-Forwarded-For": f"{ip1}, 10.0.0.1"}
        )
        assert resp.status_code == 401

    # 6th attempt from ip1 is rate limited (429)
    resp_blocked = client.post(
        "/api/v1/auth/login",
        json={"email": "other@test.com", "password": "wrong"},
        headers={"X-Forwarded-For": f"{ip1}, 10.0.0.1"}
    )
    assert resp_blocked.status_code == 429
    assert "Too many failed login attempts" in resp_blocked.json()["detail"]

    # Different client IP behind same proxy (ip2) is NOT blocked
    resp_allowed = client.post(
        "/api/v1/auth/login",
        json={"email": "other@test.com", "password": "wrong"},
        headers={"X-Forwarded-For": f"{ip2}, 10.0.0.1"}
    )
    assert resp_allowed.status_code == 401  # Not 429


# 2. Test Catalog Cache Invalidation on Mutations
def test_product_cache_invalidates_immediately(client, test_db):
    admin_token = create_access_token({"sub": "admin@smartcart.internal", "role": "ADMIN"})
    headers = {"Authorization": f"Bearer {admin_token}"}

    # Fetch products initial (empty catalog) -> populates cache
    resp1 = client.get("/api/v1/products")
    assert resp1.status_code == 200
    assert len(resp1.json()) == 0

    # Create new product -> invalidates catalog_cache
    create_payload = {
        "barcode": "8901030000001",
        "name": "Organic Honey 500g",
        "brand": "PureHealth",
        "price": 12.99,
        "category": "Pantry",
        "weight_grams": 500,
        "is_active": True
    }
    resp_create = client.post("/api/v1/products", json=create_payload, headers=headers)
    assert resp_create.status_code == 200
    new_product_id = resp_create.json()["id"]

    # Fetch products again -> must reflect new product immediately without cache lag
    resp2 = client.get("/api/v1/products")
    assert resp2.status_code == 200
    products = resp2.json()
    assert len(products) == 1
    assert products[0]["id"] == new_product_id
    assert products[0]["name"] == "Organic Honey 500g"

    # Update product -> invalidates cache
    update_payload = {"price": 14.50}
    resp_update = client.put(f"/api/v1/products/{new_product_id}", json=update_payload, headers=headers)
    assert resp_update.status_code == 200

    resp3 = client.get("/api/v1/products")
    assert resp3.status_code == 200
    assert resp3.json()[0]["price"] == 14.50

    # Delete product -> invalidates cache
    resp_del = client.delete(f"/api/v1/products/{new_product_id}", headers=headers)
    assert resp_del.status_code == 200

    resp4 = client.get("/api/v1/products")
    assert resp4.status_code == 200
    assert len(resp4.json()) == 0


# 3. Test Maintenance Flags Reconciliation & Idempotency
def test_maintenance_flags_reconciliation_and_idempotency(test_db):
    # Case A: Seed an insecure account
    insecure_user = User(
        email="legacy_admin@smartcart.internal",
        full_name="Legacy Admin",
        role="ADMIN",
        password_hash=hash_password("Admin@123"),
        is_active=True
    )
    test_db.add(insecure_user)
    test_db.commit()

    # Run audit first time: should find and neutralize insecure_user
    audit_insecure_admins_once(test_db)

    # User should be deleted
    u = test_db.query(User).filter(User.email == "legacy_admin@smartcart.internal").first()
    assert u is None

    # Both flag aliases must be stored
    f1 = test_db.query(MaintenanceFlag).filter(MaintenanceFlag.flag_name == "insecure_admin_audited_v1").first()
    f2 = test_db.query(MaintenanceFlag).filter(MaintenanceFlag.flag_name == "insecure_passwords_checked_v1").first()
    assert f1 is not None
    assert f2 is not None

    # Run audit second time: must skip and do nothing
    audit_insecure_admins_once(test_db)

    # Purge fake vectors: run once
    purge_fake_vectors_once(test_db)
    pv = test_db.query(MaintenanceFlag).filter(MaintenanceFlag.flag_name == "fake_vectors_purged_v1").first()
    assert pv is not None

    # Add a real vector
    p = Product(name="Test Apple", barcode="12345", brand="FreshFarm", category="Produce", price=1.0)
    test_db.add(p)
    test_db.commit()
    emb = ProductEmbedding(
        product_id=p.id,
        barcode=p.barcode,
        angle_tag="front",
        embedding_json="[0.1]",
        model_name="openai/clip-vit-base-patch32",
        model_version="v1.0.0-clip",
        vector_dim=512
    )
    test_db.add(emb)
    test_db.commit()
    assert test_db.query(ProductEmbedding).count() == 1

    # Run purge again: must skip because fake_vectors_purged_v1 exists; real vector survives!
    purge_fake_vectors_once(test_db)
    assert test_db.query(ProductEmbedding).count() == 1


# 4. Test WebSocket Log Sanitization & First-Message Auth
def test_websocket_log_query_sanitization():
    raw_log = "GET /ws/admin?token=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.super_secret HTTP/1.1 101"
    sanitized = sanitize_secrets(raw_log)
    assert "token=***" in sanitized
    assert "super_secret" not in sanitized


def test_websocket_admin_first_message_auth(client, test_db):
    admin_token = create_access_token({"sub": "admin@smartcart.internal", "role": "ADMIN"})

    # Connect to /ws/admin with no query param
    with client.websocket_connect("/ws/admin") as ws:
        # Send first message with auth token
        ws.send_json({"type": "auth", "token": admin_token})
        ack = ws.receive_json()
        assert ack.get("type") == "auth_ok"

        # Now send normal ping
        ws.send_text("ping")
        pong = ws.receive_text()
        assert pong == "pong"


def test_websocket_admin_first_message_auth_rejected(client):
    # Connect to /ws/admin with invalid token in first message
    with pytest.raises(Exception):
        with client.websocket_connect("/ws/admin") as ws:
            ws.send_json({"type": "auth", "token": "invalid_jwt_token"})
            # Server closes socket with 1008
            ws.receive_text()
