import os
import sys
import uuid
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.database import Base
from app.models.cart import Cart
from app.models.product import Product
from app.models.session import CartSession, CartItem
from app.models.alert import Alert
from app.models.transaction import AuditLog
from app.services.device_watchdog import release_idle_sessions
from app.config import settings


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(bind=engine)
    session = TestingSession()

    cart = Cart(
        id="cart-idle-01",
        cart_number="CART-IDLE-01",
        qr_code_token="QR-IDLE-01",
        is_enabled=True,
        status="ACTIVE",
        camera_status="ONLINE",
    )
    product = Product(
        id="prod-idle-01",
        name="Test Milk",
        brand="Brand",
        category="Dairy",
        barcode="111222333444",
        price=25.0,
        stock_quantity=10,
    )
    session.add_all([cart, product])
    session.commit()
    try:
        yield session
    finally:
        session.close()


@pytest.mark.anyio
async def test_idle_empty_session_released_after_30_minutes(db_session):
    now = datetime.utcnow()
    sess = CartSession(
        id=str(uuid.uuid4()),
        cart_id="cart-idle-01",
        status="ACTIVE",
        started_at=now - timedelta(minutes=31),
    )
    alert = Alert(
        cart_id="cart-idle-01",
        session_id=sess.id,
        alert_type="UNSCANNED_ITEM",
        message="Open warning",
        severity="HIGH",
        status="OPEN",
    )
    db_session.add_all([sess, alert])
    db_session.commit()

    with patch("app.services.device_watchdog.ws_manager.broadcast_to_cart", new_callable=AsyncMock) as mock_cart_ws, \
         patch("app.services.device_watchdog.ws_manager.broadcast_to_admin", new_callable=AsyncMock):
        released = await release_idle_sessions(db_session, now=now)

    assert sess.id in released
    db_session.refresh(sess)
    db_session.refresh(alert)
    cart = db_session.query(Cart).filter(Cart.id == "cart-idle-01").first()
    audit = db_session.query(AuditLog).filter(AuditLog.action == "IDLE_SESSION_RELEASED", AuditLog.entity_id == sess.id).first()

    assert sess.status == "ENDED"
    assert alert.status == "RESOLVED"
    assert cart.status == "IDLE"
    assert audit is not None
    mock_cart_ws.assert_awaited()
    assert mock_cart_ws.call_args.args[1] == "SESSION_ENDED_IDLE"


@pytest.mark.anyio
async def test_idle_session_with_items_kept_at_45m_and_released_after_2h(db_session, monkeypatch):
    now = datetime.utcnow()
    sess = CartSession(
        id=str(uuid.uuid4()),
        cart_id="cart-idle-01",
        status="ACTIVE",
        started_at=now - timedelta(minutes=130),
    )
    item = CartItem(
        id=str(uuid.uuid4()),
        session_id=sess.id,
        product_id="prod-idle-01",
        quantity=1,
        unit_price=25.0,
        status="VERIFIED",
        scanned_at=now - timedelta(minutes=45),
        verified_at=now - timedelta(minutes=44),
    )
    db_session.add_all([sess, item])
    db_session.commit()

    with patch("app.services.device_watchdog.ws_manager.broadcast_to_cart", new_callable=AsyncMock), \
         patch("app.services.device_watchdog.ws_manager.broadcast_to_admin", new_callable=AsyncMock):
        # At 44 minutes idle, default 120m limit must NOT release
        released_early = await release_idle_sessions(db_session, now=now)
        assert released_early == []

        # With configurable timeout set to 40m, it MUST release
        monkeypatch.setattr(settings, "IDLE_ACTIVE_SESSION_MINUTES", 40.0)
        released_cfg = await release_idle_sessions(db_session, now=now)
        assert sess.id in released_cfg
