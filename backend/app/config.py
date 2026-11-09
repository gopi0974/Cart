import os
from typing import Optional
from pathlib import Path
from pydantic import BaseModel
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# Load environment variables from .env in backend/ or project root
load_dotenv(BASE_DIR / ".env")
load_dotenv(BASE_DIR.parent / ".env")

def _normalize_db_url(url: Optional[str]) -> Optional[str]:
    """Normalize SQLAlchemy database URL for PostgreSQL / Supabase / Neon / Render."""
    if not url or not str(url).strip():
        return None
    clean_url = str(url).strip().strip("'\"")
    if clean_url.startswith("postgres://"):
        clean_url = clean_url.replace("postgres://", "postgresql://", 1)
    return clean_url

raw_db_url = os.getenv("DATABASE_URL")

class Settings(BaseModel):
    BASE_DIR: Path = BASE_DIR
    PROJECT_NAME: str = os.getenv("PROJECT_NAME", "SmartCart AI - Autonomous Retail Backend")
    VERSION: str = "1.0.0"
    API_V1_STR: str = "/api/v1"
    
    # Initial Admin Bootstrap (Environment Variables Only)
    ADMIN_EMAIL: Optional[str] = os.getenv("ADMIN_EMAIL")
    ADMIN_PASSWORD: Optional[str] = os.getenv("ADMIN_PASSWORD")
    
    # Security
    SECRET_KEY: str = os.getenv("SECRET_KEY", "smartcart-super-secret-key-change-in-production-2026")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 8  # 8 hours for staff
    
    # Environment & Flags (default: false in production)
    DEMO_MODE: bool = os.getenv("DEMO_MODE", "false").lower() in ("true", "1", "yes")
    USE_MOCK: bool = os.getenv("USE_MOCK", "false").lower() in ("true", "1", "yes")
    
    # Cart QR HMAC Signing Secret
    QR_SIGNING_SECRET: str = os.getenv("QR_SIGNING_SECRET", "smartcart-qr-hmac-secret-key-production-2026")
    
    # Public URLs for QR Connect Links & CORS
    BASE_URL: str = os.getenv("BASE_URL", "http://localhost:5173").rstrip("/")
    API_BASE_URL: str = os.getenv("API_BASE_URL", "http://localhost:8000").rstrip("/")
    CORS_ORIGINS: str = os.getenv("CORS_ORIGINS", "*")
    
    # Database (PostgreSQL with Supabase connection pooler / pgvector)
    DATABASE_URL: Optional[str] = _normalize_db_url(raw_db_url)
    
    # Storage Paths
    UPLOADS_DIR: Path = BASE_DIR / "uploads"
    EVIDENCE_DIR: Path = BASE_DIR / "uploads" / "evidence"
    CATALOG_DIR: Path = BASE_DIR / "uploads" / "catalog"
    MODELS_DIR: Path = BASE_DIR / "models_storage"
    CLIP_MODEL_PATH: Path = BASE_DIR / "models_storage" / "clip_vision_int8.onnx"
    
    # Supabase Object Storage (offloads 360 scan frames to keep Render memory & disk clean)
    SUPABASE_URL: Optional[str] = os.getenv("SUPABASE_URL")
    SUPABASE_SERVICE_ROLE_KEY: Optional[str] = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")
    SUPABASE_STORAGE_BUCKET: str = os.getenv("SUPABASE_STORAGE_BUCKET", "smartcart-360-scans")
    
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

