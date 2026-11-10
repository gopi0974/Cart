import os
import sys
import hmac
import hashlib
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Ensure backend root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.main import app
from app.config import settings
from app.database import Base, get_db
from app.models.cart import Cart
from app.models.user import User
from app.api.v1.admin import build_signed_connect_url
from app.utils.security import create_access_token, hash_password

# Fast in-memory SQLite database
TEST_DATABASE_URL = "sqlite:///:memory:"
test_engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


def override_get_db():
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(autouse=True)
def setup_test_cart():
    Base.metadata.create_all(bind=test_engine)
    app.dependency_overrides[get_db] = override_get_db

    db = TestingSessionLocal()
    try:
        cart = Cart(
            id="cart-sec-test-uuid",
            cart_number="CART-SEC-01",
            qr_code_token="QR-SECRET-TOKEN-9876",
            is_enabled=True,
            status="IDLE"
        )
        admin = User(
            id="admin-sec-test-uuid",
            email="admin.security@smartcart.internal",
            password_hash=hash_password("AdminPass123!"),
            full_name="Admin Security",
            role="ADMIN",
            is_active=True
        )
        db.add_all([cart, admin])
        db.commit()
    finally:
        db.close()

    yield

    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=test_engine)


def test_qr_link_uses_base_url(monkeypatch):
    """
    QR pairing link must be built strictly from BASE_URL environment variable
    with format: BASE_URL/user/connect?cart=<cart_number>&sig=<HMAC signature>.
    It must not contain a token parameter or hardcoded host.
    """
    monkeypatch.setattr(settings, "BASE_URL", "https://cart-9tds.vercel.app")
    monkeypatch.setattr(settings, "DEMO_MODE", False)

    url = build_signed_connect_url("CART-SEC-01", "QR-SECRET-TOKEN-9876")
    assert url is not None
    assert url.startswith("https://cart-9tds.vercel.app/user/connect?cart=CART-SEC-01&sig=")
    assert "token=" not in url
    assert "localhost" not in url


def test_localhost_is_refused_in_production(monkeypatch):
    """
    In production (DEMO_MODE=false), if BASE_URL is missing or contains localhost/127.0.0.1,
    the server must refuse to generate a QR and surface the exact warning:
    'Set BASE_URL to your public https address'.
    """
    monkeypatch.setattr(settings, "DEMO_MODE", False)

    # 1. Missing BASE_URL
    monkeypatch.setattr(settings, "BASE_URL", "")
    assert build_signed_connect_url("CART-SEC-01", "QR-SECRET-TOKEN-9876") is None

    # 2. Localhost BASE_URL
    monkeypatch.setattr(settings, "BASE_URL", "http://localhost:5173")
    assert build_signed_connect_url("CART-SEC-01", "QR-SECRET-TOKEN-9876") is None

    # 3. 127.0.0.1 BASE_URL
    monkeypatch.setattr(settings, "BASE_URL", "http://127.0.0.1:8000")
    assert build_signed_connect_url("CART-SEC-01", "QR-SECRET-TOKEN-9876") is None

    # 4. /admin/system-health exposes base_url_valid=False and warning
    client = TestClient(app)
    admin_token = create_access_token({"sub": "admin.security@smartcart.internal", "role": "ADMIN"})
    res = client.get("/admin/system-health", headers={"Authorization": f"Bearer {admin_token}"})
    assert res.status_code == 200
    data = res.json()
    assert data["base_url_valid"] is False
    assert data["base_url_warning"] == "Set BASE_URL to your public https address"
    assert data["base_url_host"] in ("127.0.0.1", "localhost", None)


def test_pairing_without_signature_fails_when_demo_mode_false(monkeypatch):
    """
    When DEMO_MODE=false, pairing without a cryptographic HMAC signature
    must be rejected with HTTP 400.
    """
    monkeypatch.setattr(settings, "DEMO_MODE", False)
    client = TestClient(app)

    payload = {
        "cart_number": "CART-SEC-01",
        "qr_token": "QR-SECRET-TOKEN-9876"
    }
    response = client.post("/api/v1/shopper/pair", json=payload)
    assert response.status_code == 400
    assert "Missing HMAC signature" in response.json()["detail"]


def test_pairing_with_invalid_signature_fails(monkeypatch):
    """
    Pairing with a forged or invalid signature must be rejected with HTTP 400
    and a clear user-friendly message.
    """
    monkeypatch.setattr(settings, "DEMO_MODE", False)
    client = TestClient(app)

    payload = {
        "cart_number": "CART-SEC-01",
        "signature": "forged_sig_12345"
    }
    response = client.post("/api/v1/shopper/pair", json=payload)
    assert response.status_code == 400
    assert "invalid or has expired" in response.json()["detail"]


