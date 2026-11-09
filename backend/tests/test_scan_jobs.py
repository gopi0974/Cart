import pytest
import io
import json
import base64
import asyncio
from unittest.mock import patch, MagicMock
from PIL import Image
from starlette.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.database import Base, get_db
import app.database as app_db
from app.models.user import User
from app.models.product import Product, ProductImage, ProductEmbedding
from app.models.scan_job import ScanJob
from app.utils.security import hash_password, create_access_token
from app.services.storage_service import storage_service
from app.services.scan_worker import (
    _downscale_and_remove_background,
    _execute_scan_job_internal,
    run_scan_job_with_watchdog
)

# Shared in-memory SQLite database
test_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


@pytest.fixture(scope="function")
def test_db():
    Base.metadata.create_all(bind=test_engine)
    db = TestingSessionLocal()
    try:
        # Seed an admin user
        admin = User(
            id="admin-uuid",
            email="admin@smartcart.internal",
            full_name="Admin Boss",
            role="ADMIN",
            password_hash=hash_password("AdminSecurePass!"),
            is_active=True
        )
        db.add(admin)

        # Seed a test product
        product = Product(
            id="product-uuid-1",
            barcode="8901030009999",
            name="Organic Green Tea 250g",
            brand="NatureFresh",
            category="Beverages",
            price=6.50,
            weight_grams=250,
            is_active=False
        )
        db.add(product)
        db.commit()
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=test_engine)


@pytest.fixture(scope="function")
def client(test_db, monkeypatch):
    monkeypatch.setattr("app.database.check_db_health", lambda *a, **k: True)
    monkeypatch.setattr("app.main.check_db_health", lambda *a, **k: True)
    monkeypatch.setattr("app.main.init_db", lambda: None)
    monkeypatch.setattr("app.main.seed_database", lambda db: None)
    monkeypatch.setattr("app.main.start_background_model_loader", lambda: None)
    monkeypatch.setattr("app.migrations.refresh_schema_cache", lambda *a, **k: {"is_up_to_date": True})
    monkeypatch.setattr("app.migrations.get_schema_info", lambda *a, **k: {"is_up_to_date": True, "current_revision": "head", "head_revision": "head"})
    monkeypatch.setattr("app.migrations.check_schema_health", lambda *a, **k: True)
    monkeypatch.setattr("app.services.scan_worker.cleanup_orphaned_jobs_on_startup", lambda: None)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    old_engine = app_db.engine
    old_session = app_db.SessionLocal
    app_db.engine = test_engine
    app_db.SessionLocal = TestingSessionLocal

    with TestClient(app) as c:
        yield c

    app.dependency_overrides.clear()
    app_db.engine = old_engine
    app_db.SessionLocal = old_session


def _create_sample_base64_image(color=(200, 50, 50), size=(100, 100)) -> str:
    """Helper to produce small real JPEG base64 data URLs."""
    img = Image.new("RGB", size, color=color)
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
    return f"data:image/jpeg;base64,{b64}"


