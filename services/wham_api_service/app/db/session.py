from __future__ import annotations

from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.settings import settings
from app.db.models import Base


@lru_cache(maxsize=1)
def get_engine():
    if not settings.database_url:
        return None
    return create_engine(settings.database_url, pool_pre_ping=True, future=True)


@lru_cache(maxsize=1)
def get_session_factory():
    engine = get_engine()
    if engine is None:
        return None
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def init_db() -> None:
    engine = get_engine()
    if engine is None:
        return
    # Base.metadata.drop_all(bind=engine)  # Drop existing tables for a clean slate (use with caution!)
    Base.metadata.create_all(bind=engine)


@contextmanager
def session_scope() -> Session:
    factory = get_session_factory()
    if factory is None:
        raise RuntimeError("WHAM_DATABASE_URL is not configured")
    session: Session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()