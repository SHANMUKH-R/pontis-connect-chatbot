from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from pontis_chat.appconfig import AppConfig
from pontis_chat.dependency_injectors import initialize_app_config
from pontis_chat.routes.chat import router as chat_router
from pontis_chat.routes.site import router as site_router
from pontis_chat.routes.test_app import router as test_app_router


def create_app(config: AppConfig | None = None, *, env_file: str | Path = ".env") -> FastAPI:
    """Build an app, deferring environment loading until startup."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        initialize_app_config(app, config, env_file=env_file)
        # Initialize shared resources here using app.state.app_config.
        try:
            yield
        finally:
            # Close shared resources here before removing the settings.
            del app.state.app_config

    application = FastAPI(title="Vantage Point", version="0.1.0", lifespan=lifespan)
    application.include_router(test_app_router)
    application.include_router(chat_router)
    application.include_router(site_router)
    return application


app = create_app()