from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import settings


class Base(DeclarativeBase):
    pass


is_sqlite = settings.database_url.startswith("sqlite")

connect_args = (
    {"check_same_thread": False}
    if is_sqlite
    else {"sslmode": "require"}
)

engine = create_engine(
    settings.database_url,
    connect_args=connect_args,
    pool_pre_ping=not is_sqlite,
    pool_recycle=1800 if not is_sqlite else -1,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
