"""Shared pytest fixtures for the api-pilot backend test suite.

Fixtures defined here are available to all test modules without importing.
Module-level fixtures in individual test files take precedence over these
conftest fixtures (standard pytest override semantics).
"""

from __future__ import annotations

import os

# Force mock LLM provider BEFORE any app imports so the factory never tries
# to instantiate a real provider (and hit a real API) during tests.
os.environ.setdefault("LLM_PROVIDER", "mock")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-used")
os.environ.setdefault("NVIDIA_API_KEY", "test-key-not-used")
os.environ.setdefault("GROQ_API_KEY", "test-key-not-used")
os.environ.setdefault("OPENAI_API_KEY", "test-key-not-used")

from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.core.constants import DEFAULT_WORKSPACE_ID
from app.models.environment import Environment
from app.models.spec import Spec


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    """httpx AsyncClient wired to the FastAPI ASGI app (no real HTTP server).

    Use this in API-level tests instead of starting a real uvicorn process.
    """
    # Import here so the app module is only loaded when the fixture is used.
    from app.main import app as fastapi_app  # noqa: PLC0415

    async with AsyncClient(
        transport=ASGITransport(app=fastapi_app),
        base_url="http://test",
    ) as c:
        yield c


@pytest.fixture
async def db() -> AsyncGenerator[AsyncSession, None]:
    """AsyncSession connected to real PostgreSQL.  Skips if DB unavailable.

    **Teardown:** deletes all Spec rows for DEFAULT_WORKSPACE_ID; cascade
    removes suites and endpoints automatically.

    Note: test modules may define their own ``db`` fixture — that local
    definition takes precedence for tests within the same file.
    """
    settings = get_settings()
    engine = create_async_engine(settings.database_url, echo=False)
    factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
    try:
        async with factory() as session:
            try:
                await session.execute(text("SELECT 1"))
            except Exception as exc:  # noqa: BLE001
                pytest.skip(f"PostgreSQL not available: {exc}")
                return

            yield session

            # Teardown — rollback any incomplete transaction, then purge all
            # test-created Spec rows (cascade handles suites + endpoints;
            # suite.environment_id is ON DELETE SET NULL, so Environment
            # rows survive that cascade and must be deleted separately).
            try:
                await session.rollback()
            except Exception:  # noqa: BLE001
                pass
            try:
                await session.execute(
                    delete(Spec).where(Spec.workspace_id == DEFAULT_WORKSPACE_ID)
                )
                await session.execute(
                    delete(Environment).where(
                        Environment.workspace_id == DEFAULT_WORKSPACE_ID
                    )
                )
                await session.commit()
            except Exception:  # noqa: BLE001
                pass
    finally:
        await engine.dispose()


@pytest.fixture(scope="session", autouse=True)
def _reset_llm_cache():
    from app.ai.providers.factory import reset_provider_cache  # noqa: PLC0415
    reset_provider_cache()
    yield
    reset_provider_cache()
