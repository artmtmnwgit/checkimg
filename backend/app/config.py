from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "sqlite:///./checkimg.db"
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"

    crawl_timeout_sec: float = 12.0
    crawl_connect_timeout_sec: float = 8.0
    crawl_max_pages: int = 500
    crawl_concurrency: int = 10
    crawl_max_stylesheets: int = 8
    crawl_max_images_per_page: int = 150
    crawl_max_image_bytes: int = 12_000_000
    image_store_dir: str = "./data/images"

    serpapi_key: str = ""
    reverse_search_provider: str = "google_lens"  # google_lens | serpapi
    yandex_search_enabled: bool = True

    dmca_api_key: str = ""
    dmca_api_url: str = "https://api.dmca.com/api/v3/protection/status"
    dmca_checks_enabled: bool = True
    dmca_lumen_per_image: bool = False
    dmca_external_timeout_sec: float = 8.0
    check_concurrency: int = 4

    match_verify_enabled: bool = True
    match_verify_top_n: int = 4
    match_verify_concurrency: int = 3
    match_verify_timeout_sec: float = 5.0
    match_verify_max_bytes: int = 2_000_000

    # TinEye (optional reverse search)
    tineye_enabled: bool = False
    tineye_api_key: str = ""
    tineye_api_secret: str = ""

    # AI search module (1.2.7)
    ai_search_enabled: bool = True
    ai_search_timeout_sec: float = 12.0
    gemini_api_key: str = ""
    gemini_model: str = "gemini-1.5-flash"
    huggingface_api_token: str = ""
    huggingface_enabled: bool = True
    duckduckgo_search_enabled: bool = True
    perplexity_enabled: bool = False
    copilot_enabled: bool = False
    hf_ai_generated_threshold: float = 0.8
    hf_watermark_threshold: float = 0.7

    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:3000"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
