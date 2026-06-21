from app.services.scan_tokens import generate_scan_token


def _self_check() -> None:
    a = generate_scan_token()
    b = generate_scan_token()
    assert a != b
    assert len(a) >= 16


if __name__ == "__main__":
    _self_check()
    print("scan_tokens self-check OK")
