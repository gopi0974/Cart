import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fastapi import HTTPException
from app.database import SessionLocal
from app.api.v1.auth import login
from app.schemas.auth import UserLogin
from app.models.user import User
from app.utils.security import hash_password

def run_tests():
    if not SessionLocal:
        print("Database not configured, skipping login test.")
        return

    db = SessionLocal()
    try:
        # Ensure a clean test user
        test_email = "testadmin@smartcart.ai"
        test_pwd = "SecureTestPassword123!"

        user = db.query(User).filter(User.email == test_email).first()
        if not user:
            user = User(
                email=test_email,
                password_hash=hash_password(test_pwd),
                full_name="Test Administrator",
                role="ADMIN",
                is_active=True
            )
            db.add(user)
            db.commit()

        print("1. Testing valid credentials...")
        token = login(UserLogin(email=test_email, password=test_pwd), db)
        assert token.access_token is not None
        assert token.role == "ADMIN"
        assert token.email == test_email
        print("   -> PASS: access_token generated successfully")

        print("2. Testing email/password whitespace trimming...")
        token = login(UserLogin(email=f"  {test_email}  ", password=f" {test_pwd} "), db)
        assert token.role == "ADMIN"
        print("   -> PASS: whitespace handled correctly")

        print("3. Testing wrong password rejection...")
        try:
            login(UserLogin(email=test_email, password="WrongPassword999!"), db)
            assert False, "Should have raised HTTPException"
        except HTTPException as e:
            assert e.status_code == 401
            assert e.detail == "Incorrect email or password"
            print("   -> PASS: 401 rejected with 'Incorrect email or password'")

        print("4. Testing non-existent user rejection...")
        try:
            login(UserLogin(email="stranger@unknown-domain.xyz", password="SomePassword123"), db)
            assert False, "Should have raised HTTPException"
        except HTTPException as e:
            assert e.status_code == 401
            assert e.detail == "Incorrect email or password"
            print("   -> PASS: 401 rejected for non-existent account")

        print("\nALL AUTHENTICATION TESTS PASSED SUCCESSFULLY!")
    finally:
        db.close()

if __name__ == "__main__":
    run_tests()
