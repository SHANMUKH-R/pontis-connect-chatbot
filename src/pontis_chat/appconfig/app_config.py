from typing import Any, cast

from fastapi import Request
from pydantic import Field, PostgresDsn
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
        hide_input_in_errors=True,
    )

    app_name: str = Field(default="Vantage Point", min_length=1)
    database_url: PostgresDsn = Field(repr=False)
    guardrails: bool = True
    health_status: str = Field(default="Ok", min_length=1)

    def __init__(self, **values: Any) -> None:
        """Allow required fields to come from BaseSettings' environment sources."""
        # An explicit constructor keeps type checkers from requiring env-backed
        # fields as arguments. BaseSettings still validates every field at runtime.
        super().__init__(**values)


def get_app_config(request: Request) -> AppConfig:
    """Return the configuration validated during this app's startup."""
    return cast(AppConfig, request.app.state.app_config)