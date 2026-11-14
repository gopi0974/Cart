import os
from typing import Optional
from pathlib import Path
from urllib.parse import urlparse
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

def is_valid_base_url(url: Optional[str], demo_mode: bool = False) -> bool:
    """
    Validate public BASE_URL for QR link generation.
    In production (demo_mode=False), BASE_URL must:
      1. Be present and non-empty.
      2. Start with https://
      3. NOT contain localhost, 127.0.0.1, or 0.0.0.0.
    In demo mode, http:// and localhost are permitted for local development.
    """
    if not url or not str(url).strip():
        return False
    clean = str(url).strip()
    clean_lower = clean.lower()
    if not demo_mode:
        if "localhost" in clean_lower or "127.0.0.1" in clean_lower or "0.0.0.0" in clean_lower:
            return False
        if not clean_lower.startswith("https://"):
            return False
    else:
        if not (clean_lower.startswith("http://") or clean_lower.startswith("https://")):
            return False
    try:
        parsed = urlparse(clean)
        return bool(parsed.hostname)
    except Exception:
        return False

def get_base_url_host(url: Optional[str]) -> Optional[str]:
    """
    Extract host only (no scheme, no port, no credentials/secrets, no paths).
    Example: 'https://cart-9tds.vercel.app' -> 'cart-9tds.vercel.app'
    """
    if not url or not str(url).strip():
        return None
    try:
        clean = str(url).strip()
        if not clean.startswith(("http://", "https://")):
            clean = f"https://{clean}"
        parsed = urlparse(clean)
        return parsed.hostname
    except Exception:
        return None

raw_db_url = os.getenv("DATABASE_URL")

_is_demo_mode = os.getenv("DEMO_MODE", "false").lower() in ("true", "1", "yes")

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
    DEMO_MODE: bool = _is_demo_mode
    USE_MOCK: bool = os.getenv("USE_MOCK", "false").lower() in ("true", "1", "yes")
    
    # Cart QR HMAC Signing Secret
    QR_SIGNING_SECRET: str = os.getenv("QR_SIGNING_SECRET", "smartcart-qr-hmac-secret-key-production-2026")
    
    # Public URLs for QR Connect Links & CORS
    BASE_URL: str = os.getenv("BASE_URL", "http://localhost:5173" if _is_demo_mode else "").rstrip("/")
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
    CONFIDENCE_LOW: float = float(os.getenv("CONFIDENCE_LOW", "0.65"))
    UNSCANNED_GRACE_PERIOD_SECONDS: float = float(os.getenv("UNSCANNED_GRACE_PERIOD_SECONDS", "10.0"))
    EVIDENCE_RETENTION_DAYS: int = int(os.getenv("EVIDENCE_RETENTION_DAYS", "14"))
    CURRENT_PREPROCESSING_VERSION: str = os.getenv("CURRENT_PREPROCESSING_VERSION", "v2_bilinear_224")
    # Face on Packaging policy: "withhold" (default, privacy-first) or "mask_and_judge"
    FACE_ON_PACKAGING_MODE: str = os.getenv("FACE_ON_PACKAGING_MODE", "withhold").lower()
    
    # Payment Gateway (Test mode only)
    PAYMENT_MODE: str = os.getenv("PAYMENT_MODE", "TEST")
    PAYMENT_KEY_ID: str = os.getenv("PAYMENT_KEY_ID", "rzp_test_smartcart2026")
    PAYMENT_KEY_SECRET: str = os.getenv("PAYMENT_KEY_SECRET", "test_secret_mock_sandbox")

settings = Settings()

CURRENT_PREPROCESSING_VERSION = settings.CURRENT_PREPROCESSING_VERSION
FACE_ON_PACKAGING_MODE = settings.FACE_ON_PACKAGING_MODE

# Ensure directories exist
settings.UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
settings.EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
settings.CATALOG_DIR.mkdir(parents=True, exist_ok=True)
settings.MODELS_DIR.mkdir(parents=True, exist_ok=True)

