import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from main import create_app
from pontis_chat.appconfig import AppConfig
from pontis_chat.dependency_injectors import AppConfigDep


def test_startup_loads_settings_and_routes_can_access_them(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("HEALTH_STATUS", raising=False)
    env_file = tmp_path / ".env"
    app = create_app(env_file=env_file)
    assert not hasattr(app.state, "app_config")
    # Create the file after app construction to verify deferred loading.
    env_file.write_text(
        "DATABASE_URL=postgresql://vp:vp@localhost:5432/vp\nHEALTH_STATUS=Configured health\n"
    )

    @app.get("/test-settings")
    def read_settings(settings: AppConfigDep):
        assert settings is app.state.app_config
        return {"app_name": settings.app_name}

    with TestClient(app) as client:
        assert client.get("/health").json() == {"status": "Configured health"}
        response = client.get("/test-settings")
        assert response.status_code == 200
        assert response.json() == {"app_name": app.state.app_config.app_name}
        assert client.get("/openapi.json").status_code == 200

    assert not hasattr(app.state, "app_config")


def test_invalid_configuration_prevents_startup(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "invalid")
    app = create_app(env_file=tmp_path / "missing.env")
    with pytest.raises(ValidationError), TestClient(app):
        pass


def test_apps_have_independent_settings():
    first = AppConfig(
        _env_file=None,
        database_url="postgresql://vp:vp@localhost/vp",
        app_name="A",
        health_status="Ok",
    )
    second = AppConfig(
        _env_file=None,
        database_url="postgresql://vp:vp@localhost/vp",
        app_name="B",
        health_status="Second app",
    )
    with TestClient(create_app(first)) as a, TestClient(create_app(second)) as b:
        assert a.app.state.app_config is first
        assert b.app.state.app_config is second
        assert a.get("/health").json() == {"status": "Ok"}
        assert b.get("/health").json() == {"status": "Second app"}