"""
Database engine and async session factory for api-pilot.

Usage in FastAPI route handlers:

    from app.db.session import get_db
    from sqlalchemy.ext.asyncio import AsyncSession

    @router.get("/example")
    async def example(db: AsyncSession = Depends(get_db)):
        result = await db.execute(select(MyModel))
        ...

The engine and sessionmaker are created once at module import time
and reused for the lifetime of the process.  Call `dispose_engine()`
during application shutdown (wired into the FastAPI lifespan handler
in main.py).
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import get_settings

# ---------------------------------------------------------------------------
# Engine — created once, shared for the whole process lifetime
# ---------------------------------------------------------------------------

_settings = get_settings()

engine = create_async_engine(
    _settings.database_url,
    echo=_settings.db_echo,
    pool_size=_settings.db_pool_size,
    max_overflow=_settings.db_max_overflow,
    pool_pre_ping=_settings.db_pool_pre_ping,
)

# ---------------------------------------------------------------------------
# Session factory
# ---------------------------------------------------------------------------

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,  # keep objects usable after commit without re-query
    autoflush=False,
    autocommit=False,
)

# Alias used by tests and CLI scripts (matches the name referenced in docs).
async_session_maker = AsyncSessionLocal


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async database session; always close it afterwards."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


# ---------------------------------------------------------------------------
# Shutdown helper
# ---------------------------------------------------------------------------


async def dispose_engine() -> None:
    """Dispose the connection pool — call during application shutdown."""
    await engine.dispose()
