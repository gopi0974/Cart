import time
import logging
from typing import Optional
from collections import defaultdict
from threading import Lock
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.user import User
from app.schemas.auth import Token, UserLogin, UserCreate, UserResponse
from app.utils.security import verify_password, hash_password, create_access_token, decode_access_token

logger = logging.getLogger("smartcart.auth")

class LoginRateLimiter:
    """Thread-safe sliding-window rate limiter for failed login attempts (5 attempts per 15 min)."""
    def __init__(self, max_attempts: int = 5, window_seconds: int = 900):
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self._failures = defaultdict(list)
        self._lock = Lock()

    def _cleanup(self, now: float):
        cutoff = now - self.window_seconds
        for key in list(self._failures.keys()):
            self._failures[key] = [t for t in self._failures[key] if t > cutoff]
            if not self._failures[key]:
                del self._failures[key]

    def is_rate_limited(self, ip: str, email: str) -> bool:
        now = time.time()
        with self._lock:
            self._cleanup(now)
            ip_attempts = len(self._failures.get(f"ip:{ip}", []))
            email_attempts = len(self._failures.get(f"email:{email}", []))
            return ip_attempts >= self.max_attempts or email_attempts >= self.max_attempts

    def record_failure(self, ip: str, email: str):
        now = time.time()
        with self._lock:
            self._failures[f"ip:{ip}"].append(now)
            self._failures[f"email:{email}"].append(now)

    def record_success(self, ip: str, email: str):
        with self._lock:
            self._failures.pop(f"ip:{ip}", None)
            self._failures.pop(f"email:{email}", None)

    def clear(self):
        with self._lock:
            self._failures.clear()

login_rate_limiter = LoginRateLimiter(max_attempts=5, window_seconds=900)

router = APIRouter(prefix="/auth", tags=["Authentication"])
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")

def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    """Dependency to retrieve authenticated user from JWT bearer token."""
    payload = decode_access_token(token)
    if not payload or "sub" not in payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user = db.query(User).filter(User.email.ilike(str(payload["sub"]).strip())).first()
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account inactive or not found",
        )
    return user

def require_admin_or_manager(current_user: User = Depends(get_current_user)) -> User:
    """Ensure authenticated staff has ADMIN or MANAGER privileges."""
    if current_user.role not in ["ADMIN", "MANAGER"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied: Requires Admin or Manager role."
        )
    return current_user

def require_admin(current_user: User = Depends(get_current_user)) -> User:
    """Ensure authenticated staff has ADMIN privileges."""
    if current_user.role != "ADMIN":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied: Requires Admin role."
        )
    return current_user

def get_client_ip(request: Optional[Request]) -> str:
    """
    Extract the real client IP address:
    1. Inspects 'X-Forwarded-For' header: in reverse-proxy architectures (Render, Cloudflare, AWS),
       the connecting client's true IP is the first entry in the comma-separated chain.
    2. Inspects 'X-Real-IP' as secondary proxy standard.
    3. Falls back to request.client.host if direct connection.
    4. Defaults to '127.0.0.1'.
    """
    if not request or not hasattr(request, "headers"):
        return "127.0.0.1"

    x_forwarded = request.headers.get("x-forwarded-for")
    if x_forwarded:
        ips = [ip.strip() for ip in x_forwarded.split(",") if ip.strip()]
        if ips:
            return ips[0]
            
    x_real_ip = request.headers.get("x-real-ip")
    if x_real_ip and x_real_ip.strip():
        return x_real_ip.strip()

    if request.client and request.client.host:
        return request.client.host
    return "127.0.0.1"


@router.post("/login", response_model=Token)
def login(
    login_data: UserLogin,
    request: Request,
    db: Session = Depends(get_db)
):
    """Staff/Admin login endpoint providing JWT access token with rate limiting protection."""
    if isinstance(request, Session):
        db = request
        request = None

    clean_email = (login_data.email or "").strip().lower()
    clean_password = (login_data.password or "").strip()

    client_ip = get_client_ip(request)

    # Enforce rate limiting: 5 failed attempts per 15 minutes per IP or email
    if login_rate_limiter.is_rate_limited(client_ip, clean_email):
        logger.warning(f"Login rate limit triggered for IP {client_ip} / email {clean_email}")
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed login attempts. Please try again after 15 minutes."
        )

    user = db.query(User).filter(User.email.ilike(clean_email)).first()
    if not user:
        login_rate_limiter.record_failure(client_ip, clean_email)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )

    try:
        is_valid = verify_password(clean_password, user.password_hash)
    except Exception as e:
        logger.warning(f"Password verification exception for {user.email}: {e}")
        is_valid = False

    if not is_valid:
        login_rate_limiter.record_failure(client_ip, clean_email)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Staff account is disabled. Contact store administrator.",
        )

    # Login successful: clear any failure history for this IP/email
    login_rate_limiter.record_success(client_ip, clean_email)

    access_token = create_access_token(data={"sub": user.email, "role": user.role})
    return Token(
        access_token=access_token,
        token_type="bearer",
        role=user.role,
        full_name=user.full_name,
        email=user.email
    )

@router.get("/me", response_model=UserResponse)
def get_me(current_user: User = Depends(get_current_user)):
    """Retrieve current authenticated staff member profile."""
    return current_user

@router.get("/staff", response_model=list[UserResponse])
def list_staff(current_user: User = Depends(require_admin), db: Session = Depends(get_db)):
    """List all staff accounts (Admin only)."""
    return db.query(User).all()

@router.post("/staff", response_model=UserResponse)
def create_staff(user_in: UserCreate, current_user: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Create new staff account (Admin only)."""
    existing = db.query(User).filter(User.email == user_in.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="User with this email already exists.")
    
    new_user = User(
        email=user_in.email,
        password_hash=hash_password(user_in.password),
        full_name=user_in.full_name,
        role=user_in.role
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return new_user
