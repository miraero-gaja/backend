"""Configuration safety checks."""

from collections.abc import Iterator

import pytest
from pydantic import ValidationError

from app.core.config import Settings

SETTING_NAMES = (
    "APP_ENV",
    "LOG_LEVEL",
    "ANSWER_DEADLINE_SECONDS",
    "HCX_ENABLED",
    "HCX_API_KEY",
    "HCX_API_URL",
    "DATABASE_URL",
)


@pytest.fixture(autouse=True)
def isolated_settings_environment(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Prevent developer-machine settings from influencing these unit tests."""

    for name in SETTING_NAMES:
        monkeypatch.delenv(name, raising=False)
    yield


def test_settings_can_start_without_external_services() -> None:
    settings = Settings(_env_file=None)

    assert settings.hcx_enabled is False
    assert 0 < settings.answer_deadline_seconds <= 60


def test_settings_exposes_only_the_declared_foundation_fields() -> None:
    assert set(Settings.model_fields) == {
        "app_env",
        "log_level",
        "answer_deadline_seconds",
        "hcx_enabled",
        "hcx_api_key",
        "hcx_api_url",
        "database_url",
    }


def test_answer_deadline_cannot_exceed_internal_budget() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, ANSWER_DEADLINE_SECONDS=61)


def test_settings_rendering_redacts_api_key_and_database_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api_key = "test-only-hcx-key-must-not-leak"
    database_password = "test-only-db-password-must-not-leak"
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    monkeypatch.setenv("ANSWER_DEADLINE_SECONDS", "60")
    monkeypatch.setenv("HCX_ENABLED", "true")
    monkeypatch.setenv("HCX_API_KEY", api_key)
    monkeypatch.setenv("HCX_API_URL", "https://hcx.invalid.example/v1")
    monkeypatch.setenv(
        "DATABASE_URL",
        f"postgresql://test-user:{database_password}@db.invalid/test-db",
    )

    settings = Settings(_env_file=None)
    rendered = "\n".join(
        (repr(settings), str(settings), settings.model_dump_json())
    )

    assert api_key not in rendered
    assert database_password not in rendered
