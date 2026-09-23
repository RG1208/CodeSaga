import pytest
from pydantic import ValidationError

from app.core.config import Settings


def _settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[call-arg]


def test_defaults_are_development_friendly(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("APP_ENV", "API_V1_PREFIX", "CORS_ORIGINS", "LOG_LEVEL"):
        monkeypatch.delenv(name, raising=False)

    settings = _settings()

    assert settings.app_env == "development"
    assert settings.api_v1_prefix == "/api/v1"
    assert settings.cors_origins == ["http://localhost:3000"]
    assert not settings.is_production


def test_cors_origins_parsed_from_comma_separated_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:3000, https://app.example.com/ ,")

    assert _settings().cors_origins == ["http://localhost:3000", "https://app.example.com"]


def test_log_level_is_case_insensitive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOG_LEVEL", "debug")

    assert _settings().log_level == "DEBUG"


def test_invalid_environment_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _settings(app_env="moon")
