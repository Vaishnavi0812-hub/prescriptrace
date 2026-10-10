"""Runtime settings, read from environment variables (see .env.example)."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = (
        "postgresql+psycopg://prescriptrace:change-me-locally@localhost:5432/prescriptrace"
    )
    cors_origins: str = "http://localhost:5173"
    log_level: str = "info"

    normalise_auto_accept: float = Field(0.90, ge=0, le=1)
    normalise_confirm_min: float = Field(0.60, ge=0, le=1)

    # Ask RxNav for suggestions when nothing local matches (capped below auto-accept).
    normalise_external: bool = True

    rate_limit_enabled: bool = True
    rate_limit_search: str = "120/minute"
    rate_limit_normalise: str = "60/minute"
    rate_limit_check: str = "30/minute"

    openfda_api_key: str = ""
    ocr_engine: str = "tesseract"
    llm_provider: str = "none"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
