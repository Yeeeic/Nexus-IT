from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import URL, create_engine, pool


config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = None


def _required_environment(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Required database setting is missing: {name}")
    return value


def _database_url() -> URL:
    return URL.create(
        drivername="postgresql+psycopg",
        username=_required_environment("NEXUS_POSTGRES_USER"),
        password=_required_environment("NEXUS_POSTGRES_PASSWORD"),
        host=os.getenv("NEXUS_POSTGRES_HOST", "postgres"),
        port=int(os.getenv("NEXUS_POSTGRES_PORT", "5432")),
        database=os.getenv("NEXUS_POSTGRES_DB", "nexus_it"),
    )


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_database_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
