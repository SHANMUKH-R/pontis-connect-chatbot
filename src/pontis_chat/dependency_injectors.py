from pathlib import Path
from typing import Annotated, cast

from fastapi import Depends, FastAPI

from pontis_chat.appconfig import AppConfig, get_app_config

AppConfigDep = Annotated[AppConfig, Depends(get_app_config)]


def initialize_app_config(
    app: FastAPI, config: AppConfig | None = None, *, env_file: str | Path = ".env"
) -> AppConfig:
    """Validate configuration before serving requests and retain it on app state."""
    app.state.app_config = config if config is not None else AppConfig(_env_file=env_file)
    return cast(AppConfig, app.state.app_config)