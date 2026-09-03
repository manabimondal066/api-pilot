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

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import get_settings


def _split_sslmode(database_url: str) -> tuple[str, dict]:
    """Strip libpq-only query params (sslmode, channel_binding) from the URL
    and translate them into asyncpg-native connect_args.

    asyncpg's connect() only understands an `ssl` keyword, not the
    `sslmode`/`channel_binding` query params libpq-style connection strings
    (e.g. Neon's) use. SQLAlchemy's asyncpg dialect forwards every URL query
    param straight through to asyncpg.connect(), so leaving `sslmode` in the
    URL raises "unexpected keyword argument 'sslmode'". Local dev URLs have
    no query params and are returned unchanged.
    """
    url = make_url(database_url)
    query = dict(url.query)
    sslmode = query.pop("sslmode", None)
    query.pop("channel_binding", None)

    connect_args: dict = {}
    if sslmode and sslmode != "disable":
        connect_args["ssl"] = True

    if query != dict(url.query):
        url = url.set(query=query)
    return url.render_as_string(hide_password=False), connect_args


# ---------------------------------------------------------------------------
# Engine — created once, shared for the whole process lifetime
# ---------------------------------------------------------------------------

_settings = get_settings()
_database_url, _connect_args = _split_sslmode(_settings.database_url)

engine = create_async_engine(
    _database_url,
    echo=_settings.db_echo,
    pool_size=_settings.db_pool_size,
    max_overflow=_settings.db_max_overflow,
    pool_pre_ping=_settings.db_pool_pre_ping,
    connect_args=_connect_args,
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
