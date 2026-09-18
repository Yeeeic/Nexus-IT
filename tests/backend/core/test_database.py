import asyncio

from backend.app.core.config import DatabaseSettings
from backend.app.core.database import create_database_engine


def test_database_engine_uses_async_psycopg_and_hides_parameters() -> None:
    secret = "runtime-only-password"
    settings = DatabaseSettings.from_environment(
        {
            "NEXUS_DATABASE_HOST": "postgres",
            "NEXUS_DATABASE_PORT": "5432",
            "NEXUS_DATABASE_NAME": "nexus_it",
            "NEXUS_DATABASE_USER": "nexus_runtime",
            "NEXUS_DATABASE_PASSWORD": secret,
        }
    )

    engine = create_database_engine(settings)

    assert engine.url.drivername == "postgresql+psycopg"
    assert engine.url.username == "nexus_runtime"
    assert engine.url.host == "postgres"
    assert engine.url.database == "nexus_it"
    assert engine.sync_engine.hide_parameters is True
    assert secret not in repr(engine)
    assert secret not in str(engine.url)

    asyncio.run(engine.dispose())
