"""
Async Database Layer
======================
SQLAlchemy async engine for PostgreSQL (with asyncpg driver).
Used by the KIS data sync worker and the fast screener API.

Falls back to sync engine on SQLite for local dev / tests.
"""

import logging
import os
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import declarative_base

logger = logging.getLogger(__name__)

# ─── Config ──────────────────────────────────────────────────────────────────

DEFAULT_DB_URL = "postgresql+asyncpg://ficc_user:ficc_pw@postgres:5432/ficc_risk"
DATABASE_URL_ASYNC = os.getenv("DATABASE_URL_ASYNC", DEFAULT_DB_URL)

# Normalize sync-style URLs to async drivers
if DATABASE_URL_ASYNC.startswith("postgresql://"):
    DATABASE_URL_ASYNC = DATABASE_URL_ASYNC.replace(
        "postgresql://", "postgresql+asyncpg://", 1,
    )
elif DATABASE_URL_ASYNC.startswith("sqlite:///"):
    DATABASE_URL_ASYNC = DATABASE_URL_ASYNC.replace(
        "sqlite:///", "sqlite+aiosqlite:///", 1,
    )

# Declarative base shared with ORM models
AsyncBase = declarative_base()

# Engine — pool config varies by dialect (SQLite doesn't accept pool_size)
try:
    if "sqlite" in DATABASE_URL_ASYNC:
        _engine = create_async_engine(
            DATABASE_URL_ASYNC, echo=False, pool_pre_ping=True,
        )
    else:
        _engine = create_async_engine(
            DATABASE_URL_ASYNC,
            echo=False,
            pool_size=5,
            max_overflow=5,
            pool_pre_ping=True,
            pool_recycle=1800,
        )
    _engine_available = True
except Exception as e:
    logger.warning(f"Async engine init failed: {e}")
    _engine = None
    _engine_available = False

AsyncSessionLocal = async_sessionmaker(
    _engine, expire_on_commit=False, class_=AsyncSession,
) if _engine else None


# ─── Session Context Managers ────────────────────────────────────────────────

@asynccontextmanager
async def async_session_scope():
    """Async session for writes — commits on success, rolls back on error."""
    if AsyncSessionLocal is None:
        raise RuntimeError("Async engine unavailable")
    session = AsyncSessionLocal()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def get_async_session() -> AsyncSession:
    """Dependency for FastAPI routes."""
    async with AsyncSessionLocal() as session:
        yield session


# ─── Bootstrap ───────────────────────────────────────────────────────────────

async def init_async_db():
    """Create all tables defined on AsyncBase.metadata."""
    if not _engine_available:
        return False
    async with _engine.begin() as conn:
        await conn.run_sync(AsyncBase.metadata.create_all)
    return True


def get_async_engine():
    return _engine
