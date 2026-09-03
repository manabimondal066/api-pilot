"""
Integration test — requires local PostgreSQL running with api_pilot database.
Skips gracefully if the DB is not reachable.

These tests connect to the REAL database (postgresql+asyncpg) and verify the
full async stack: engine → session → query → result.

Run with:
    pytest tests/test_db_integration.py -v
"""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.config import get_settings


@pytest.fixture
async def db_session():
    """Create a test session against the real local PostgreSQL database."""
    settings = get_settings()
    engine = create_async_engine(settings.database_url, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    try:
        async with async_session() as session:
            # Probe the connection before yielding — fail fast with a skip
            await session.execute(text("SELECT 1"))
            yield session
    except Exception as exc:
        pytest.skip(f"PostgreSQL not available: {exc}")
    finally:
        await engine.dispose()


async def test_postgres_connection(db_session: AsyncSession):
    """Verify we can connect to PostgreSQL and run a basic query."""
    result = await db_session.execute(text("SELECT 1 AS val"))
    row = result.one()
    assert row.val == 1


async def test_postgres_database_name(db_session: AsyncSession):
    """Verify we are connected to the correct database (api_pilot)."""
    result = await db_session.execute(text("SELECT current_database()"))
    db_name = result.scalar()
    assert db_name == "api_pilot"


async def test_postgres_user(db_session: AsyncSession):
    """Verify we are connected as the correct user (api_pilot)."""
    result = await db_session.execute(text("SELECT current_user"))
    user = result.scalar()
    assert user == "api_pilot"
