import os
import sys
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Ensure backend root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.main import app
from app.database import Base, get_db
from app.models.user import User
from app.models.cart import Cart
from app.models.session import CartSession
from app.utils.security import hash_password, create_access_token

# Standalone fast in-memory SQLite database
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
def setup_test_db():
    Base.metadata.create_all(bind=test_engine)
    app.dependency_overrides[get_db] = override_get_db

    db = TestingSessionLocal()
    try:
        # 1. Staff User
        staff_user = User(
            id="ws-test-staff-id",
            email="staff.ws@smartcart.internal",
            password_hash=hash_password("StaffPass!2026"),
            full_name="WS Staff Member",
            role="STAFF",
            is_active=True
        )
        db.add(staff_user)

        # 2. Physical Cart
        cart = Cart(
            id="ws-test-cart-id",
            cart_number="CART-WS-01",
            qr_code_token="QR-WS-01",
            is_enabled=True,
            status="ACTIVE"
        )
        db.add(cart)

        # 3. Active Shopping Session with specific session_token
        session = CartSession(
            id="ws-test-session-id",
            cart_id="ws-test-cart-id",
            session_token="shopper_valid_session_token_12345",
            status="ACTIVE"
        )
        db.add(session)
        db.commit()
    finally:
        db.close()

    yield

    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=test_engine)


def test_ws_admin_unauthenticated_rejected():
    """Connecting to /ws/admin without a token must be rejected with close code 1008."""
    client = TestClient(app)
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect("/ws/admin"):
            pass
    assert exc_info.value.code == 1008


def test_ws_admin_invalid_token_rejected():
    """Connecting to /ws/admin with an invalid token must be rejected with close code 1008."""
    client = TestClient(app)
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect("/ws/admin?token=invalid.jwt.token"):
            pass
    assert exc_info.value.code == 1008


def test_ws_admin_valid_staff_token_accepted():
    """Connecting to /ws/admin with a valid staff JWT must succeed and support ping/pong."""
    staff_token = create_access_token(data={"sub": "staff.ws@smartcart.internal", "role": "STAFF"})
    client = TestClient(app)

    with client.websocket_connect(f"/ws/admin?token={staff_token}") as ws:
        ws.send_text("ping")
        response = ws.receive_text()
        assert response == "pong"


def test_ws_cart_unauthenticated_rejected():
    """Connecting to /ws/cart/{cart_id} without a token must be rejected with close code 1008."""
    client = TestClient(app)
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect("/ws/cart/ws-test-cart-id"):
            pass
    assert exc_info.value.code == 1008


def test_ws_cart_invalid_session_token_rejected():
    """Connecting to /ws/cart/{cart_id} with an invalid session token must be rejected with close code 1008."""
    client = TestClient(app)
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect("/ws/cart/ws-test-cart-id?token=wrong_token_54321"):
            pass
    assert exc_info.value.code == 1008


def test_ws_cart_valid_shopper_token_accepted():
    """Connecting to /ws/cart/{cart_id} with a valid shopper session token must succeed."""
    client = TestClient(app)
    with client.websocket_connect("/ws/cart/ws-test-cart-id?token=shopper_valid_session_token_12345") as ws:
        ws.send_text("ping")
        response = ws.receive_text()
        assert response == "pong"


def test_ws_cart_staff_jwt_accepted():
    """Connecting to /ws/cart/{cart_id} with a valid staff JWT (store staff monitoring) must succeed."""
    staff_token = create_access_token(data={"sub": "staff.ws@smartcart.internal", "role": "STAFF"})
    client = TestClient(app)
    with client.websocket_connect(f"/ws/cart/ws-test-cart-id?token={staff_token}") as ws:
        ws.send_text("ping")
        response = ws.receive_text()
        assert response == "pong"

