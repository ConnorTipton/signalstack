import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from alembic import command
from alembic.config import Config
from app.core.config import settings


def _alembic_cfg(database_url: str) -> Config:
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", database_url)
    return cfg


def _test_database_url() -> str:
    explicit = settings.test_database_url or os.getenv("TEST_DATABASE_URL")
    if explicit:
        return explicit

    app_url = make_url(settings.database_url)
    database = app_url.database or "signalstack"
    if database.endswith("_test"):
        return app_url.render_as_string(hide_password=False)
    return app_url.set(database=f"{database}_test").render_as_string(hide_password=False)


def _database_name(database_url: str) -> str:
    return make_url(database_url).database or ""


def _ensure_test_database(database_url: str) -> None:
    test_url = make_url(database_url)
    app_url = make_url(settings.database_url)
    if test_url.database == app_url.database:
        pytest.skip("Refusing to run integration tests against the application database")

    admin_db = os.getenv("POSTGRES_MAINTENANCE_DB", "postgres")
    admin_url = test_url.set(database=admin_db)
    admin_engine = create_engine(
        admin_url.render_as_string(hide_password=False),
        isolation_level="AUTOCOMMIT",
    )
    db_name = _database_name(database_url)
    escaped = db_name.replace('"', '""')
    try:
        with admin_engine.connect() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": db_name},
            ).scalar()
            if not exists:
                conn.execute(text(f'CREATE DATABASE "{escaped}"'))
    except Exception:
        pytest.skip("Test database unavailable and could not be created")
    finally:
        admin_engine.dispose()


@pytest.fixture(scope="session")
def db_engine():
    """Apply migrations to an isolated test DB; tear down that schema only."""
    database_url = _test_database_url()
    _ensure_test_database(database_url)
    engine = create_engine(database_url)
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:
        pytest.skip("Database not available — skipping integration tests")

    cfg = _alembic_cfg(database_url)
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    yield engine
    command.downgrade(cfg, "base")
    engine.dispose()


@pytest.fixture()
def db_session(db_engine):
    """Provide a transactional session that rolls back after each test."""
    connection = db_engine.connect()
    transaction = connection.begin()
    session_factory = sessionmaker(bind=connection)
    session = session_factory()

    yield session

    session.close()
    transaction.rollback()
    connection.close()
