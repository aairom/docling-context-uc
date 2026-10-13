from pathlib import Path

import pytest

from dcuc.config import LLMSettings, Settings


def test_defaults_are_local_and_safe():
    settings = Settings.from_env(env_file=None)
    assert settings.app_host == "127.0.0.1"
    assert settings.app_port == 7860
    assert not settings.llm.enabled
    assert not settings.enable_vectors


def test_env_overrides(monkeypatch):
    monkeypatch.setenv("DC_COLLECTION", "papers")
    monkeypatch.setenv("DC_ENABLE_VECTORS", "yes")
    monkeypatch.setenv("LLM_BASE_URL", "http://localhost:9931/v1/")
    monkeypatch.setenv("APP_PORT", "8501")
    settings = Settings.from_env(env_file=None)
    assert settings.collection == "papers"
    assert settings.enable_vectors is True
    assert settings.llm.base_url == "http://localhost:9931/v1"  # trailing slash removed
    assert settings.app_port == 8501


def test_dotenv_does_not_override_shell(tmp_path: Path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("DC_COLLECTION=from-file\nDC_USER_ID=bob\n")
    monkeypatch.setenv("DC_COLLECTION", "from-shell")
    settings = Settings.from_env(env)
    assert settings.collection == "from-shell"
    assert settings.user_id == "bob"


@pytest.mark.parametrize(
    ("name", "value"),
    [("APP_PORT", "5000"), ("APP_PORT", "80"), ("APP_PORT", "abc"), ("DC_ENABLE_VECTORS", "maybe")],
)
def test_invalid_values_fail_loudly(monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(ValueError):
        Settings.from_env(env_file=None)


def test_api_key_hidden_from_repr():
    assert "s3cret" not in repr(LLMSettings(base_url="http://localhost:1", api_key="s3cret"))
