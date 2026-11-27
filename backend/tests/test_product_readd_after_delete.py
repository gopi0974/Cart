import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.database import Base, get_db
from app.models.user import User
from app.utils.security import hash_password, create_access_token

test_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


@pytest.fixture(scope="function")
def client(monkeypatch):
    Base.metadata.create_all(bind=test_engine)
    db = TestingSessionLocal()
    admin = User(
        id="admin-readd-uuid",
        email="admin-readd@smartcart.internal",
        full_name="Admin User",
        role="ADMIN",
        password_hash=hash_password("AdminPass123!"),
        is_active=True,
    )
    db.add(admin)
    db.commit()
    db.close()

    monkeypatch.setattr("app.main.check_db_health", lambda *a, **k: False)
    monkeypatch.setattr("app.main.start_background_model_loader", lambda: None)

    def override_get_db():
        s = TestingSessionLocal()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as c:
            yield c
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(bind=test_engine)


def test_readd_product_with_same_barcode_after_soft_delete(client):
    token = create_access_token({"sub": "admin-readd@smartcart.internal", "role": "ADMIN"})
    headers = {"Authorization": f"Bearer {token}"}

    payload = {
        "barcode": "8901234567890",
        "name": "Test Mango Juice",
        "brand": "FreshCo",
        "category": "Beverages",
        "price": 45.0,
        "weight_grams": 200,
        "tax_rate": 5.0,
        "stock_quantity": 25,
    }

    # 1. Create product
    r1 = client.post("/api/v1/products", json=payload, headers=headers)
    assert r1.status_code == 200, r1.text
    prod_id = r1.json()["id"]

    # 2. Duplicate while still active must fail with 400
    r_dup = client.post("/api/v1/products", json=payload, headers=headers)
    assert r_dup.status_code == 400
    assert "already exists" in r_dup.json()["detail"]

    # 3. Soft-delete product
    r_del = client.delete(f"/api/v1/products/{prod_id}", headers=headers)
    assert r_del.status_code == 200, r_del.text

    # 4. Re-add product with the same barcode must succeed and update fields
    readd_payload = {**payload, "name": "Test Mango Juice V2", "price": 50.0}
    r_readd = client.post("/api/v1/products", json=readd_payload, headers=headers)
    assert r_readd.status_code == 200, r_readd.text
    data = r_readd.json()
    assert data["barcode"] == "8901234567890"
    assert data["name"] == "Test Mango Juice V2"
    assert data["price"] == 50.0
    assert data["is_active"] is True

    # 5. Product must appear in active catalog listing
    r_list = client.get("/api/v1/products")
    assert r_list.status_code == 200
    barcodes = [p["barcode"] for p in r_list.json()]
    assert "8901234567890" in barcodes
