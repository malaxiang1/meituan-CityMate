from __future__ import annotations

from functools import lru_cache
from os import getenv

from pydantic import BaseModel


class Settings(BaseModel):
    app_name: str = "CityMate"
    environment: str = getenv("CITYMATE_ENV", "local")
    use_live_data: bool = getenv("CITYMATE_USE_LIVE_DATA", "true").lower() == "true"
    request_timeout: float = float(getenv("CITYMATE_REQUEST_TIMEOUT", "6.0"))
    map_provider: str = getenv("CITYMATE_MAP_PROVIDER", "open").lower()
    amap_web_service_key: str = getenv("AMAP_WEB_SERVICE_KEY", getenv("CITYMATE_AMAP_KEY", ""))
    vendor_api_url: str = getenv("CITYMATE_VENDOR_API_URL", "")
    vendor_api_key: str = getenv("CITYMATE_VENDOR_API_KEY", "")
    vendor_api_key_header: str = getenv("CITYMATE_VENDOR_API_KEY_HEADER", "Authorization")
    llm_provider: str = getenv("CITYMATE_LLM_PROVIDER", "mock")
    openai_api_key: str = getenv("OPENAI_API_KEY", "")
    openai_base_url: str = getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    openai_model: str = getenv("OPENAI_MODEL", "gpt-4o-mini")


@lru_cache
def get_settings() -> Settings:
    return Settings()
