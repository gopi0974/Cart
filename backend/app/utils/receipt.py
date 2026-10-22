import random
import string
from datetime import datetime

def generate_receipt_number() -> str:
    """Generate sequential-style receipt number e.g. REC-20261020-8492."""
    date_str = datetime.utcnow().strftime("%Y%m%d")
    random_suffix = "".join(random.choices(string.digits, k=4))
    return f"REC-{date_str}-{random_suffix}"

def generate_exit_token(receipt_number: str) -> str:
    """Generate secure exit turnstile QR verification token."""
    random_salt = "".join(random.choices(string.ascii_uppercase + string.digits, k=8))
    return f"EXIT-{receipt_number}-{random_salt}"
