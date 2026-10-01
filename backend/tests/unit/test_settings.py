import pytest

from app.core.settings import Settings


def test_secrets_are_masked(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:hunter2@db/x")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-secret")
    settings = Settings(_env_file=None)

    rendered = repr(settings) + str(settings.model_dump())
    assert "hunter2" not in rendered
    assert "sk-ant-test-secret" not in rendered
    assert settings.anthropic_api_key is not None
    assert settings.anthropic_api_key.get_secret_value() == "sk-ant-test-secret"


def test_database_url_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ValueError, match="database_url"):
        Settings(_env_file=None)


def test_anthropic_key_is_optional_before_phase_5(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert Settings(_env_file=None).anthropic_api_key is None
