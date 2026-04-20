import re
import uuid
import threading
import contextlib
import socket
import hashlib
import os
import platform
from datetime import datetime
from typing import Any, Dict, Tuple, List


# -----------------------------
# Sensitive data masking helpers
# -----------------------------

# Keys that should always be redacted when present (case-insensitive)
_SENSITIVE_KEYS = {
    # Auth/Secrets
    "authorization",
    "bearer",
    "access_token",
    "refresh_token",
    "api_key",
    "client_secret",
    "password",
    "secret",
    "cookie",
    "session_id",
    "private_key",
    "key",
    # Financial/PII
    "iban",
    "iban_number",
    "bank_account",
    "account",
    "account_number",
    "cc",
    "card",
    "card_number",
    "credit_card",
    "ssn",
    "ahv",
    "avs",
    "email",
}


def _mask_tail(value: str, visible_tail: int = 4) -> str:
    if not isinstance(value, str):
        value = str(value)
    if len(value) <= visible_tail:
        return "****"
    return f"***{value[-visible_tail:]}"


def _mask_full(_: str = "") -> str:
    return "****"


# Precompiled regex patterns (case-insensitive) with a named group 'val' for replacement
# 1) JSON-style:  "key": "value"
_JSON_PAIR_RE = re.compile(
    r"\b(\"(?P<key>authorization|access_token|refresh_token|api_key|client_secret|password|cookie|session_id|secret|key|iban|account|account_number|bank_account|card|card_number|credit_card|email)\"\s*:\s*\")(?P<val>[^\"]+)(\")",
    re.IGNORECASE,
)

# 2) Query/header style: key=value (within URLs or plain text)
_QUERY_PAIR_RE = re.compile(
    r"(?P<key>authorization|access_token|refresh_token|api_key|client_secret|password|cookie|session_id|secret|key|iban|account|account_number|bank_account|card|card_number|credit_card|email)\s*=\s*(?P<val>[^&\s]+)",
    re.IGNORECASE,
)

# 3) HTTP Authorization: Bearer <token>
_AUTH_BEARER_RE = re.compile(r"(Authorization\s*:\s*Bearer\s+)(?P<val>[A-Za-z0-9_\-\.=:+/]+)", re.IGNORECASE)

# 4) JWT-like tokens (3 base64url segments)
_JWT_RE = re.compile(r"\b(?P<val>[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)\b")

# 5) Long hex strings (e.g., keys) and base64-like long blobs
_LONG_HEX_RE = re.compile(r"\b(?P<val>[a-fA-F0-9]{32,})\b")
_BASE64ISH_RE = re.compile(r"\b(?P<val>[A-Za-z0-9+/]{30,}={0,2})\b")

# 6) IBAN (generic)
_IBAN_RE = re.compile(r"\b(?P<val>[A-Z]{2}\d{2}[A-Z0-9]{10,30})\b")

# 7) Credit card number (13–19 digits, spaces/dashes allowed)
_CC_RE = re.compile(r"\b(?P<val>(?:\d[ -]*?){13,19})\b")

# 8) Email address
_EMAIL_RE = re.compile(r"\b(?P<val>[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})\b")

# 9) Swiss AHV/AVS number (e.g., 756.1234.5678.97)
_AHV_RE = re.compile(r"\b(?P<val>756\.\d{4}\.\d{4}\.\d{2})\b")


def _sub_mask_tail(match: re.Match) -> str:
    prefix = match.group(1) if match.lastindex and match.lastindex >= 1 else ""
    val = match.group("val")
    suffix = match.group(match.lastindex) if match.lastindex and match.lastindex >= 4 else ""
    return f"{prefix}{_mask_tail(val)}{suffix}"


def mask_sensitive_data(message: str) -> str:
    """
    Masks sensitive data in log messages.

    - Case-insensitive for common secret keys
    - Supports JSON "key": "value", query/header key=value, and Authorization: Bearer patterns
    - Redacts JWTs, long hex, base64-like blobs, IBANs, credit cards (keeps last 4), and emails/AHV
    
    Can be disabled via environment variable DISABLE_LOG_MASKING=true (dev only, not recommended for production)
    """
    if not message:
        return message
    
    # Allow disabling masking for development/debugging (NOT recommended for production)
    if os.getenv("DISABLE_LOG_MASKING", "false").lower() == "true":
        return message

    # JSON pairs
    message = _JSON_PAIR_RE.sub(_sub_mask_tail, message)

    # Query/header pairs
    message = _QUERY_PAIR_RE.sub(lambda m: f"{m.group('key')}={_mask_tail(m.group('val'))}", message)

    # Authorization bearer
    message = _AUTH_BEARER_RE.sub(lambda m: f"{m.group(1)}{_mask_tail(m.group('val'))}", message)

    # Generic token-like values (tail-masked)
    for regex in (_JWT_RE, _LONG_HEX_RE, _BASE64ISH_RE, _IBAN_RE, _CC_RE):
        message = regex.sub(lambda m: _mask_tail(m.group('val')), message)

    # Emails (fully masked)
    message = _EMAIL_RE.sub(lambda m: _mask_full(m.group('val')), message)

    # Swiss AHV/AVS (tail-masked lightly)
    message = _AHV_RE.sub(lambda m: _mask_tail(m.group('val'), visible_tail=2), message)

    return message


