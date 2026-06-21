from app.config import Settings


def _self_check() -> None:
    assert Settings(cors_origins="http://a.com,http://b.com").cors_origins == [
        "http://a.com",
        "http://b.com",
    ]
    assert Settings(cors_origins="*").cors_origins == ["*"]
    assert Settings(cors_origins='["http://x"]', _env_file=None).cors_origins == ["http://x"]


if __name__ == "__main__":
    _self_check()
    print("config self-check OK")
