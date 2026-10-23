import os
from pathlib import Path
from pydantic import BaseModel
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# Load environment variables from .env in backend/ or project root
load_dotenv(BASE_DIR / ".env")
load_dotenv(BASE_DIR.parent / ".env")

def _normalize_db_url(url: str) -> str:
    """Normalize SQLAlchemy database URL for PostgreSQL/Supabase/Neon/Render."""
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql://", 1)
    return url

raw_db_url = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR}/smartcart.db")

class Settings(BaseModel):
    PROJECT_NAME: str = os.getenv("PROJECT_NAME", "SmartCart AI - Autonomous Retail Backend")
    VERSION: str = "1.0.0"
    API_V1_STR: str = "/api/v1"
    
    # Security
    SECRET_KEY: str = os.getenv("SECRET_KEY", "smartcart-super-secret-key-change-in-production-2026")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24 hours
    
    # Cart QR HMAC Signing Secret
    QR_SIGNING_SECRET: str = os.getenv("QR_SIGNING_SECRET", "smartcart-qr-hmac-secret-key-production-2026")
    
    # Public URLs for QR Connect Links & CORS
    BASE_URL: str = os.getenv("BASE_URL", "http://localhost:5173").rstrip("/")
    API_BASE_URL: str = os.getenv("API_BASE_URL", "http://localhost:8000").rstrip("/")
    CORS_ORIGINS: str = os.getenv("CORS_ORIGINS", "*")
    
    # Database (Hosted PostgreSQL on Supabase/Neon, or local SQLite)
    DATABASE_URL: str = _normalize_db_url(raw_db_url)
    
    # Storage Paths
    UPLOADS_DIR: Path = BASE_DIR / "uploads"
    EVIDENCE_DIR: Path = BASE_DIR / "uploads" / "evidence"
    CATALOG_DIR: Path = BASE_DIR / "uploads" / "catalog"
    MODELS_DIR: Path = BASE_DIR / "models_storage"
    
    # AI / Vision Thresholds
    CONFIDENCE_HIGH: float = float(os.getenv("CONFIDENCE_HIGH", "0.85"))
    CONFIDENCE_MEDIUM: float = float(os.getenv("CONFIDENCE_MEDIUM", "0.65"))
    CONFIDENCE_LOW: float = float(os.getenv("CONFIDENCE_LOW", "0.50"))
    
    # Payment Gateway (Test mode only)
    PAYMENT_MODE: str = os.getenv("PAYMENT_MODE", "TEST")
    PAYMENT_KEY_ID: str = os.getenv("PAYMENT_KEY_ID", "rzp_test_smartcart2026")
    PAYMENT_KEY_SECRET: str = os.getenv("PAYMENT_KEY_SECRET", "test_secret_mock_sandbox")

settings = Settings()

# Ensure directories exist
settings.UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
settings.EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
settings.CATALOG_DIR.mkdir(parents=True, exist_ok=True)
settings.MODELS_DIR.mkdir(parents=True, exist_ok=True)

