"""Async SQLAlchemy engine and session lifecycle."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from myagent.config import Settings

AsyncSessionFactory = async_sessionmaker[AsyncSession]


def create_database_engine(settings: Settings) -> AsyncEngine:
    """Create a dialect-aware async engine without logging credentials."""

    database_url = settings.database_url.get_secret_value()
    common_options = {
        "echo": settings.database_echo,
        "pool_pre_ping": True,
    }
    if database_url.startswith("sqlite+"):
        return create_async_engine(database_url, **common_options)
    return create_async_engine(
        database_url,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
        **common_options,
    )


def create_session_factory(engine: AsyncEngine) -> AsyncSessionFactory:
    """Create sessions that keep ORM values available after commit."""

    return async_sessionmaker(engine, expire_on_commit=False)


@dataclass(slots=True)
class Database:
    """Own the database engine and its session factory."""

    engine: AsyncEngine
    session_factory: AsyncSessionFactory

    @classmethod
    def from_settings(cls, settings: Settings) -> Database:
        engine = create_database_engine(settings)
        return cls(engine=engine, session_factory=create_session_factory(engine))

    async def close(self) -> None:
        await self.engine.dispose()
