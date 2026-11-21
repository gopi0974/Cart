import os
import sys
import io
import base64
import pytest
from unittest.mock import patch
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.main import app
from app.database import Base, get_db
from app.models.product import Product
from app.models.user import User
from app.utils.security import create_access_token
from app.services.recognition_lab_service import RecognitionLabService

test_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
Base.metadata.create_all(bind=test_engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_test_db():
    Base.metadata.create_all(bind=test_engine)
    app.dependency_overrides[get_db] = override_get_db
    yield
    Base.metadata.drop_all(bind=test_engine)


def test_recognition_lab_service_evaluation():
    """Verify RecognitionLabService computes score_scanned, best_other, margin, and confusion matrix."""
    db = TestingSessionLocal()

    p1 = Product(name="Organic Milk", barcode="8901111111111", price=60.0, brand="Amul", category="Dairy")
    p2 = Product(name="Greek Yogurt", barcode="8902222222222", price=45.0, brand="Epigamia", category="Dairy")
    db.add_all([p1, p2])
    db.commit()

    service = RecognitionLabService()
    service.reset_all()

    # Create dummy image
    test_img = Image.new("RGB", (120, 120), color=(100, 150, 200))

    with patch("app.services.recognition_lab_service.get_embedding", return_value=[0.2] * 512):
        with patch("app.services.recognition_lab_service.VectorStoreMatcher.find_nearest_product", return_value=[
            {"product_name": p1.name, "barcode": p1.barcode, "similarity": 0.88},
            {"product_name": p2.name, "barcode": p2.barcode, "similarity": 0.55}
        ]):
            with patch("app.services.recognition_lab_service.VectorStoreMatcher.verify_claimed_barcode", return_value=(True, 0.88)):
                sample1 = service.evaluate_and_record_photo(
                    db=db,
                    image_pil=test_img,
                    expected_barcode=p1.barcode,
                    filename="milk_overhead.jpg",
                    angle_label="OVERHEAD",
                    source="upload"
                )

    assert sample1["expected_barcode"] == p1.barcode
    assert sample1["expected_product_name"] == p1.name
    assert sample1["top1_product_name"] == p1.name
    assert sample1["top1_score"] == 0.88
    assert sample1["best_other"] == 0.55
    assert sample1["best_other_product_name"] == p2.name
    assert sample1["margin"] == round(0.88 - 0.55, 4)
    assert sample1["is_correct_top1"] is True

    # Record second sample (mismatch scenario)
    with patch("app.services.recognition_lab_service.get_embedding", return_value=[0.2] * 512):
        with patch("app.services.recognition_lab_service.VectorStoreMatcher.find_nearest_product", return_value=[
            {"product_name": p2.name, "barcode": p2.barcode, "similarity": 0.82},
            {"product_name": p1.name, "barcode": p1.barcode, "similarity": 0.60}
        ]):
            with patch("app.services.recognition_lab_service.VectorStoreMatcher.verify_claimed_barcode", return_value=(False, 0.60)):
                sample2 = service.evaluate_and_record_photo(
                    db=db,
                    image_pil=test_img,
                    expected_barcode=p1.barcode,
                    filename="milk_tilted.jpg",
                    angle_label="TILTED",
                    source="cart-device"
                )

    assert sample2["is_correct_top1"] is False
    assert sample2["top1_product_name"] == p2.name
    assert sample2["score_scanned"] == 0.60
    assert sample2["best_other"] == 0.82
    assert sample2["margin"] == round(0.60 - 0.82, 4)

    # Compute analysis report
    report = service.get_analysis_report()
    assert report["total_samples"] == 2
    assert report["unique_products_count"] == 1
    assert report["overall_top1_accuracy"] == 50.0  # 1 out of 2 correct
    assert "data_origin_statement" in report
    assert "No synthetic data is used" in report["data_origin_statement"]

    # Check threshold sensitivity matrix
    matrix = report["sensitivity_matrix"]
    assert len(matrix) == 9 * 5  # 9 thresholds x 5 margins

    # Threshold 0.80, Margin 0.10: sample 1 matches (score 0.88, margin 0.33), sample 2 doesn't
    point_080_010 = next((r for r in matrix if r["threshold"] == 0.80 and r["margin"] == 0.10), None)
    assert point_080_010 is not None
    assert point_080_010["true_accepts"] == 1
    assert point_080_010["false_rejects"] == 0
    assert point_080_010["false_accepts"] == 0

    # Check confusion matrix
    cm = report["confusion_matrix"]
    assert p1.name in cm["labels"]
    assert p2.name in cm["labels"]

    # Test single delete
    deleted = service.delete_sample(sample1["id"])
    assert deleted is True
    assert service.get_analysis_report()["total_samples"] == 1

    # Reset
    count = service.reset_all()
    assert count == 1
    assert service.get_analysis_report()["total_samples"] == 0


def test_recognition_lab_api_endpoints():
    """Verify HTTP API endpoints for Recognition Lab."""
    db = TestingSessionLocal()

    admin_user = User(email="admin@mart.com", password_hash="hash", full_name="Admin", role="ADMIN")
    p = Product(name="Cereal Box", barcode="8903333333333", price=120.0, brand="Kelloggs", category="Cereal")
    db.add_all([admin_user, p])
    db.commit()

    token = create_access_token({"sub": admin_user.email, "role": "ADMIN"})
    auth_header = {"Authorization": f"Bearer {token}"}

    # Create dummy base64 JPEG
    test_img = Image.new("RGB", (64, 64), color=(50, 100, 150))
    buf = io.BytesIO()
    test_img.save(buf, format="JPEG")
    data_url = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("utf-8")

    with patch("app.services.recognition_lab_service.get_embedding", return_value=[0.1] * 512):
        with patch("app.services.recognition_lab_service.VectorStoreMatcher.find_nearest_product", return_value=[
            {"product_name": p.name, "barcode": p.barcode, "similarity": 0.91}
        ]):
            with patch("app.services.recognition_lab_service.VectorStoreMatcher.verify_claimed_barcode", return_value=(True, 0.91)):
                resp = client.post(
                    "/api/v1/vision/recognition-lab/sample",
                    headers=auth_header,
                    json={
                        "expected_barcode": p.barcode,
                        "image_data_url": data_url,
                        "angle_label": "FRONT",
                        "source": "upload"
                    }
                )

    assert resp.status_code == 200
    res_data = resp.json()
    assert res_data["status"] == "SUCCESS"
    sample_id = res_data["sample"]["id"]
    assert res_data["sample"]["expected_barcode"] == p.barcode
    assert res_data["sample"]["top1_score"] == 0.91

    # GET results
    resp_results = client.get("/api/v1/vision/recognition-lab/results", headers=auth_header)
    assert resp_results.status_code == 200
    report_data = resp_results.json()
    assert report_data["total_samples"] >= 1
    assert "sensitivity_matrix" in report_data
    assert "confusion_matrix" in report_data

    # DELETE sample
    resp_del = client.delete(f"/api/v1/vision/recognition-lab/sample/{sample_id}", headers=auth_header)
    assert resp_del.status_code == 200
    assert resp_del.json()["status"] == "DELETED"

    # RESET
    resp_reset = client.post("/api/v1/vision/recognition-lab/reset", headers=auth_header)
    assert resp_reset.status_code == 200
    assert resp_reset.json()["status"] == "RESET"
