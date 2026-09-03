"""Shared FastAPI dependencies.

All route handlers import from here instead of importing session factories or
constants directly, which keeps routers thin and swappable.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import DEFAULT_WORKSPACE_ID
from app.db.session import async_session_maker


async def get_db() -> AsyncIterator[AsyncSession]:
    """Yield a fresh :class:`AsyncSession` for each request.

    The session is closed (and any uncommitted transaction is rolled back)
    when the request context exits.
    """
    async with async_session_maker() as session:
        yield session


async def get_current_workspace_id() -> UUID:
    """V1 placeholder — always returns the seeded default workspace.

    Sprint 9 will replace this with a real JWT-based workspace lookup.
    """
    return DEFAULT_WORKSPACE_ID
