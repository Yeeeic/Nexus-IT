"""Async minimum-privilege PostgreSQL engine construction."""

from sqlalchemy import URL
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from backend.app.core.config import DatabaseSettings


def create_database_engine(settings: DatabaseSettings) -> AsyncEngine:
    url = URL.create(
        drivername="postgresql+psycopg",
        username=settings.user,
        password=settings.password.get_secret_value(),
        host=settings.host,
        port=settings.port,
        database=settings.name,
    )
    return create_async_engine(
        url,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
        pool_timeout=10,
        hide_parameters=True,
    )
