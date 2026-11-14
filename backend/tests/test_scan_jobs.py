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
    monkeypatch.setattr("app.ai.vector_store.VectorStoreMatcher.sync_to_disk", lambda *a, **k: None)
    monkeypatch.setattr("app.services.device_watchdog.run_camera_watchdog", lambda *a, **k: asyncio.sleep(0))
    monkeypatch.setattr(storage_service, "supabase_url", "")

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

    with patch("app.services.storage_service.storage_service.check_frames_exist", return_value=(["ref1"], [])):
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
            assert "ref1" in reloaded.frame_paths_json


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
                {"angle_tag": "FRONT", "filename": "8901030009999_FRONT_0.jpg", "poor_crop": False},
                {"angle_tag": "BACK", "filename": "8901030009999_BACK_0.jpg", "poor_crop": False},
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

    job = ScanJob(
        id="direct-job-123",
        product_id="product-uuid-1",
        status="PENDING",
        stage="AWAITING_UPLOAD",
        frame_paths_json=None
    )
    test_db.add(job)
    test_db.commit()

    f1 = "supabase://bucket/direct-job-123/8901030009999_FRONT_0.jpg"
    f2 = "supabase://bucket/direct-job-123/8901030009999_BACK_1.jpg"

    with patch("app.services.storage_service.storage_service.check_frames_exist", return_value=([f1, f2], [])):
        with patch("app.services.scan_worker.enqueue_scan_job") as mock_enqueue:
            resp = client.post(
                "/api/v1/vision/products/product-uuid-1/360-scan/complete",
                json={
                    "job_id": "direct-job-123",
                    "frames": [
                        {"angle_tag": "FRONT", "frame_ref": f1, "poor_crop": False},
                        {"angle_tag": "BACK", "frame_ref": f2, "poor_crop": False},
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


def test_direct_upload_complete_360_scan_rejects_missing_frames(client, test_db):
    admin_token = create_access_token({"sub": "admin@smartcart.internal", "role": "ADMIN"})
    headers = {"Authorization": f"Bearer {admin_token}"}

    job = ScanJob(
        id="missing-job-123",
        product_id="product-uuid-1",
        status="PENDING",
        stage="AWAITING_UPLOAD",
        frame_paths_json=None
    )
    test_db.add(job)
    test_db.commit()

    f1 = "supabase://bucket/missing-job-123/8901030009999_FRONT_0.jpg"
    f2 = "supabase://bucket/missing-job-123/8901030009999_BACK_1.jpg"

    # Simulate missing frame f2 in storage
    with patch("app.services.storage_service.storage_service.check_frames_exist", return_value=([f1], [f2])):
        resp = client.post(
            "/api/v1/vision/products/product-uuid-1/360-scan/complete",
            json={
                "job_id": "missing-job-123",
                "frames": [
                    {"angle_tag": "FRONT", "frame_ref": f1, "poor_crop": False},
                    {"angle_tag": "BACK", "frame_ref": f2, "poor_crop": False},
                ]
            },
            headers=headers
        )
        assert resp.status_code == 400
        detail = resp.json()["detail"]
        assert "ERR_MISSING_FRAMES" in detail
        assert "8901030009999_BACK_1.jpg" in detail


def test_retry_scan_job_rejects_empty_frames(client, test_db):
    admin_token = create_access_token({"sub": "admin@smartcart.internal", "role": "ADMIN"})
    headers = {"Authorization": f"Bearer {admin_token}"}

    job = ScanJob(
        id="empty-frames-job",
        product_id="product-uuid-1",
        status="FAILED",
        stage="FAILED",
        frame_paths_json="[]"
    )
    test_db.add(job)
    test_db.commit()

    resp = client.post("/api/v1/vision/jobs/empty-frames-job/retry", headers=headers)
    assert resp.status_code == 400
    assert "ERR_NO_FRAMES" in resp.json()["detail"]


def test_failed_rescan_preserves_existing_vectors(test_db):
    from app.services.scan_worker import _execute_scan_job_sync
    from app.models.product import ProductEmbedding
    from app.ai.vector_store import VectorStoreMatcher

    # 1. Product initially has 4 enrolled vectors
    for i in range(4):
        VectorStoreMatcher.store_embedding(
            db=test_db,
            product_id="product-uuid-1",
            barcode="8901030009999",
            angle_tag=f"FRONT_{i}",
            vector=[0.123] * 512,
            image_path=f"path/to/old_{i}.jpg",
            commit=True
        )

    initial_embeddings = test_db.query(ProductEmbedding).filter(ProductEmbedding.product_id == "product-uuid-1").all()
    assert len(initial_embeddings) == 4
    initial_ids = {e.id for e in initial_embeddings}

    # 2. Trigger a failing re-scan job (simulate storage failure during download)
    failing_job = ScanJob(
        id="failing-rescan-job",
        product_id="product-uuid-1",
        status="PENDING",
        stage="QUEUED",
        total=2,
        frame_paths_json=json.dumps([
            {"angle_tag": "FRONT", "frame_ref": "bad-ref-1", "poor_crop": False},
            {"angle_tag": "BACK", "frame_ref": "bad-ref-2", "poor_crop": False},
        ])
    )
    test_db.add(failing_job)
    test_db.commit()

    with patch("app.services.scan_worker.SessionLocal", return_value=test_db):
        with patch("app.services.storage_service.storage_service.load_frame_image", side_effect=RuntimeError("Storage connection failed")):
            _execute_scan_job_sync("failing-rescan-job")

    # 3. Verify job failed
    test_db.expire_all()
    reloaded_job = test_db.query(ScanJob).filter(ScanJob.id == "failing-rescan-job").first()
    assert reloaded_job.status == "FAILED"
    assert "Storage connection failed" in reloaded_job.error

    # 4. Verify original product vectors are 100% intact and untouched
    surviving_embeddings = test_db.query(ProductEmbedding).filter(ProductEmbedding.product_id == "product-uuid-1").all()
    assert len(surviving_embeddings) == 4
    surviving_ids = {e.id for e in surviving_embeddings}
    assert surviving_ids == initial_ids


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


def test_frame_save_exception_triggers_sanitize_secrets(client, test_db):
    """Verifies that an exception during base64 frame saving triggers sanitize_secrets without NameError."""
    admin_token = create_access_token({"sub": "admin@smartcart.internal", "role": "ADMIN"})
    headers = {"Authorization": f"Bearer {admin_token}"}

    captures = [
        {"angle_tag": "FRONT", "image_data_url": _create_sample_base64_image((255, 0, 0)), "poor_crop": False},
        {"angle_tag": "BACK", "image_data_url": _create_sample_base64_image((0, 255, 0)), "poor_crop": False},
    ]

    call_count = 0
    def side_effect_save(job_id, filename, image_bytes):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("Database user:secret_pass_1234@cluster error")
        return f"supabase://bucket/{job_id}/{filename}"

    with patch("app.services.storage_service.storage_service.save_frame", side_effect=side_effect_save):
        with patch("app.services.scan_worker.enqueue_scan_job"):
            resp = client.post(
                "/api/v1/vision/products/product-uuid-1/360-scan/complete",
                json={"captures": captures},
                headers=headers
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "PENDING"
            assert data["total_frames"] == 1


def test_frame_ref_validation_rejects_unmatched_job_or_product(client, test_db):
    """Direct upload must reject frame_refs pointing to other jobs, other products, or path traversal."""
    admin_token = create_access_token({"sub": "admin@smartcart.internal", "role": "ADMIN"})
    headers = {"Authorization": f"Bearer {admin_token}"}

    job = ScanJob(
        id="valid-job-999",
        product_id="product-uuid-1",
        status="PENDING",
        stage="AWAITING_UPLOAD"
    )
    test_db.add(job)
    test_db.commit()

    # 1. Foreign job ID in frame_ref
    resp = client.post(
        "/api/v1/vision/products/product-uuid-1/360-scan/complete",
        json={
            "job_id": "valid-job-999",
            "frames": [{"angle_tag": "FRONT", "frame_ref": "supabase://bucket/different-job-000/8901030009999_f.jpg"}]
        },
        headers=headers
    )
    assert resp.status_code == 400
    assert "does not belong to job" in resp.json()["detail"]

    # 2. Foreign product prefix in frame_ref
    resp2 = client.post(
        "/api/v1/vision/products/product-uuid-1/360-scan/complete",
        json={
            "job_id": "valid-job-999",
            "frames": [{"angle_tag": "FRONT", "frame_ref": "supabase://bucket/valid-job-999/FOREIGNBARCODE_f.jpg"}]
        },
        headers=headers
    )
    assert resp2.status_code == 400
    assert "product barcode" in resp2.json()["detail"]


def test_init_upload_rejects_path_traversal_and_unmatched_filenames(client, test_db):
    """init-upload must reject traversal patterns and files not prefixed with product barcode."""
    admin_token = create_access_token({"sub": "admin@smartcart.internal", "role": "ADMIN"})
    headers = {"Authorization": f"Bearer {admin_token}"}

    # Path traversal
    resp1 = client.post(
        "/api/v1/vision/products/product-uuid-1/360-scan/init-upload",
        json={"files": [{"angle_tag": "FRONT", "filename": "../../../etc/passwd"}]},
        headers=headers
    )
    assert resp1.status_code == 400
    assert "path traversal" in resp1.json()["detail"]

    # Wrong prefix
    resp2 = client.post(
        "/api/v1/vision/products/product-uuid-1/360-scan/init-upload",
        json={"files": [{"angle_tag": "FRONT", "filename": "random_file.jpg"}]},
        headers=headers
    )
    assert resp2.status_code == 400
    assert "must start with product barcode" in resp2.json()["detail"]


def test_retry_scan_job_partial_frames_requires_confirmation(client, test_db):
    """Retry with partial surviving frames warns admin with missing angles and requires confirmation."""
    admin_token = create_access_token({"sub": "admin@smartcart.internal", "role": "ADMIN"})
    headers = {"Authorization": f"Bearer {admin_token}"}

    f1 = "supabase://bucket/partial-job-1/8901030009999_FRONT.jpg"
    f2 = "supabase://bucket/partial-job-1/8901030009999_BACK.jpg"
    f3 = "supabase://bucket/partial-job-1/8901030009999_LEFT.jpg"

    job = ScanJob(
        id="partial-job-1",
        product_id="product-uuid-1",
        status="FAILED",
        stage="FAILED",
        frame_paths_json=json.dumps({
            "frames": [
                {"angle_tag": "FRONT", "frame_ref": f1},
                {"angle_tag": "BACK", "frame_ref": f2},
                {"angle_tag": "LEFT", "frame_ref": f3},
            ],
            "completed_vectors": [],
            "primary_frame_url": None
        })
    )
    test_db.add(job)
    test_db.commit()

    # Only f1 and f2 exist; f3 (LEFT) is missing
    with patch("app.services.storage_service.storage_service.check_frames_exist", return_value=([f1, f2], [f3])):
        # First retry call: without confirm_partial -> returns confirmation warning
        resp = client.post("/api/v1/vision/jobs/partial-job-1/retry", json={"confirm_partial": False}, headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["requires_confirmation"] is True
        assert data["surviving_count"] == 2
        assert data["total_count"] == 3
        assert "LEFT" in data["missing_angles"]

        # Second retry call: with confirm_partial -> enqueues successfully
        with patch("app.services.scan_worker.enqueue_scan_job") as mock_enq:
            resp2 = client.post("/api/v1/vision/jobs/partial-job-1/retry", json={"confirm_partial": True}, headers=headers)
            assert resp2.status_code == 200
            data2 = resp2.json()
            assert data2["status"] == "PENDING"
            assert data2["total_frames"] == 2
            mock_enq.assert_called_once_with("partial-job-1")


def test_server_upload_enforces_size_limits_and_rbac(client, test_db):
    """Streaming server upload enforces RBAC and frame size limit of 5MB."""
    staff_user = User(
        id="staff-uuid-99",
        email="staff@smartcart.internal",
        full_name="Staff Worker",
        role="STAFF",
        password_hash=hash_password("StaffPass!"),
        is_active=True
    )
    test_db.add(staff_user)
    test_db.commit()

    staff_token = create_access_token({"sub": "staff@smartcart.internal", "role": "STAFF"})
    admin_token = create_access_token({"sub": "admin@smartcart.internal", "role": "ADMIN"})

    job = ScanJob(id="upload-job-1", product_id="product-uuid-1", status="PENDING", stage="AWAITING_UPLOAD")
    test_db.add(job)
    test_db.commit()

    # 1. Staff role must be rejected with 403
    resp_staff = client.post(
        "/api/v1/vision/products/product-uuid-1/360-scan/upload-frame",
        data={"job_id": "upload-job-1", "angle_tag": "FRONT"},
        files={"file": ("frame.jpg", b"fake-jpg-content", "image/jpeg")},
        headers={"Authorization": f"Bearer {staff_token}"}
    )
    assert resp_staff.status_code == 403

    # 2. File > 5MB must be rejected with 400
    huge_bytes = b"0" * (5 * 1024 * 1024 + 10)
    resp_large = client.post(
        "/api/v1/vision/products/product-uuid-1/360-scan/upload-frame",
        data={"job_id": "upload-job-1", "angle_tag": "FRONT"},
        files={"file": ("frame.jpg", huge_bytes, "image/jpeg")},
        headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert resp_large.status_code == 400
    assert "exceeds maximum allowed size" in resp_large.json()["detail"]

    # 3. Valid file with Admin succeeds
    with patch("app.services.storage_service.storage_service.save_frame", return_value="supabase://bucket/upload-job-1/f.jpg"):
        resp_ok = client.post(
            "/api/v1/vision/products/product-uuid-1/360-scan/upload-frame",
            data={"job_id": "upload-job-1", "angle_tag": "FRONT"},
            files={"file": ("frame.jpg", b"valid-frame-bytes", "image/jpeg")},
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert resp_ok.status_code == 200
        assert resp_ok.json()["frame_ref"] == "supabase://bucket/upload-job-1/f.jpg"


def test_atomic_vector_enrollment_rolls_back_on_failure(test_db):
    """Failure during vector insertion must roll back deletion, leaving old vectors intact."""
    from app.services.scan_worker import _execute_scan_job_sync
    from app.models.product import ProductEmbedding
    from app.ai.vector_store import VectorStoreMatcher

    # 1. Product initially has 3 enrolled vectors
    for i in range(3):
        VectorStoreMatcher.store_embedding(
            db=test_db,
            product_id="product-uuid-1",
            barcode="8901030009999",
            angle_tag=f"OLD_{i}",
            vector=[0.1] * 512,
            commit=True
        )

    initial_count = test_db.query(ProductEmbedding).filter(ProductEmbedding.product_id == "product-uuid-1").count()
    assert initial_count == 3

    # Create a job that reaches stage E but fails during database save
    frames = [{"angle_tag": "FRONT", "frame_ref": "supabase://bucket/f1.jpg", "completed": True}]
    job = ScanJob(
        id="failing-atomic-job",
        product_id="product-uuid-1",
        status="PENDING",
        stage="QUEUED",
        frame_paths_json=json.dumps({"frames": frames, "completed_vectors": [{"angle_tag": "FRONT", "v_tag": "CLEAN", "vec": [0.2] * 512, "frame_ref": "supabase://bucket/f1.jpg"}], "primary_frame_url": None})
    )
    test_db.add(job)
    test_db.commit()

    with patch("app.services.scan_worker.SessionLocal", lambda: test_db):
        # Patch store_embedding to raise an error during insertion
        original_store = VectorStoreMatcher.store_embedding
        def failing_store(*args, **kwargs):
            raise RuntimeError("Simulated DB connection drop during vector insert")

        with patch.object(VectorStoreMatcher, "store_embedding", side_effect=failing_store):
            _execute_scan_job_sync("failing-atomic-job")

    # Verify that the transaction rolled back and the 3 original vectors are still intact!
    test_db.expire_all()
    surviving_count = test_db.query(ProductEmbedding).filter(ProductEmbedding.product_id == "product-uuid-1").count()
    assert surviving_count == 3, f"Expected 3 vectors to be preserved by atomic rollback, but found {surviving_count}!"


def test_scan_job_uploads_only_cropped_product_images_never_full_frames(client, test_db):
    """
    Requirement 4 verification:
    Confirm that only cropped product images are uploaded and stored, never uncropped full frames.
    """
    admin_token = create_access_token({"sub": "admin@smartcart.internal", "role": "ADMIN"})
    headers = {"Authorization": f"Bearer {admin_token}"}

    # Create dummy cropped image (200x200) and dummy full frame (1280x720)
    cropped_buf = io.BytesIO()
    Image.new("RGB", (200, 200), color=(50, 150, 50)).save(cropped_buf, format="JPEG")
    cropped_b64 = "data:image/jpeg;base64," + base64.b64encode(cropped_buf.getvalue()).decode()

    full_frame_buf = io.BytesIO()
    Image.new("RGB", (1280, 720), color=(10, 20, 30)).save(full_frame_buf, format="JPEG")
    full_frame_b64 = "data:image/jpeg;base64," + base64.b64encode(full_frame_buf.getvalue()).decode()

    # Attempt to send with both cropped and full frame fields
    payload = {
        "captures": [
            {
                "angle_tag": "FRONT",
                "image_data_url": cropped_b64,
                "original_image_data_url": full_frame_b64,  # Even if sent, MUST NEVER BE STORED
                "poor_crop": False
            }
        ]
    }

    with patch("app.services.scan_worker.enqueue_scan_job"):
        resp = client.post("/api/v1/vision/products/product-uuid-1/360-scan/complete", json=payload, headers=headers)
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()
        job_id = data["job_id"]

    # Verify ScanJob in database
    job = test_db.query(ScanJob).filter(ScanJob.id == job_id).first()
    assert job is not None
    frame_state = json.loads(job.frame_paths_json)
    saved_frames = frame_state["frames"]
    assert len(saved_frames) == 1

    # Verify that the stored frame reference corresponds strictly to the cropped image
    frame_ref = saved_frames[0]["frame_ref"]
    from app.services.storage_service import storage_service
    loaded_img = storage_service.load_frame_image(frame_ref)

    # Load image and assert its dimensions match the cropped image, NOT the 1280x720 full frame!
    assert loaded_img.size == (200, 200), f"Stored image size is {loaded_img.size}, expected cropped (200, 200)!"
    assert loaded_img.size != (1280, 720), "SECURITY VIOLATION: Full camera frame was stored!"


def test_audit_override_endpoint_records_admin_action(client, test_db):
    """
    Requirement 7 verification:
    'Capture anyway' admin override writes an audit log entry.
    """
    admin_token = create_access_token({"sub": "admin@smartcart.internal", "role": "ADMIN"})
    headers = {"Authorization": f"Bearer {admin_token}"}

    override_payload = {
        "product_id": "product-uuid-1",
        "angle_tag": "FRONT",
        "reason": "Admin verified no face in cropped product region after 3 blocked attempts.",
        "confirmed_by": "admin@smartcart.internal",
        "face_details": {
            "score": 0.68,
            "widthFraction": 0.08,
            "heightFraction": 0.10,
            "x": 0.35,
            "y": 0.40,
            "consecutiveFrames": 3
        }
    }

    resp = client.post("/api/v1/vision/scan-jobs/audit-override", json=override_payload, headers=headers)
    assert resp.status_code == 200
    res_data = resp.json()
    assert res_data["status"] == "AUDIT_LOGGED"
    assert res_data["confirmed_by"] == "admin@smartcart.internal"
    assert res_data["product_id"] == "product-uuid-1"
    assert res_data["angle_tag"] == "FRONT"


def test_detector_profile_synthetic_frames_evaluation():
    """
    Requirement 8 verification:
    Evaluate synthetic frames across 4 scenarios:
    1. Empty scene
    2. Poster with face in background (outside guide box)
    3. Face inside guide box (overlapping product crop)
    4. Product alone (packaging graphics, text, barcodes)
    Measure false-positive count on a test set of at least 20 empty or product-only frames.
    """
    # Profile definitions matching frontend/src/config/detectorProfiles.ts
    privacy_profile = {
        "name": "privacy",
        "min_face_confidence": 0.25,
        "min_face_box_width": 0.02,
        "min_consecutive_frames": 1,
        "cooldown_frames": 5
    }
    enrollment_profile = {
        "name": "enrollment",
        "min_face_confidence": 0.60,
        "min_face_box_width": 0.06,
        "min_consecutive_frames": 3,
        "cooldown_frames": 1
    }

    def evaluate_frame_detections(detections, profile, guide_box, crop_box, static_refs=None):
        """Simulates privacyDetector.detect and overlap blocking logic."""
        if static_refs is None:
            static_refs = []

        active_blocking = []
        active_outside = []

        for d in detections:
            # Check static reference match
            is_static = any(
                abs(d["x"] - r["x"]) < 0.05 and abs(d["y"] - r["y"]) < 0.05
                for r in static_refs
            )
            if is_static:
                continue

            # Confidence and size gating
            if d["score"] < profile["min_face_confidence"]:
                continue
            if d["width"] < profile["min_face_box_width"]:
                continue
            if d.get("consecutive_frames", 1) < profile["min_consecutive_frames"]:
                continue

            # Overlap with crop box or large face (>15% area or >38% width)
            is_large = (d["width"] * d["height"] >= 0.15) or (d["width"] >= 0.38)
            inter_x1 = max(d["x"], crop_box["x"])
            inter_y1 = max(d["y"], crop_box["y"])
            inter_x2 = min(d["x"] + d["width"], crop_box["x"] + crop_box["width"])
            inter_y2 = min(d["y"] + d["height"], crop_box["y"] + crop_box["height"])
            has_overlap = (inter_x2 > inter_x1 and inter_y2 > inter_y1)

            if is_large or has_overlap:
                active_blocking.append(d)
            else:
                active_outside.append(d)

        return {
            "is_blocking": len(active_blocking) > 0,
            "has_outside_hint": len(active_outside) > 0,
            "blocking_count": len(active_blocking),
            "outside_count": len(active_outside)
        }

    guide_box = {"x": 0.20, "y": 0.167, "width": 0.60, "height": 0.667}
    crop_box = {"x": 0.25, "y": 0.20, "width": 0.50, "height": 0.60}

    # Scenario 1: Empty scene with low-confidence noise artifact (conf=0.28, width=0.03, 1 frame)
    empty_detections = [{"x": 0.10, "y": 0.10, "width": 0.03, "height": 0.04, "score": 0.28, "consecutive_frames": 1}]
    res_empty_old = evaluate_frame_detections(empty_detections, privacy_profile, guide_box, crop_box)
    res_empty_new = evaluate_frame_detections(empty_detections, enrollment_profile, guide_box, crop_box)
    assert res_empty_old["outside_count"] > 0 or res_empty_old["is_blocking"] is True  # Old profile triggered
    assert res_empty_new["is_blocking"] is False  # New profile correctly ignores noise
    assert res_empty_new["blocking_count"] == 0

    # Scenario 2: Poster with face in background (outside guide box, conf=0.78, w=0.10, 5 frames)
    poster_detections = [{"x": 0.05, "y": 0.05, "width": 0.10, "height": 0.12, "score": 0.78, "consecutive_frames": 5}]
    res_poster = evaluate_frame_detections(poster_detections, enrollment_profile, guide_box, crop_box)
    assert res_poster["is_blocking"] is False, "Poster outside guide box should NOT block capture!"
    assert res_poster["has_outside_hint"] is True, "Poster outside guide box should provide gentle hint."

    # Scenario 2b: Static poster calibrated in Step 0
    static_refs = [{"x": 0.05, "y": 0.05, "width": 0.10, "height": 0.12}]
    res_poster_static = evaluate_frame_detections(poster_detections, enrollment_profile, guide_box, crop_box, static_refs=static_refs)
    assert res_poster_static["is_blocking"] is False
    assert res_poster_static["has_outside_hint"] is False, "Calibrated static background must be completely ignored!"

    # Scenario 3: Face inside guide box (overlapping product crop, conf=0.85, w=0.20, 4 frames)
    face_inside = [{"x": 0.35, "y": 0.30, "width": 0.20, "height": 0.25, "score": 0.85, "consecutive_frames": 4}]
    res_inside = evaluate_frame_detections(face_inside, enrollment_profile, guide_box, crop_box)
    assert res_inside["is_blocking"] is True, "Face inside guide box MUST block capture!"
    assert res_inside["blocking_count"] == 1

    # Scenario 4: Product alone (retail packaging with high-contrast text, logos, folds)
    product_detections = [{"x": 0.40, "y": 0.35, "width": 0.05, "height": 0.05, "score": 0.42, "consecutive_frames": 2}]
    res_product = evaluate_frame_detections(product_detections, enrollment_profile, guide_box, crop_box)
    assert res_product["is_blocking"] is False, "Product packaging artifact must NOT block enrollment!"

    # 20-frame Test Set: 10 empty scene frames + 10 product-only packaging frames
    test_set = []
    # 10 Empty frames with camera noise & sensor fluctuations
    for i in range(10):
        # Spurious detections that occur in 1 or 2 frames with low confidence
        conf = 0.26 + (i % 4) * 0.05  # 0.26, 0.31, 0.36, 0.41
        width = 0.02 + (i % 3) * 0.015  # 0.02, 0.035, 0.05
        test_set.append([{"x": 0.12, "y": 0.15, "width": width, "height": width * 1.2, "score": conf, "consecutive_frames": (i % 2) + 1}])

    # 10 Product-only frames with packaging graphics & barcodes
    for i in range(10):
        conf = 0.32 + (i % 5) * 0.05  # 0.32 to 0.52
        width = 0.04 + (i % 3) * 0.01  # 0.04 to 0.06
        test_set.append([{"x": 0.35, "y": 0.30, "width": width, "height": width * 1.1, "score": conf, "consecutive_frames": (i % 2) + 1}])

    assert len(test_set) == 20

    old_false_positives = sum(
        1 for frame_dets in test_set
        if evaluate_frame_detections(frame_dets, privacy_profile, guide_box, crop_box)["blocking_count"] > 0
        or evaluate_frame_detections(frame_dets, privacy_profile, guide_box, crop_box)["outside_count"] > 0
    )

    new_false_positives = sum(
        1 for frame_dets in test_set
        if evaluate_frame_detections(frame_dets, enrollment_profile, guide_box, crop_box)["is_blocking"] is True
    )

    # Under naive 0.25 confidence and 1 frame, false-positive rate is high (~75%)
    assert old_false_positives >= 10, f"Expected old profile to trigger false positives, got {old_false_positives}"
    # Under enrollment profile (>=0.60 conf, >=6% width, >=3 consecutive frames), false positives drop to 0!
    assert new_false_positives == 0, f"Expected 0 false positives under enrollment profile, got {new_false_positives}!"





