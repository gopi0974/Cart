import random
import string
from datetime import datetime

def generate_receipt_number() -> str:
    """Generate sequential-style receipt number e.g. REC-20261020-8492."""
    date_str = datetime.utcnow().strftime("%Y%m%d")
    random_suffix = "".join(random.choices(string.digits, k=4))
    return f"REC-{date_str}-{random_suffix}"

