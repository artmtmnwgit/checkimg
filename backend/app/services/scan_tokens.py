import secrets


def generate_scan_token() -> str:
    return secrets.token_urlsafe(24)
