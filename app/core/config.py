"""Environment-backed application settings with secret-safe representations."""

from functools import lru_cache
from typing import Annotated

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings; optional integrations remain disabled by default."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
        case_sensitive=False,
    )

    app_env: Annotated[str, Field(validation_alias="APP_ENV")] = "development"
    log_level: Annotated[str, Field(validation_alias="LOG_LEVEL")] = "INFO"
    answer_deadline_seconds: Annotated[
        float,
        Field(validation_alias="ANSWER_DEADLINE_SECONDS", gt=0, le=60),
    ] = 50.0
    hcx_enabled: Annotated[bool, Field(validation_alias="HCX_ENABLED")] = False
    hcx_api_key: Annotated[
        SecretStr | None,
        Field(validation_alias="HCX_API_KEY"),
    ] = None
    hcx_api_url: Annotated[
        str | None,
        Field(validation_alias="HCX_API_URL"),
    ] = None
    database_url: Annotated[
        SecretStr | None,
        Field(validation_alias="DATABASE_URL"),
    ] = None

    @field_validator("hcx_api_key", "hcx_api_url", "database_url", mode="before")
    @classmethod
    def empty_string_is_unset(cls, value: object) -> object:
        """Treat empty optional environment variables as absent configuration."""

        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("log_level")
    @classmethod
    def normalize_log_level(cls, value: str) -> str:
        """Normalize and constrain the level understood by stdlib logging."""

        normalized = value.upper()
        allowed = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}
        if normalized not in allowed:
            raise ValueError(f"LOG_LEVEL must be one of {sorted(allowed)}")
        return normalized

    @property
    def hcx_ready(self) -> bool:
        """Whether generation is enabled and has the minimum configuration."""

        return bool(self.hcx_enabled and self.hcx_api_key and self.hcx_api_url)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Load settings once per process; tests may clear the cache explicitly."""

    return Settings()
