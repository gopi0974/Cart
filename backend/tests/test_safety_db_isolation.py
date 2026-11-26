from pathlib import Path
import pytest
from tests.conftest import require_test_database_url, create_live_test_session


def test_live_db_helpers_ignore_database_url_and_require_test_database_url(monkeypatch):
    """Even if DATABASE_URL is set, live-DB tests must skip unless TEST_DATABASE_URL is explicitly set."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@prod.example.com:5432/prod")
    monkeypatch.delenv("TEST_DATABASE_URL", raising=False)

    with pytest.raises(pytest.skip.Exception, match="TEST_DATABASE_URL is not set"):
        require_test_database_url()

    with pytest.raises(pytest.skip.Exception, match="TEST_DATABASE_URL is not set"):
        create_live_test_session()


def test_no_live_db_test_reads_database_url():
    """Live-DB integration tests must not import or read settings.DATABASE_URL."""
    tests_dir = Path(__file__).parent
    for filename in ("test_backend.py", "test_removal_flow.py", "test_task6_e2e_verification.py"):
        content = (tests_dir / filename).read_text(encoding="utf-8")
        assert "DATABASE_URL" not in content, f"{filename} must not reference DATABASE_URL"
        assert "create_live_test_session" in content, f"{filename} must use create_live_test_session()"
