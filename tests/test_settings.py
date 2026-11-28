import pytest
from pydantic import ValidationError

from pontis_chat.appconfig import AppConfig


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    for name in ("APP_NAME", "DATABASE_URL", "GUARDRAILS", "HEALTH_STATUS"):
        monkeypatch.delenv(name, raising=False)


@pytest.mark.parametrize("guardrails", [True, False])
def test_dotenv_loading_and_environment_precedence(tmp_path, monkeypatch, guardrails):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "APP_NAME=From file\n"
        "DATABASE_URL=postgresql://vp:vp@localhost:5432/vp\n"
        f"GUARDRAILS={str(guardrails).lower()}\n"
        "UNRELATED=value\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("APP_NAME", "From environment")

    settings = AppConfig(_env_file=env_file)

    assert settings.app_name == "From environment"
    assert settings.guardrails is guardrails
    assert str(settings.database_url) == "postgresql://vp:vp@localhost:5432/vp"
    assert AppConfig(_env_file=env_file, app_name="Explicit").app_name == "Explicit"


def test_database_url_is_required():
    with pytest.raises(ValidationError, match="database_url"):
        AppConfig(_env_file=None)


@pytest.mark.parametrize(
    "values",
    [{"database_url": "invalid"}, {"guardrails": "invalid"}, {"app_name": ""}],
)
def test_invalid_settings_are_rejected(values):
    config = {"database_url": "postgresql://vp:vp@localhost:5432/vp", **values}
    with pytest.raises(ValidationError):
        AppConfig(_env_file=None, **config)