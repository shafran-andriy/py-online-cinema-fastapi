from logging.config import fileConfig
import os
import sys

from sqlalchemy import engine_from_config, pool
from alembic import context

config = context.config
fileConfig(config.config_file_name)

# Ensure src/ is on the import path so all models are importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

# Import Base and all models so their metadata is populated for autogenerate
from database import Base  # noqa: E402
import database.models.accounts  # noqa: E402, F401
import database.models.movies    # noqa: E402, F401
import database.models.cart      # noqa: E402, F401
import database.models.orders    # noqa: E402, F401
import database.models.payments  # noqa: E402, F401

target_metadata = Base.metadata

# Allow overriding the DB URL from the environment.
# Strip +asyncpg so alembic can use psycopg2 (sync) for PostgreSQL migrations.
database_url = os.getenv("DATABASE_URL")
if database_url:
    database_url = database_url.replace("postgresql+asyncpg://", "postgresql+psycopg2://")
    config.set_main_option("sqlalchemy.url", database_url)


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
