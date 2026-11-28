import os
from collections.abc import AsyncGenerator, Sequence
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from pontis_chat.appconfig import AppConfig
from pontis_chat.dependency_injectors import initialize_app_config
from pontis_chat.routes.chat import router as chat_router
from pontis_chat.routes.site import router as site_router
from pontis_chat.routes.test_app import router as test_app_router


def create_app(
    config: AppConfig | None = None, *, env_file: str | Path = ".env", cors_origins: Sequence[str] = ()
) -> FastAPI:
    """Build an app, deferring environment loading until startup.

    ``cors_origins`` lists the origins of pages hosted elsewhere (for example a GitHub Pages site)
    that may call the API from a browser. The page the backend serves itself needs no entry.
    """

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
    if cors_origins:
        application.add_middleware(
            CORSMiddleware, allow_origins=list(cors_origins), allow_methods=["POST"], allow_headers=["Content-Type"]
        )
    application.include_router(test_app_router)
    application.include_router(chat_router)
    application.include_router(site_router)
    return application


# Middleware must be registered before startup, so this one value is read from the process
# environment at import. Everything else is still loaded at startup.
app = create_app(
    cors_origins=[origin.strip() for origin in os.environ.get("CORS_ALLOWED_ORIGINS", "").split(",") if origin.strip()]
)