def _mask_if_sensitive_key(key: str, value: Any, masked_fields: List[str]) -> Any:
    """
    Redact value if the key is considered sensitive. Returns masked value and records the field.
    """
    try:
        key_lower = (key or "").lower()
    except Exception:
        key_lower = str(key).lower()

    if key_lower in _SENSITIVE_KEYS:
        masked_fields.append(key_lower)
        if isinstance(value, str):
            # Email gets full mask; others tail-masked
            if key_lower == "email":
                return _mask_full(value)
            return _mask_tail(value)
        return "****"
    return value


def _mask_value_by_pattern(value: Any, masked_fields: List[str]) -> Any:
    """
    Apply value-based masking for strings (JWTs, long hex/base64, IBAN/CC/email/AHV) even if the key is not sensitive.
    """
    if not isinstance(value, str):
        return value

    original = value
    masked = value
    # Tail-masked patterns
    for regex in (_JWT_RE, _LONG_HEX_RE, _BASE64ISH_RE, _IBAN_RE, _CC_RE):
        masked = regex.sub(lambda m: _mask_tail(m.group('val')), masked)

    # Emails full masked
    masked = _EMAIL_RE.sub(lambda m: _mask_full(m.group('val')), masked)

    # AHV lightly tail-masked
    masked = _AHV_RE.sub(lambda m: _mask_tail(m.group('val'), visible_tail=2), masked)

    # Also apply JSON/query/bearer forms in case raw fragments appear
    masked = _AUTH_BEARER_RE.sub(lambda m: f"{m.group(1)}{_mask_tail(m.group('val'))}", masked)
    masked = _QUERY_PAIR_RE.sub(lambda m: f"{m.group('key')}={_mask_tail(m.group('val'))}", masked)

    if masked != original:
        masked_fields.append("value_pattern")
    return masked


