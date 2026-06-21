from app.services.auth import create_access_token, decode_access_token, hash_password, verify_password


def _self_check() -> None:
    h = hash_password("test-pass-123")
    assert verify_password("test-pass-123", h)
    assert not verify_password("wrong", h)
    token = create_access_token(42)
    assert decode_access_token(token) == 42
    assert decode_access_token("not-a-token") is None


if __name__ == "__main__":
    _self_check()
    print("auth self-check OK")