def test_pairing_with_valid_hmac_signature_succeeds(monkeypatch):
    """
    Pairing with the legitimate HMAC signature derived from the cart's physical QR
    must succeed with HTTP 200 when DEMO_MODE=false, accepting cart_number and signature
    without requiring qr_token.
    """
    monkeypatch.setattr(settings, "DEMO_MODE", False)
    client = TestClient(app)

    msg = "CART-SEC-01:QR-SECRET-TOKEN-9876".encode("utf-8")
    valid_sig = hmac.new(settings.QR_SIGNING_SECRET.encode("utf-8"), msg, hashlib.sha256).hexdigest()[:16]

    payload = {
        "cart_number": "CART-SEC-01",
        "signature": valid_sig
    }
    response = client.post("/api/v1/shopper/pair", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["cart_number"] == "CART-SEC-01"
    assert data["status"] == "ACTIVE"
    assert "session_token" in data and len(data["session_token"]) > 16


def test_regenerate_qr_invalidates_old_link(monkeypatch):
    """
    Regenerating a cart QR changes cart.qr_code_token in the database.
    Because the HMAC signature is derived from cart.qr_code_token, the old link
    stops working immediately, and only the new link's signature is accepted.
    """
    monkeypatch.setattr(settings, "DEMO_MODE", False)
    client = TestClient(app)

    # 1. Valid signature for original token
    old_msg = "CART-SEC-01:QR-SECRET-TOKEN-9876".encode("utf-8")
    old_sig = hmac.new(settings.QR_SIGNING_SECRET.encode("utf-8"), old_msg, hashlib.sha256).hexdigest()[:16]

    # 2. Simulate QR token regeneration (e.g. staff clicks Regenerate QR)
    db = TestingSessionLocal()
    try:
        cart = db.query(Cart).filter(Cart.cart_number == "CART-SEC-01").first()
        cart.qr_code_token = "QR-REGENERATED-NEW-TOKEN"
        db.commit()
    finally:
        db.close()

    # 3. Old link attempt MUST be rejected
    res_old = client.post("/api/v1/shopper/pair", json={
        "cart_number": "CART-SEC-01",
        "signature": old_sig
    })
    assert res_old.status_code == 400
    assert "invalid or has expired" in res_old.json()["detail"]

    # 4. New link attempt MUST succeed
    new_msg = "CART-SEC-01:QR-REGENERATED-NEW-TOKEN".encode("utf-8")
    new_sig = hmac.new(settings.QR_SIGNING_SECRET.encode("utf-8"), new_msg, hashlib.sha256).hexdigest()[:16]

    res_new = client.post("/api/v1/shopper/pair", json={
        "cart_number": "CART-SEC-01",
        "signature": new_sig
    })
    assert res_new.status_code == 200
    assert res_new.json()["status"] == "ACTIVE"


def test_cart_already_in_use_is_rejected(monkeypatch):
    """
    When a cart has an ACTIVE shopper session, another shopper cannot pair to it.
    The second pairing attempt is rejected with 400 'occupied by an active shopper'.
    """
    monkeypatch.setattr(settings, "DEMO_MODE", False)
    client = TestClient(app)

    msg = "CART-SEC-01:QR-SECRET-TOKEN-9876".encode("utf-8")
    sig = hmac.new(settings.QR_SIGNING_SECRET.encode("utf-8"), msg, hashlib.sha256).hexdigest()[:16]

    # Shopper 1 pairs
    res1 = client.post("/api/v1/shopper/pair", json={
        "cart_number": "CART-SEC-01",
        "signature": sig,
        "customer_phone": "+919999900001"
    })
    assert res1.status_code == 200

    # Shopper 2 attempts to pair to the same cart
    res2 = client.post("/api/v1/shopper/pair", json={
        "cart_number": "CART-SEC-01",
        "signature": sig,
        "customer_phone": "+919999900002"
    })
    assert res2.status_code == 400
    assert "occupied by an active shopper" in res2.json()["detail"]


def test_pairing_without_signature_permitted_when_demo_mode_true(monkeypatch):
    """
    When DEMO_MODE=true, quick unsigned pairing is permitted for development and testing.
    """
    monkeypatch.setattr(settings, "DEMO_MODE", True)
    client = TestClient(app)

    payload = {
        "cart_number": "CART-SEC-01",
        "qr_token": "QR-SECRET-TOKEN-9876"
    }
    response = client.post("/api/v1/shopper/pair", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["cart_number"] == "CART-SEC-01"
    assert data["status"] == "ACTIVE"
