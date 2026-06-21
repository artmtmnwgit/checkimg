"""Strip chars that break PostgreSQL JSONB (NUL, control chars)."""

from typing import Any


def clean_text(value: str, max_len: int = 2000) -> str:
    cleaned = "".join(c for c in value if c in "\n\t\r" or ord(c) >= 32)
    return cleaned[:max_len]


def sanitize_json(value: Any, max_str: int = 2000) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return clean_text(value, max_str)
    if isinstance(value, bytes):
        return clean_text(value.decode("utf-8", errors="ignore"), max_str)
    if isinstance(value, dict):
        return {clean_text(str(k), 256): sanitize_json(v, max_str) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [sanitize_json(v, max_str) for v in value]
    return clean_text(str(value), max_str)
