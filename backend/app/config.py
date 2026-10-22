import os
from pathlib import Path
from pydantic import BaseModel

BASE_DIR = Path(__file__).resolve().parent.parent

class Settings(BaseModel):
    PROJECT_NAME: str = os.getenv("PROJECT_NAME", "SmartCart AI - Autonomous Retail Backend")
    VERSION: str = "1.0.0"
    API_V1_STR: str = "/api/v1"
    
    # Security
    SECRET_KEY: str = os.getenv("SECRET_KEY", "smartcart-super-secret-key-change-in-production-2026")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24 hours
    
    # Database (SQLite with WAL or PostgreSQL)
    DATABASE_URL: str = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR}/smartcart.db")
    
    # Storage Paths
    UPLOADS_DIR: Path = BASE_DIR / "uploads"
    EVIDENCE_DIR: Path = BASE_DIR / "uploads" / "evidence"
    CATALOG_DIR: Path = BASE_DIR / "uploads" / "catalog"
    MODELS_DIR: Path = BASE_DIR / "models_storage"
    
    # AI / Vision Thresholds
    CONFIDENCE_HIGH: float = float(os.getenv("CONFIDENCE_HIGH", "0.85"))
    CONFIDENCE_MEDIUM: float = float(os.getenv("CONFIDENCE_MEDIUM", "0.65"))
    CONFIDENCE_LOW: float = float(os.getenv("CONFIDENCE_LOW", "0.50"))
    
    # Payment Gateway
    PAYMENT_MODE: str = os.getenv("PAYMENT_MODE", "SANDBOX")

settings = Settings()

# Ensure directories exist
settings.UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
settings.EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
settings.CATALOG_DIR.mkdir(parents=True, exist_ok=True)
settings.MODELS_DIR.mkdir(parents=True, exist_ok=True)
