from collections.abc import Generator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session


def database_engine(url: str):
    return create_engine(
        make_url(url).set(drivername="postgresql+psycopg"),
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
        connect_args={"connect_timeout": 10},
        hide_parameters=True,
    )


def get_db(request: Request) -> Generator[Session, None, None]:
    with Session(request.app.state.database_engine) as session:
        yield session


DatabaseDep = Annotated[Session, Depends(get_db)]
