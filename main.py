"""Repository entry point; application setup lives in pontis_chat."""

from pontis_chat.application import app, create_app

__all__ = ["app", "create_app"]
