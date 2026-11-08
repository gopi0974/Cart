import secrets
from typing import Optional
from sqlalchemy.orm import Session
from app.models.user import User
from app.models.session import CartSession
from app.utils.security import decode_access_token


def authenticate_admin_ws(token: Optional[str], db: Session) -> Optional[User]:
    """
    Authenticate /ws/admin connection.
    Requires a valid staff JWT with an active User having role ADMIN, MANAGER, or STAFF.
    """
    if not token or not token.strip():
        return None

    payload = decode_access_token(token.strip())
    if not payload or "sub" not in payload:
        return None

    email = str(payload["sub"]).strip()
    user = db.query(User).filter(User.email.ilike(email)).first()
    if not user or not user.is_active or user.role not in ["ADMIN", "MANAGER", "STAFF"]:
        return None

    return user


def authenticate_cart_ws(cart_id: str, token: Optional[str], db: Session) -> bool:
    """
    Authenticate /ws/cart/{cart_id} connection.
    Allows either:
    1. Valid shopper session token matching an ACTIVE CartSession for cart_id.
    2. Valid staff JWT access token.
    """
    if not token or not token.strip():
        return False

    clean_token = token.strip()

    # 1. Check if token matches active shopper CartSession for this cart_id
    active_session = db.query(CartSession).filter(
        CartSession.cart_id == cart_id,
        CartSession.status == "ACTIVE"
    ).first()

    if active_session and active_session.session_token:
        if secrets.compare_digest(clean_token, active_session.session_token):
            return True

    # 2. Check if token is a valid staff JWT
    payload = decode_access_token(clean_token)
    if payload and "sub" in payload:
        email = str(payload["sub"]).strip()
        user = db.query(User).filter(User.email.ilike(email)).first()
        if user and user.is_active and user.role in ["ADMIN", "MANAGER", "STAFF"]:
            return True

    return False
