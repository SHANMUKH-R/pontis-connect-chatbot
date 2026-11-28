from alembic import context

from pontis_chat.appconfig import AppConfig
from pontis_chat.backend.database import database_engine


def run_migrations():
    engine = database_engine(str(AppConfig().database_url))
    try:
        with engine.connect() as connection:
            context.configure(connection=connection, target_metadata=None)
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


run_migrations()