def mask_sensitive_context(context: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    """
    Return a deep-masked copy of the provided context, and a list of masked field names.
    - Masks by key name (authorization, access_token, password, etc.)
    - Masks by value pattern (JWTs, long hex/base64, IBAN/CC/email/AHV, bearer tokens)
    
    Can be disabled via environment variable DISABLE_LOG_MASKING=true (dev only, not recommended for production)
    """
    masked_fields: List[str] = []
    
    # Allow disabling masking for development/debugging (NOT recommended for production)
    if os.getenv("DISABLE_LOG_MASKING", "false").lower() == "true":
        return context or {}, masked_fields

    def _walk(value: Any) -> Any:
        # Dict: mask keys and recurse
        if isinstance(value, dict):
            result: Dict[str, Any] = {}
            for k, v in value.items():
                v2 = _mask_if_sensitive_key(k, v, masked_fields)
                # If not masked via key, still scan content
                v2 = _walk(v2)
                # Finally, pattern-based masking for strings
                v2 = _mask_value_by_pattern(v2, masked_fields)
                result[k] = v2
            return result
        # List/Tuple: recurse each item
        if isinstance(value, (list, tuple)):
            return type(value)(_walk(item) for item in value)
        # Strings: pattern-based masking
        if isinstance(value, str):
            return _mask_value_by_pattern(value, masked_fields)
        # Other scalars
        return value

    masked_context = _walk(context or {})
    return masked_context, masked_fields


# -----------------------------
# Correlation ID helpers
# -----------------------------

# Thread-local storage for correlation IDs
_request_context = threading.local()


def _generate_correlation_id() -> str:
    """
    Internal function to generate a new strong correlation ID

    Format: timestamp-environment-hostname-process-random-checksum

    This provides:
    - Temporal tracing (when)
    - Environmental context (where)
    - Process identity (which process)
    - Uniqueness (random component)
    - Integrity verification (checksum)
    """
    # Get timestamp with millisecond precision
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S%f")[:-3]

    # Get environment and hostname components
    env = os.getenv("APP_ENV", "dev")
    hostname = socket.gethostname()
    if len(hostname) > 8:
        hostname = hostname[:8]  # Truncate long hostnames

    # Process information
    pid = os.getpid()

    # Random component for uniqueness
    random_component = uuid.uuid4().hex[:8]

    # Create base ID
    base_id = f"{timestamp}-{env}-{hostname}-{pid}-{random_component}"

    # Add checksum for integrity verification
    checksum = hashlib.md5(base_id.encode()).hexdigest()[:6]

    return f"{base_id}-{checksum}"


def explain_correlation_id(correlation_id):
    """
    Parse and explain the components of a correlation ID

    Args:
        correlation_id: The correlation ID to explain

    Returns:
        Dictionary with correlation ID components
    """
    try:
        # Check if it's our enhanced format with the expected structure
        # Format: timestamp-environment-hostname-process-random-checksum
        parts = correlation_id.split("-")

        # Need at least 6 parts for our enhanced format
        if len(parts) >= 6:
            timestamp = parts[0]
            environment = parts[1]
            hostname = parts[2]
            process_id = parts[3]
            random_part = parts[4]
            checksum = parts[5]

            # Format timestamp for human readability
            year = timestamp[0:4]
            month = timestamp[4:6]
            day = timestamp[6:8]
            hour = timestamp[8:10]
            minute = timestamp[10:12]
            second = timestamp[12:14]
            ms = timestamp[14:] if len(timestamp) > 14 else "000"

            readable_time = f"{year}-{month}-{day} {hour}:{minute}:{second}.{ms}"

            return {
                "timestamp": readable_time,
                "environment": environment,
                "hostname": hostname,
                "process_id": process_id,
                "random_component": random_part,
                "checksum": checksum,
                "format": "enhanced",
            }

        # It must be a custom or legacy format
        if len(parts) >= 2 and parts[0].isdigit() and len(parts[0]) >= 14:
            # Looks like a timestamp-based format but not our enhanced one
            timestamp = parts[0]
            year = timestamp[0:4]
            month = timestamp[4:6]
            day = timestamp[6:8]
            hour = timestamp[8:10]
            minute = timestamp[10:12]
            second = timestamp[12:14]
            ms = timestamp[14:] if len(timestamp) > 14 else "000"

            readable_time = f"{year}-{month}-{day} {hour}:{minute}:{second}.{ms}"

            return {
                "timestamp": readable_time,
                "format": "simple-timestamp-based",
                "additional_components": parts[1:],
            }

        # Completely custom format
        return {
            "format": "custom",
            "notes": "Unrecognized correlation ID format",
            "raw_value": correlation_id,
        }
    except Exception as e:
        # Return basic information in case of parsing errors
        return {"format": "unknown", "error": str(e), "raw_value": correlation_id}


def get_correlation_id() -> str:
    """
    Returns the current correlation ID for request tracing.
    If no correlation ID exists, generates a new one.

    Returns:
        The correlation ID string
    """
    if not hasattr(_request_context, "correlation_id"):
        _request_context.correlation_id = _generate_correlation_id()

    return _request_context.correlation_id


def set_correlation_id(correlation_id: str = None) -> str:
    """
    Explicitly sets the correlation ID to a specific value or generates a new one.

    Args:
        correlation_id: Custom correlation ID to set. If None, generates a new one.

    Returns:
        The set correlation ID
    """
    _request_context.correlation_id = correlation_id or _generate_correlation_id()
    return _request_context.correlation_id


def reset_correlation_id() -> None:
    """
    Explicitly resets the correlation ID.
    """
    if hasattr(_request_context, "correlation_id"):
        delattr(_request_context, "correlation_id")


@contextlib.contextmanager
def correlation_scope(correlation_id: str = None):
    """
    Context manager for handling correlation ID lifecycle.

    Automatically manages the lifecycle of a correlation ID:
    1. Sets/creates a correlation ID at the beginning of the scope
    2. Yields control back to the caller
    3. Restores the previous correlation ID (if any) when exiting the scope

    Example:
        with correlation_scope():
            # Code in this block uses the same correlation ID
            log_something()  # Uses the scoped correlation ID
            process_data()   # Still uses the same correlation ID
        # Previous correlation ID (if any) is restored here

    Args:
        correlation_id: Optional custom correlation ID. If None, generates a new one.
    """
    # Save the previous correlation ID if it exists
    previous_id = None
    if hasattr(_request_context, "correlation_id"):
        previous_id = _request_context.correlation_id

    # Set the new correlation ID for this scope
    new_id = correlation_id or _generate_correlation_id()
    _request_context.correlation_id = new_id

    try:
        yield new_id
    finally:
        # Restore the previous correlation ID or remove it
        if previous_id is not None:
            _request_context.correlation_id = previous_id
        else:
            reset_correlation_id()


def get_current_datetime() -> str:
    """
    Returns the current date and time in a readable format
    """
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
