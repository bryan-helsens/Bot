"""Async database engine and session management.

Provides a single :class:`Database` facade that owns the SQLAlchemy async engine
and session factory, created from :class:`~quantbot.core.config.Settings`. It
exposes an async-context ``session()`` that commits on success and rolls back on
error, a ``transaction()`` alias, and ``create_all``/``health_check`` helpers.

The ORM ``Base`` lives here so models and the engine share one metadata object.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import text

from quantbot.core.config import Settings, get_settings
from quantbot.core.exceptions import DatabaseError
from quantbot.core.logging import get_logger

_log = get_logger(__name__)


class Base(DeclarativeBase):
    """Declarative base shared by all ORM models."""


class Database:
    """Owns the async engine and session factory for the application."""

    def __init__(self, settings: Settings | None = None, *, url: str | None = None) -> None:
        self._settings = settings or get_settings()
        self._url = url or self._settings.database.url
        self._engine: AsyncEngine | None = None
        self._sessionmaker: async_sessionmaker[AsyncSession] | None = None

    # ------------------------------------------------------------------ lifecycle

    def connect(self) -> None:
        """Create the engine and session factory (idempotent)."""
        if self._engine is not None:
            return
        engine_kwargs: dict[str, object] = {
            "echo": self._settings.database.echo,
            "future": True,
        }
        # SQLite (used in tests) uses a StaticPool and rejects pool sizing args.
        if not self._url.startswith("sqlite"):
            engine_kwargs.update(
                pool_pre_ping=True,
                pool_size=self._settings.database.pool_size,
                max_overflow=self._settings.database.max_overflow,
            )
        self._engine = create_async_engine(self._url, **engine_kwargs)
        self._sessionmaker = async_sessionmaker(
            self._engine, expire_on_commit=False, class_=AsyncSession
        )
        _log.info("database_connected", url=_redact_url(self._url))

    @property
    def engine(self) -> AsyncEngine:
        if self._engine is None:
            self.connect()
        assert self._engine is not None
        return self._engine

    async def dispose(self) -> None:
        """Dispose the engine and its connection pool."""
        if self._engine is not None:
            await self._engine.dispose()
            self._engine = None
            self._sessionmaker = None
            _log.info("database_disposed")

    # ------------------------------------------------------------------ sessions

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        """Yield a session, committing on success and rolling back on error."""
        if self._sessionmaker is None:
            self.connect()
        assert self._sessionmaker is not None
        session = self._sessionmaker()
        try:
            yield session
            await session.commit()
        except Exception as exc:
            await session.rollback()
            raise DatabaseError(f"Transaction failed: {exc}") from exc
        finally:
            await session.close()

    #: ``transaction`` reads better at call sites that mutate data.
    transaction = session

    # ------------------------------------------------------------------ schema

    async def create_all(self) -> None:
        """Create all tables (for tests / first-run; production uses Alembic)."""
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        _log.info("schema_created", tables=len(Base.metadata.tables))

    async def drop_all(self) -> None:
        """Drop all tables (tests only)."""
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)

    async def health_check(self) -> bool:
        """Return ``True`` if a trivial query succeeds."""
        try:
            async with self.session() as session:
                await session.execute(text("SELECT 1"))
            return True
        except Exception as exc:  # noqa: BLE001 - health check must not raise
            _log.warning("database_health_check_failed", error=str(exc))
            return False


def _redact_url(url: str) -> str:
    """Hide credentials in a DSN for logging."""
    if "@" not in url:
        return url
    scheme, _, rest = url.partition("://")
    _, _, host = rest.partition("@")
    return f"{scheme}://***@{host}"


__all__ = ["Base", "Database"]
