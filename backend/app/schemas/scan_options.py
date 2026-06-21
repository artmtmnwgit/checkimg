from pydantic import BaseModel, Field

# Toggle fields only — API keys stored separately on the same model for one POST body
SCAN_TOGGLES = (
    "google_search",
    "yandex_search",
    "match_verify",
    "dmca_checks",
    "dmca_lumen_per_image",
    "ai_search",
    "duckduckgo",
    "huggingface",
    "gemini",
    "tineye",
    "perplexity",
    "copilot",
)

SCAN_API_KEYS = (
    "gemini_api_key",
    "huggingface_api_token",
    "tineye_api_key",
    "tineye_api_secret",
    "dmca_api_key",
    "serpapi_key",
)


class ScanOptions(BaseModel):
    """Per-scan toggles + optional API keys (override .env for this scan)."""

    google_search: bool = True
    yandex_search: bool = True
    match_verify: bool = True
    dmca_checks: bool = True
    dmca_lumen_per_image: bool = False
    ai_search: bool = True
    duckduckgo: bool = True
    huggingface: bool = True
    gemini: bool = True
    tineye: bool = False
    perplexity: bool = False
    copilot: bool = False
    gemini_api_key: str = ""
    huggingface_api_token: str = ""
    tineye_api_key: str = ""
    tineye_api_secret: str = ""
    dmca_api_key: str = ""
    serpapi_key: str = ""


class KeysConfigured(BaseModel):
    gemini: bool = False
    huggingface: bool = False
    tineye: bool = False
    dmca: bool = False
    serpapi: bool = False


class ScanOptionsDefaultsResponse(BaseModel):
    defaults: ScanOptions
    presets: dict[str, ScanOptions] = Field(
        description="Named presets: full (env defaults) and fast (minimal external calls)"
    )
    keys_configured: KeysConfigured = Field(description="True when key exists in server .env")
