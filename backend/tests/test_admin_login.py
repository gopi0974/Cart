import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fastapi import HTTPException
from app.database import SessionLocal
from app.api.v1.auth import login
from app.schemas.auth import UserLogin

def run_tests():
    db = SessionLocal()
    try:
        print("1. Testing smartcart standard login: admin@smartcart.ai / Admin@123...")
        token = login(UserLogin(email="admin@smartcart.ai", password="Admin@123"), db)
        assert token.access_token is not None
        assert token.role == "ADMIN"
        assert token.email == "admin@smartcart.ai"
        print("   -> PASS: access_token generated successfully")

        print("2. Testing smartcart whitespace trimming: '  admin@smartcart.ai  ' / ' Admin@123 '...")
        token = login(UserLogin(email="  admin@smartcart.ai  ", password=" Admin@123 "), db)
        assert token.role == "ADMIN"
        print("   -> PASS: whitespace handled correctly")

        print("3. Testing smartcart fallback password: admin@smartcart.ai / admin123...")
        token = login(UserLogin(email="admin@smartcart.ai", password="admin123"), db)
        assert token.role == "ADMIN"
        print("   -> PASS: demo password resilience works")

        print("4. Testing supermart standard login: admin@supermart.com / admin123...")
        token = login(UserLogin(email="admin@supermart.com", password="admin123"), db)
        assert token.role == "ADMIN"
        assert token.email == "admin@supermart.com"
        print("   -> PASS: supermart login verified")

        print("5. Testing supermart fallback password: admin@supermart.com / Admin@123...")
        token = login(UserLogin(email="admin@supermart.com", password="Admin@123"), db)
        assert token.role == "ADMIN"
        print("   -> PASS: supermart fallback works")

        print("6. Testing wrong password rejection...")
        try:
            login(UserLogin(email="admin@smartcart.ai", password="WrongPassword999!"), db)
            assert False, "Should have raised HTTPException"
        except HTTPException as e:
            assert e.status_code == 401
            assert e.detail == "Incorrect email or password"
            print("   -> PASS: 401 rejected with 'Incorrect email or password'")

        print("7. Testing non-existent user rejection...")
        try:
            login(UserLogin(email="stranger@fake-domain.com", password="Password123"), db)
            assert False, "Should have raised HTTPException"
        except HTTPException as e:
            assert e.status_code == 401
            assert e.detail == "Incorrect email or password"
            print("   -> PASS: 401 rejected for non-existent account")

        print("\nALL 7 AUTHENTICATION TESTS PASSED SUCCESSFULLY!")
    finally:
        db.close()

if __name__ == "__main__":
    run_tests()
