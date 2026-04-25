from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

# Import all models so their metadata is registered on Base.
import app.db.models  # noqa: F401, E402
from app.core.config import settings  # noqa: E402
from app.db.base import Base  # noqa: E402

_DEFAULT_INI_URL = "postgresql+psycopg://signalstack:signalstack@localhost:5432/signalstack"

# Use settings for normal app runs, but preserve an explicitly injected URL
# from test fixtures or one-off migration commands.
if config.get_main_option("sqlalchemy.url") == _DEFAULT_INI_URL:
    config.set_main_option("sqlalchemy.url", settings.database_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
