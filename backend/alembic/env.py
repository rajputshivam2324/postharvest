from logging.config import fileConfig

from alembic import context
from app.core.config import Settings
from app.db import models  # noqa: F401
from app.db.base import Base
from app.db.session import build_engine

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)
settings = Settings()  # type: ignore[call-arg]
target_metadata = Base.metadata

if context.is_offline_mode():
    context.configure(
        url=settings.sqlalchemy_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()
else:

    def run_on_connection(connection):
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            version_table_schema=config.attributes.get("version_table_schema"),
        )
        with context.begin_transaction():
            context.run_migrations()

    provided_connection = config.attributes.get("connection")
    if provided_connection is not None:
        run_on_connection(provided_connection)
    else:
        engine = build_engine(settings)
        with engine.connect() as connection:
            run_on_connection(connection)
        engine.dispose()
