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
        db.add(cart)
        db.commit()
    finally:
        db.close()

    yield

    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=test_engine)


def test_pairing_without_signature_fails_when_demo_mode_false(monkeypatch):
    """
    When DEMO_MODE=false, pairing without a cryptographic HMAC signature
    must be rejected with HTTP 400.
    """
    monkeypatch.setattr(settings, "DEMO_MODE", False)
    client = TestClient(app)

    # Attempt pairing with only cart_number (unsigned)
    payload = {
        "cart_number": "CART-SEC-01",
        "qr_token": "QR-SECRET-TOKEN-9876"
        # No signature provided
    }
    response = client.post("/api/v1/shopper/pair", json=payload)
    assert response.status_code == 400
    assert "Missing HMAC signature" in response.json()["detail"]


def test_pairing_with_invalid_signature_fails(monkeypatch):
    """
    Pairing with a forged or invalid signature must be rejected with HTTP 400.
    """
    monkeypatch.setattr(settings, "DEMO_MODE", False)
    client = TestClient(app)

    payload = {
        "cart_number": "CART-SEC-01",
        "qr_token": "QR-SECRET-TOKEN-9876",
        "signature": "forged_sig_12345"
    }
    response = client.post("/api/v1/shopper/pair", json=payload)
    assert response.status_code == 400
    assert "Invalid or tampered cart QR signature" in response.json()["detail"]


def test_pairing_with_valid_hmac_signature_succeeds(monkeypatch):
    """
    Pairing with the legitimate HMAC signature derived from the cart's physical QR
    must succeed with HTTP 200 when DEMO_MODE=false.
    """
    monkeypatch.setattr(settings, "DEMO_MODE", False)
    client = TestClient(app)

    # Compute valid HMAC signature using server's QR_SIGNING_SECRET
    msg = "CART-SEC-01:QR-SECRET-TOKEN-9876".encode("utf-8")
    valid_sig = hmac.new(settings.QR_SIGNING_SECRET.encode("utf-8"), msg, hashlib.sha256).hexdigest()[:16]

    payload = {
        "cart_number": "CART-SEC-01",
        "qr_token": "QR-SECRET-TOKEN-9876",
        "signature": valid_sig
    }
    response = client.post("/api/v1/shopper/pair", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["cart_number"] == "CART-SEC-01"
    assert data["status"] == "ACTIVE"


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
