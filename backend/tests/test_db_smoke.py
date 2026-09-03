"""
Async DB smoke test — runs against in-memory SQLite (aiosqlite).

This test proves the async engine + Base setup works without requiring
a live Postgres instance.  Postgres integration tests come in a later sprint
once Docker Compose is running (Prompt 4+).
"""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base


@pytest.fixture
async def sqlite_engine():
    """Create a fresh in-memory async SQLite engine for each test.

    We do NOT call ``Base.metadata.create_all`` here: the Endpoint model uses
    a PostgreSQL-specific JSONB column that SQLite's DDL compiler cannot
    render.  The only test that uses this fixture (``test_db_select_one``)
    just runs ``SELECT 1`` and does not need any tables.
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    yield engine
    await engine.dispose()


@pytest.fixture
async def db_session(sqlite_engine):
    """Yield an AsyncSession bound to the in-memory SQLite engine."""
    factory = async_sessionmaker(
        bind=sqlite_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    async with factory() as session:
        yield session


async def test_db_select_one(db_session: AsyncSession):
    """Trivial query — proves the async session pipeline works end-to-end."""
    result = await db_session.execute(text("SELECT 1"))
    value = result.scalar_one()
    assert value == 1


async def test_base_metadata_has_sprint1_tables():
    """Base.metadata must contain all 5 Sprint 1 tables once models are imported."""
    # Import triggers model registration on Base.metadata
    import app.models  # noqa: F401

    expected = {"workspaces", "users", "specs", "suites", "endpoints"}
    assert expected.issubset(Base.metadata.tables.keys()), (
        f"Missing tables: {expected - set(Base.metadata.tables.keys())}"
    )
