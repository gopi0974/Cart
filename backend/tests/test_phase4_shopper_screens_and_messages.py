import uuid
from datetime import datetime, timedelta
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from app.database import Base, get_db
from app.models.cart import Cart
from app.models.product import Product
from app.models.session import CartSession, CartItem
from app.models.alert import Alert
from app.services.cart_state_machine import ViolationType
from app.main import app

TEST_DB_URL = "sqlite:///:memory:"
test_engine = create_engine(
    TEST_DB_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def db_session():
    Base.metadata.create_all(bind=test_engine)
    app.dependency_overrides[get_db] = override_get_db
    session = TestingSessionLocal()

    # Seed test cart and product
    cart = Cart(
        id="cart-p4-01",
        cart_number="CART-04",
        qr_code_token="token-p4-01",
        device_token_hash="hash-p4-01",
        status="ACTIVE",
        camera_status="ONLINE"
    )
    prod = Product(
        id="prod-p4-01",
        name="Almond Milk",
        barcode="8901111001",
        price=60.0,
        brand="NutriFarm",
        category="Dairy",
        is_active=True
    )
    session.add_all([cart, prod])
    session.commit()

    yield session

    session.close()
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=test_engine)


@pytest.fixture
def client():
    return TestClient(app)


def test_shopper_screens_empty_cart_warning_message(db_session, client):
    sess_id = str(uuid.uuid4())
    sess_token = "valid-session-token-p4"
    cart_sess = CartSession(
        id=sess_id,
        cart_id="cart-p4-01",
        session_token=sess_token,
        status="ACTIVE",
        cart_empty_verified=False
    )
    alert = Alert(
        id=str(uuid.uuid4()),
        cart_id="cart-p4-01",
        session_id=sess_id,
        alert_type="CART_NOT_EMPTY_AT_START",
        violation_type=ViolationType.CART_NOT_EMPTY_AT_START.value,
        message="Please empty the cart. Remove any items inside before scanning.",
        status="OPEN"
    )
    db_session.add_all([cart_sess, alert])
    db_session.commit()

    res = client.get(
        f"/api/v1/shopper/{sess_id}",
        headers={"X-Session-Token": sess_token}
    )
    assert res.status_code == 200
    data = res.json()
    assert data["can_checkout"] is False
    assert len(data["active_warnings"]) >= 1

    empty_warn = next(w for w in data["active_warnings"] if w["type"] == "CART_NOT_EMPTY_AT_START")
    assert "Please empty the cart" in empty_warn["message"]
    assert empty_warn["action_required"] == "EMPTY_CART"


def test_shopper_screens_unauthorized_remove_warning_message_and_evidence(db_session, client):
    sess_id = str(uuid.uuid4())
    sess_token = "valid-session-token-p4"
    cart_sess = CartSession(
        id=sess_id,
        cart_id="cart-p4-01",
        session_token=sess_token,
        status="ACTIVE"
    )
    item = CartItem(
        id=str(uuid.uuid4()),
        session_id=sess_id,
        product_id="prod-p4-01",
        quantity=1,
        unit_price=60.0,
        status="VERIFIED"
    )
    alert = Alert(
        id=str(uuid.uuid4()),
        cart_id="cart-p4-01",
        session_id=sess_id,
        item_id=item.id,
        alert_type="UNAUTHORIZED_REMOVE",
        violation_type=ViolationType.UNAUTHORIZED_REMOVE.value,
        message="This item appears to have been removed: Almond Milk",
        evidence_path="/uploads/evidence/unauth_rem_01.jpg",
        status="OPEN"
    )
    db_session.add_all([cart_sess, item, alert])
    db_session.commit()

    res = client.get(
        f"/api/v1/shopper/{sess_id}",
        headers={"X-Session-Token": sess_token}
    )
    assert res.status_code == 200
    data = res.json()

    rem_warn = next(w for w in data["active_warnings"] if w["type"] == "UNAUTHORIZED_REMOVE")
    assert "This item appears to have been removed: Almond Milk" in rem_warn["message"]
    assert rem_warn["action_required"] == "REPLACE_ITEM_OR_CALL_STAFF"
    assert rem_warn["evidence_url"] == "/uploads/evidence/unauth_rem_01.jpg"


def test_shopper_scan_item_blocked_while_pending_returns_place_scanned_item_first(db_session, client):
    sess_id = str(uuid.uuid4())
    sess_token = "valid-session-token-p4"
    cart_sess = CartSession(
        id=sess_id,
        cart_id="cart-p4-01",
        session_token=sess_token,
        status="ACTIVE",
        cart_empty_verified=True
    )
    pending_item = CartItem(
        id=str(uuid.uuid4()),
        session_id=sess_id,
        product_id="prod-p4-01",
        quantity=1,
        unit_price=60.0,
        status="PENDING",
        scanned_at=datetime.utcnow()
    )
    db_session.add_all([cart_sess, pending_item])
    db_session.commit()

    # Attempt to scan while an item is already PENDING (R2)
    res = client.post(
        f"/api/v1/shopper/{sess_id}/scan-item",
        headers={"X-Session-Token": sess_token},
        json={"barcode": "8901111001"}
    )
    assert res.status_code == 409
    body = res.json()
    assert body["detail"]["reason_code"] == "ITEM_PENDING"
    assert "Place the scanned item first" in body["detail"]["message"]


def test_shopper_scan_item_blocked_while_removing(db_session, client):
    sess_id = str(uuid.uuid4())
    sess_token = "valid-session-token-p4"
    cart_sess = CartSession(
        id=sess_id,
        cart_id="cart-p4-01",
        session_token=sess_token,
        status="ACTIVE",
        cart_empty_verified=True
    )
    removing_item = CartItem(
        id=str(uuid.uuid4()),
        session_id=sess_id,
        product_id="prod-p4-01",
        quantity=1,
        unit_price=60.0,
        status="REMOVING",
        scanned_at=datetime.utcnow()
    )
    db_session.add_all([cart_sess, removing_item])
    db_session.commit()

    # Attempt to scan while an item is REMOVING (R5)
    res = client.post(
        f"/api/v1/shopper/{sess_id}/scan-item",
        headers={"X-Session-Token": sess_token},
        json={"barcode": "8901111001"}
    )
    assert res.status_code == 409
    body = res.json()
    assert body["detail"]["reason_code"] == "ITEM_REMOVING"
    assert "finish removing" in body["detail"]["message"]


def test_shopper_pending_item_elapsed_time_message(db_session, client):
    sess_id = str(uuid.uuid4())
    sess_token = "valid-session-token-p4"
    cart_sess = CartSession(
        id=sess_id,
        cart_id="cart-p4-01",
        session_token=sess_token,
        status="ACTIVE",
        cart_empty_verified=True
    )
    # Scanned 70 seconds ago (exceeds 60s reminder threshold)
    old_scanned_at = datetime.utcnow() - timedelta(seconds=70)
    pending_item = CartItem(
        id=str(uuid.uuid4()),
        session_id=sess_id,
        product_id="prod-p4-01",
        quantity=1,
        unit_price=60.0,
        status="PENDING",
        scanned_at=old_scanned_at
    )
    db_session.add_all([cart_sess, pending_item])
    db_session.commit()

    res = client.get(
        f"/api/v1/shopper/{sess_id}",
        headers={"X-Session-Token": sess_token}
    )
    assert res.status_code == 200
    data = res.json()

    pending_warn = next(w for w in data["active_warnings"] if w["type"] == "PENDING_ITEM")
    assert "Waiting for the camera to check this item" in pending_warn["message"]
    assert pending_warn["action_required"] == "PLACE_IN_CART"
