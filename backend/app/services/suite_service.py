"""Suite service — query layer for suite read operations.

Functions
---------
list_suites(db, workspace_id)  → list[Suite]
    All suites for a workspace, ordered newest-first, with endpoint_count set.

get_suite(db, suite_id, workspace_id)  → Suite
    Single suite with endpoints loaded; raises SuiteNotFoundError if absent.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.endpoint import Endpoint
from app.models.suite import Suite
from app.services import SuiteNotFoundError


async def list_suites(db: AsyncSession, workspace_id: UUID) -> list[Suite]:
    """Return all suites for *workspace_id*, ordered by ``created_at`` DESC.

    Each returned :class:`~app.models.suite.Suite` has an ``endpoint_count``
    attribute set as a plain Python int (not a mapped column) so that
    :class:`~app.schemas.api.SuiteSummaryOut` can read it with
    ``from_attributes=True``.
    """
    stmt = (
        select(Suite, func.count(Endpoint.id).label("endpoint_count"))
        .outerjoin(Endpoint, Endpoint.suite_id == Suite.id)
        .where(Suite.workspace_id == workspace_id)
        .group_by(Suite.id)
        .order_by(Suite.created_at.desc())
    )
    rows = (await db.execute(stmt)).all()
    for suite, count in rows:
        suite.endpoint_count = count  # dynamic Python attribute
    return [suite for suite, _ in rows]


async def get_suite(
    db: AsyncSession,
    suite_id: UUID,
    workspace_id: UUID,
) -> Suite:
    """Return the suite identified by *suite_id* with its endpoints loaded.

    Filters by *workspace_id* for tenant isolation (even in V1 single-tenant
    mode this guard prevents accidental cross-workspace data leaks).

    Raises:
        SuiteNotFoundError: if no matching suite exists in the workspace.
    """
    result = await db.execute(
        select(Suite)
        .where(Suite.id == suite_id, Suite.workspace_id == workspace_id)
        .options(selectinload(Suite.endpoints))
    )
    suite = result.scalar_one_or_none()
    if suite is None:
        raise SuiteNotFoundError(f"Suite {suite_id} not found in workspace {workspace_id}")
    return suite
