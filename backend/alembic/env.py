from alembic import context
from app.core.config import get_settings
from app.db.session import build_engine
from app.models import Base

if context.is_offline_mode():
    context.configure(url=get_settings().database_url, target_metadata=Base.metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    with build_engine(get_settings().database_url).connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
