"""Ambiente Alembic di RT: usa l'engine passato da rt.db.engine (config.attributes) oppure
ne crea uno dall'URL. render_as_batch per poter alterare tabelle SQLite."""
from alembic import context

from rt.db.engine import create_db_engine
from rt.db.models import Base

config = context.config
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(url=config.get_main_option("sqlalchemy.url"), target_metadata=target_metadata,
                      literal_binds=True, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = config.attributes.get("engine")
    own = engine is None
    if own:
        engine = create_db_engine(config.get_main_option("sqlalchemy.url"))
    try:
        with engine.connect() as connection:
            context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True)
            with context.begin_transaction():
                context.run_migrations()
            connection.commit()
    finally:
        if own:
            engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
