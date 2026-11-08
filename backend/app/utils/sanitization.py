import re
import logging
from typing import Any, Optional

# Match credentials in URIs: scheme://username:password@host...
# Covers URLs where password contains percent-encoded characters (%21, %40, %25, etc.) or raw characters
URL_CRED_PATTERN = re.compile(r"([a-zA-Z][a-zA-Z0-9+.-]*://)([^/\s:@]+):([^/\s@]+)@")

# Query parameters like password=..., token=..., secret=..., key=...
QUERY_SECRET_PATTERN = re.compile(r"(?i)(password|secret|token|key|api_key|pwd)=([^&\s'\"]+)")

# Bearer tokens in headers, logs, or error strings
BEARER_PATTERN = re.compile(r"(?i)bearer\s+[a-zA-Z0-9._~+/-]+=*")


def sanitize_secrets(value: Any) -> Any:
    """
    Recursively sanitize strings, dicts, lists, or exceptions to mask database passwords,
    auth tokens, keys, and connection strings.
    Never exposes raw credentials in user-facing responses, diagnostics, or logs.
    """
    if value is None:
        return None
    if isinstance(value, str):
        # 1. Mask user:password in URLs (e.g. postgresql://user:pass@host -> postgresql://user:***@host)
        text = URL_CRED_PATTERN.sub(r"\1\2:***@", value)
        # 2. Mask secret query parameters
        text = QUERY_SECRET_PATTERN.sub(r"\1=***", text)
        # 3. Mask Bearer tokens
        text = BEARER_PATTERN.sub("Bearer ***", text)
        return text
    if isinstance(value, dict):
        return {k: sanitize_secrets(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [sanitize_secrets(item) for item in value]
    if isinstance(value, Exception):
        return sanitize_secrets(str(value))
    return value


def mask_url(url: Optional[str]) -> Optional[str]:
    """Specifically masks credentials in a database or API URL."""
    if not url:
        return url
    return sanitize_secrets(str(url))


class SanitizingLogFilter(logging.Filter):
    """Logging filter that ensures no secret URLs or tokens appear in log records."""
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = sanitize_secrets(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {k: sanitize_secrets(v) for k, v in record.args.items()}
            elif isinstance(record.args, tuple):
                record.args = tuple(sanitize_secrets(v) for v in record.args)
        return True