def test_complete_360_scan_returns_job_id_immediately(client, test_db):
    admin_token = create_access_token({"sub": "admin@smartcart.internal", "role": "ADMIN"})
    headers = {"Authorization": f"Bearer {admin_token}"}

    captures = [
        {"angle_tag": "FRONT", "image_data_url": _create_sample_base64_image((255, 0, 0))},
        {"angle_tag": "BACK", "image_data_url": _create_sample_base64_image((0, 255, 0))},
        {"angle_tag": "LABEL_CLOSEUP", "image_data_url": _create_sample_base64_image((0, 0, 255))},
    ]

    # Don't trigger async thread worker in this unit test
    with patch("app.services.scan_worker.enqueue_scan_job") as mock_enqueue:
        resp = client.post(
            "/api/v1/vision/products/product-uuid-1/360-scan/complete",
            json={"captures": captures},
            headers=headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "PENDING"
        assert "job_id" in data
        assert data["product_id"] == "product-uuid-1"
        assert data["total_frames"] == 3
        mock_enqueue.assert_called_once_with(data["job_id"])

        # Check job persisted in database
        job = test_db.query(ScanJob).filter(ScanJob.id == data["job_id"]).first()
        assert job is not None
        assert job.status == "PENDING"
        assert job.total == 3
        assert job.stage == "SAVING_FRAMES"
        assert job.frame_paths_json is not None

        parsed = json.loads(job.frame_paths_json)
        frames = parsed.get("frames", parsed) if isinstance(parsed, dict) else parsed
        assert len(frames) == 3


def test_get_scan_job_status(client, test_db):
    admin_token = create_access_token({"sub": "admin@smartcart.internal", "role": "ADMIN"})
    headers = {"Authorization": f"Bearer {admin_token}"}

    # Seed job manually
    job = ScanJob(
        id="job-uuid-123",
        product_id="product-uuid-1",
        status="PROCESSING",
        stage="REMOVING_BACKGROUND",
        stage_message="Removing background 2/3",
        done=2,
        total=3
    )
    test_db.add(job)
    test_db.commit()

    resp = client.get("/api/v1/vision/jobs/job-uuid-123", headers=headers)
    assert resp.status_code == 200
    res = resp.json()
    assert res["job_id"] == "job-uuid-123"
    assert res["status"] == "PROCESSING"
    assert res["stage"] == "REMOVING_BACKGROUND"
    assert res["stage_message"] == "Removing background 2/3"
    assert res["done"] == 2
    assert res["total"] == 3


def test_downscale_and_background_removal():
    # Test that large image is downscaled to 224x224
    large_img = Image.new("RGB", (800, 600), color=(180, 180, 180))
    result = _downscale_and_remove_background(large_img)
    assert result.size == (224, 224)


def test_execute_scan_job_internal(test_db):
    # Save 2 frames locally via storage_service
    frame_bytes = base64.b64decode(_create_sample_base64_image().split(",", 1)[1])
    ref1 = storage_service.save_frame("job-test-exec", "f1.jpg", frame_bytes)
    ref2 = storage_service.save_frame("job-test-exec", "f2.jpg", frame_bytes)

    job = ScanJob(
        id="job-test-exec",
        product_id="product-uuid-1",
        status="PENDING",
        stage="SAVING_FRAMES",
        total=2,
        frame_paths_json=json.dumps([
            {"angle_tag": "FRONT", "frame_ref": ref1},
            {"angle_tag": "BACK", "frame_ref": ref2}
        ])
    )
    test_db.add(job)
    test_db.commit()

    # Mock get_embeddings_batch to return dummy 512-dim normalized vectors
    dummy_vec = [0.05] * 512
    with patch("app.services.scan_worker.get_embeddings_batch", return_value=[dummy_vec] * 16):
        with patch("app.services.scan_worker.SessionLocal", return_value=test_db):
            asyncio.run(_execute_scan_job_internal("job-test-exec"))

    # Refresh job
    test_db.expire_all()
    updated_job = test_db.query(ScanJob).filter(ScanJob.id == "job-test-exec").first()
    assert updated_job.status == "ENROLLED"
    assert updated_job.stage == "COMPLETED"
    assert updated_job.error is None
    assert updated_job.done > 0

    # Verify product is now active and embeddings stored
    prod = test_db.query(Product).filter(Product.id == "product-uuid-1").first()
    assert prod.is_active is True
    assert prod.quality_score is not None
    assert 0.0 <= prod.quality_score <= 1.0
    embeddings = test_db.query(ProductEmbedding).filter(ProductEmbedding.product_id == prod.id).all()
    assert len(embeddings) > 0


def test_retry_scan_job(client, test_db):
    admin_token = create_access_token({"sub": "admin@smartcart.internal", "role": "ADMIN"})
    headers = {"Authorization": f"Bearer {admin_token}"}

    # Seed a failed job
    job = ScanJob(
        id="failed-job-uuid",
        product_id="product-uuid-1",
        status="FAILED",
        stage="FAILED",
        stage_message="Processing timed out after 120s limit.",
        error="Processing timed out after 120s limit.",
        done=1,
        total=4,
        frame_paths_json='[{"angle_tag": "FRONT", "frame_ref": "ref1"}]'
    )
    test_db.add(job)
    test_db.commit()

    with patch("app.services.scan_worker.enqueue_scan_job") as mock_enqueue:
        resp = client.post("/api/v1/vision/jobs/failed-job-uuid/retry", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "PENDING"
        mock_enqueue.assert_called_once_with("failed-job-uuid")

        test_db.expire_all()
        reloaded = test_db.query(ScanJob).filter(ScanJob.id == "failed-job-uuid").first()
        assert reloaded.status == "PENDING"
        assert reloaded.error is None
        # Verify saved frames were preserved for retry
        assert reloaded.frame_paths_json == '[{"angle_tag": "FRONT", "frame_ref": "ref1"}]'


def test_cancel_scan_job(client, test_db):
    admin_token = create_access_token({"sub": "admin@smartcart.internal", "role": "ADMIN"})
    headers = {"Authorization": f"Bearer {admin_token}"}

    # Seed an active processing job
    job = ScanJob(
        id="cancel-job-uuid",
        product_id="product-uuid-1",
        status="PROCESSING",
        stage="COMPUTING_VECTORS",
        stage_message="Computing vectors 5/16",
        done=5,
        total=16,
        frame_paths_json='[{"angle_tag": "FRONT", "frame_ref": "ref1"}]'
    )
    test_db.add(job)
    test_db.commit()

    resp = client.post("/api/v1/vision/jobs/cancel-job-uuid/cancel", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "CANCELLED"

    test_db.expire_all()
    cancelled_job = test_db.query(ScanJob).filter(ScanJob.id == "cancel-job-uuid").first()
    assert cancelled_job.status == "CANCELLED"
    assert cancelled_job.stage == "CANCELLED"
    # Frames are kept for retry
    assert cancelled_job.frame_paths_json is not None


def test_get_product_active_job(client, test_db):
    admin_token = create_access_token({"sub": "admin@smartcart.internal", "role": "ADMIN"})
    headers = {"Authorization": f"Bearer {admin_token}"}

    # 1. Product without any jobs
    resp1 = client.get("/api/v1/vision/products/product-uuid-1/active-job", headers=headers)
    assert resp1.status_code == 200
    assert resp1.json()["has_active_job"] is False

    # 2. Add an active job
    job = ScanJob(
        id="active-job-uuid",
        product_id="product-uuid-1",
        status="PROCESSING",
        stage="REMOVING_BACKGROUND",
        stage_message="Removing background 1/3",
        done=1,
        total=3
    )
    test_db.add(job)
    test_db.commit()

    resp2 = client.get("/api/v1/vision/products/product-uuid-1/active-job", headers=headers)
    assert resp2.status_code == 200
    assert resp2.json()["has_active_job"] is True
    assert resp2.json()["job"]["job_id"] == "active-job-uuid"


def test_preprocess_product_image_for_embedding():
    from app.services.scan_worker import preprocess_product_image_for_embedding
    img = Image.new("RGB", (640, 480), color=(200, 100, 100))
    res = preprocess_product_image_for_embedding(img)
    assert res.size == (224, 224)


def test_preview_test_quality_recommendation(client, test_db):
    admin_token = create_access_token({"sub": "admin@smartcart.internal", "role": "ADMIN"})
    headers = {"Authorization": f"Bearer {admin_token}"}
    sample_img = _create_sample_base64_image()

    with patch("app.api.v1.vision.get_embedding", return_value=[0.05] * 512):
        with patch("app.ai.vector_store.VectorStoreMatcher.find_nearest_product", return_value=[
            {"product_name": "Other Product", "barcode": "999999999", "similarity": 0.88},
            {"product_name": "Organic Green Tea", "barcode": "8901030009999", "similarity": 0.82}
        ]):
            resp = client.post(
                "/api/v1/vision/products/preview-test",
                json={"image_data_url": sample_img, "target_barcode": "8901030009999"},
                headers=headers
            )
            assert resp.status_code == 200
            data = resp.json()
            assert "scan_quality_recommendation" in data
            assert data["scan_quality_recommendation"] == "Scan quality is low. Please rescan angles FRONT and LABEL_CLOSEUP."


def test_init_360_scan_upload(client, test_db):
    admin_token = create_access_token({"sub": "admin@smartcart.internal", "role": "ADMIN"})
    headers = {"Authorization": f"Bearer {admin_token}"}

    resp = client.post(
        "/api/v1/vision/products/product-uuid-1/360-scan/init-upload",
        json={
            "files": [
                {"angle_tag": "FRONT", "filename": "FRONT_0.jpg", "poor_crop": False},
                {"angle_tag": "BACK", "filename": "BACK_0.jpg", "poor_crop": False},
            ]
        },
        headers=headers
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "job_id" in data
    assert "direct_upload" in data
    assert data["product_id"] == "product-uuid-1"


def test_direct_upload_complete_360_scan(client, test_db):
    admin_token = create_access_token({"sub": "admin@smartcart.internal", "role": "ADMIN"})
    headers = {"Authorization": f"Bearer {admin_token}"}

    with patch("app.services.scan_worker.enqueue_scan_job") as mock_enqueue:
        resp = client.post(
            "/api/v1/vision/products/product-uuid-1/360-scan/complete",
            json={
                "job_id": "direct-job-123",
                "frames": [
                    {"angle_tag": "FRONT", "frame_ref": "supabase://bucket/f1.jpg", "poor_crop": False},
                    {"angle_tag": "BACK", "frame_ref": "supabase://bucket/f2.jpg", "poor_crop": False},
                ]
            },
            headers=headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "PENDING"
        assert data["job_id"] == "direct-job-123"
        assert data["total_frames"] == 2
        mock_enqueue.assert_called_once_with("direct-job-123")


def test_delete_scan_job(client, test_db):
    admin_token = create_access_token({"sub": "admin@smartcart.internal", "role": "ADMIN"})
    headers = {"Authorization": f"Bearer {admin_token}"}

    job = ScanJob(
        id="job-to-delete",
        product_id="product-uuid-1",
        status="CANCELLED",
        stage="CANCELLED",
        total=2,
    )
    test_db.add(job)
    test_db.commit()

    resp = client.delete("/api/v1/vision/jobs/job-to-delete", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "DELETED"

    # Confirm deleted from DB
    deleted = test_db.query(ScanJob).filter(ScanJob.id == "job-to-delete").first()
    assert deleted is None


def test_cleanup_orphaned_jobs_on_startup(test_db, monkeypatch):
    from app.services.scan_worker import cleanup_orphaned_jobs_on_startup

    # Seed orphaned jobs
    job1 = ScanJob(id="orphan-1", product_id="product-uuid-1", status="PENDING", stage="QUEUED", frame_paths_json="[]")
    job2 = ScanJob(id="orphan-2", product_id="product-uuid-1", status="PROCESSING", stage="PROCESSING_FRAMES", frame_paths_json="[]")
    test_db.add_all([job1, job2])
    test_db.commit()

    monkeypatch.setattr("app.services.scan_worker.SessionLocal", lambda: test_db)
    cleanup_orphaned_jobs_on_startup()

    test_db.expire_all()
    j1 = test_db.query(ScanJob).filter(ScanJob.id == "orphan-1").first()
    j2 = test_db.query(ScanJob).filter(ScanJob.id == "orphan-2").first()

    assert j1.status == "FAILED"
    assert "ERR_SERVER_RESTART" in j1.error
    assert j2.status == "FAILED"
    assert "ERR_SERVER_RESTART" in j2.error


def test_public_health_does_not_call_alembic(client):
    with patch("alembic.runtime.migration.MigrationContext.configure") as mock_mig:
        resp = client.get("/health")
        assert resp.status_code == 200
        # Verify Alembic migration context was NOT opened during public /health request
        mock_mig.assert_not_called()




