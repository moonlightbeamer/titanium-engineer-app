"""SQLAlchemy declarative base and engine factory."""

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker


class Base(DeclarativeBase):
    pass


def get_engine(url: str | None = None):
    db_url = url or os.getenv(
        "DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/pr_reviewer"
    )
    return create_engine(db_url, pool_pre_ping=True)


def get_session_factory(url: str | None = None):
    engine = get_engine(url)
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)
