import os
import sys
import time
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Ensure backend root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.main import app
from app.database import Base, get_db
from app.models.user import User
from app.models.cart import Cart
from app.models.product import Product, ProductEmbedding
from app.models.session import CartSession, CartItem
from app.utils.security import hash_password, create_access_token
from app.utils.cache import catalog_cache

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
def setup_perf_data():
    Base.metadata.create_all(bind=test_engine)
    app.dependency_overrides[get_db] = override_get_db
    catalog_cache.invalidate()

    db = TestingSessionLocal()
    try:
        # 1. Staff Admin User
        admin = User(
            id="perf-admin-id",
            email="admin.perf@smartcart.internal",
            password_hash=hash_password("PerfAdmin!2026"),
            full_name="Performance Admin",
            role="ADMIN",
            is_active=True
        )
        db.add(admin)

        # 2. Cart
        cart = Cart(
            id="perf-cart-id",
            cart_number="CART-PERF-01",
            qr_code_token="QR-PERF-01",
            is_enabled=True,
            status="ACTIVE"
        )
        db.add(cart)

        # 3. Active Session
        session = CartSession(
            id="perf-session-id",
            cart_id="perf-cart-id",
            session_token="shopper_perf_token_99999",
            status="ACTIVE"
        )
        db.add(session)

        # 4. Seed 20 products with embeddings to test N+1 query elimination
        for i in range(1, 21):
            pid = f"prod-perf-{i:03d}"
            barcode = f"89010000{i:04d}"
            p = Product(
                id=pid,
                barcode=barcode,
                name=f"Performance Test Product {i}",
                brand="StoreBrand",
                category="Dairy" if i % 2 == 0 else "Snacks",
                price=10.0 + i,
                stock_quantity=50,
                is_active=True,
                is_deleted=False
            )
            db.add(p)
            emb = ProductEmbedding(
                id=f"emb-perf-{i:03d}",
                product_id=pid,
                barcode=barcode,
                angle_tag="FRONT",
                embedding_json="[0.01]*512"
            )
            db.add(emb)

            # Add first 5 products to the cart session
            if i <= 5:
                item = CartItem(
                    id=f"item-perf-{i:03d}",
                    session_id="perf-session-id",
                    product_id=pid,
                    quantity=1,
                    unit_price=10.0 + i,
                    status="VERIFIED"
                )
                db.add(item)

        db.commit()
    finally:
        db.close()

    yield

    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=test_engine)


def test_request_timing_and_query_headers_present():
    """Verify middleware injects X-Response-Time-Ms and X-DB-Queries headers."""
    client = TestClient(app)
    res = client.get("/")
    assert res.status_code == 200
    assert "X-Response-Time-Ms" in res.headers
    assert "X-DB-Queries" in res.headers
    duration = float(res.headers["X-Response-Time-Ms"])
    assert duration >= 0.0


def test_product_listing_eliminates_n_plus_one_queries():
    """
    Querying 20 products previously executed 1 + 20 = 21 queries.
    With batch embedding lookup, it must execute <= 2 queries.
    """
    client = TestClient(app)
    # Query without cache
    catalog_cache.invalidate()
    res = client.get("/api/v1/products?limit=20")
    assert res.status_code == 200
    queries = int(res.headers["X-DB-Queries"])
    assert queries <= 2, f"Expected <= 2 database queries, got {queries} (N+1 query detected!)"
    data = res.json()
    assert len(data) == 20
    assert all(item["has_embeddings"] for item in data)


def test_shopper_session_details_eliminates_n_plus_one_queries():
    """
    Fetching session details with 5 items previously executed 1 session + 1 cart + 5 item products = 7 queries.
    With joinedload, it must execute <= 3 queries.
    """
    client = TestClient(app)
    res = client.get(
        "/api/v1/shopper/perf-session-id",
        headers={"X-Session-Token": "shopper_perf_token_99999"}
    )
    assert res.status_code == 200
    queries = int(res.headers["X-DB-Queries"])
    assert queries <= 3, f"Expected <= 3 database queries, got {queries} (N+1 query detected!)"
    data = res.json()
    assert len(data["items"]) == 5
    assert data["cart_number"] == "CART-PERF-01"


def test_benchmark_endpoint_latencies(monkeypatch):
    """
    Benchmark and report execution timings and query counts across:
    1. /health
    2. /api/v1/shopper/{session_id}
    3. /api/v1/products
    """
    monkeypatch.setattr("app.database.check_db_health", lambda *args, **kwargs: True)
    monkeypatch.setattr("app.main.check_db_health", lambda *args, **kwargs: True)
    monkeypatch.setattr("app.main.SessionLocal", TestingSessionLocal)
    monkeypatch.setattr("app.migrations.check_schema_health", lambda *args, **kwargs: True)

    client = TestClient(app)

    # 1. /health
    t0 = time.perf_counter()
    res_health = client.get("/health")
    ms_health = (time.perf_counter() - t0) * 1000
    assert res_health.status_code == 200

    # 2. /shopper/{session_id}
    t0 = time.perf_counter()
    res_shopper = client.get(
        "/api/v1/shopper/perf-session-id",
        headers={"X-Session-Token": "shopper_perf_token_99999"}
    )
    ms_shopper = (time.perf_counter() - t0) * 1000
    assert res_shopper.status_code == 200

    # 3. /products (uncached first run)
    catalog_cache.invalidate()
    t0 = time.perf_counter()
    res_prod_uncached = client.get("/api/v1/products")
    ms_prod_uncached = (time.perf_counter() - t0) * 1000
    assert res_prod_uncached.status_code == 200

    # 4. /products (cached second run)
    t0 = time.perf_counter()
    res_prod_cached = client.get("/api/v1/products")
    ms_prod_cached = (time.perf_counter() - t0) * 1000
    assert res_prod_cached.status_code == 200

    print(f"\n--- BENCHMARK LATENCY REPORT ---")
    print(f"GET /health: {ms_health:.2f}ms | Queries: {res_health.headers.get('X-DB-Queries')}")
    print(f"GET /api/v1/shopper/{{id}}: {ms_shopper:.2f}ms | Queries: {res_shopper.headers.get('X-DB-Queries')}")
    print(f"GET /api/v1/products (DB query): {ms_prod_uncached:.2f}ms | Queries: {res_prod_uncached.headers.get('X-DB-Queries')}")
    print(f"GET /api/v1/products (TTL cache): {ms_prod_cached:.2f}ms | Queries: {res_prod_cached.headers.get('X-DB-Queries')}")
