import os

# Provide non-default ephemeral test secrets before app.config is imported by tests
os.environ.setdefault("SECRET_KEY", "pytest-ephemeral-jwt-secret-key-for-local-tests")
os.environ.setdefault("QR_SIGNING_SECRET", "pytest-ephemeral-qr-hmac-secret-for-local-tests")
