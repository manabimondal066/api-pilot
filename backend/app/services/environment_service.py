"""Environment CRUD service.

Public functions
----------------
create_environment(db, workspace_id, ...) -> Environment
list_environments(db, workspace_id) -> list[Environment]
get_environment(db, environment_id, workspace_id) -> Environment
update_environment(db, environment_id, workspace_id, ...) -> Environment
delete_environment(db, environment_id, workspace_id) -> None
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.environment import Environment
from app.services import EnvironmentNotFoundError

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _load_environment(
    db: AsyncSession, environment_id: UUID, workspace_id: UUID
) -> Environment:
    result = await db.execute(
        select(Environment).where(
            Environment.id == environment_id,
            Environment.workspace_id == workspace_id,
        )
    )
    environment = result.scalar_one_or_none()
    if environment is None:
        raise EnvironmentNotFoundError(
            f"Environment {environment_id} not found in workspace {workspace_id}"
        )
    return environment


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def create_environment(
    db: AsyncSession,
    workspace_id: UUID,
    name: str,
    base_url: str,
    auth_type: str = "none",
    auth_config: dict[str, Any] | None = None,
    default_headers: dict[str, str] | None = None,
    variables: dict[str, Any] | None = None,
) -> Environment:
    environment = Environment(
        workspace_id=workspace_id,
        name=name,
        base_url=base_url,
        auth_type=auth_type,
        auth_config=auth_config or {},
        default_headers=default_headers or {},
        variables=variables or {},
    )
    db.add(environment)
    await db.commit()
    await db.refresh(environment)
    return environment


async def list_environments(db: AsyncSession, workspace_id: UUID) -> list[Environment]:
    result = await db.execute(
        select(Environment)
        .where(Environment.workspace_id == workspace_id)
        .order_by(Environment.created_at.desc())
    )
    return list(result.scalars().all())


async def get_environment(
    db: AsyncSession, environment_id: UUID, workspace_id: UUID
) -> Environment:
    """Raises EnvironmentNotFoundError if no matching environment exists."""
    return await _load_environment(db, environment_id, workspace_id)


async def update_environment(
    db: AsyncSession,
    environment_id: UUID,
    workspace_id: UUID,
    **updates: Any,
) -> Environment:
    """Apply the given (already-validated) field updates and persist.

    Raises EnvironmentNotFoundError if no matching environment exists.
    """
    environment = await _load_environment(db, environment_id, workspace_id)
    for field, value in updates.items():
        if value is not None:
            setattr(environment, field, value)
    await db.commit()
    await db.refresh(environment)
    return environment


async def delete_environment(
    db: AsyncSession, environment_id: UUID, workspace_id: UUID
) -> None:
    """Raises EnvironmentNotFoundError if no matching environment exists."""
    environment = await _load_environment(db, environment_id, workspace_id)
    await db.delete(environment)
    await db.commit()


async def find_or_create_from_curl(
    db: AsyncSession,
    workspace_id: UUID,
    name: str,
    base_url: str,
    auth_type: str = "none",
    auth_config: dict[str, Any] | None = None,
    default_headers: dict[str, str] | None = None,
) -> tuple[Environment, bool]:
    """Reuse a workspace environment with a matching base_url, or create one.

    Used by the cURL import flow (app/services/import_service.py) so
    re-importing against the same API doesn't create a duplicate environment
    every time. Does NOT commit — the caller (import_service) owns the
    transaction and commits once, alongside the Suite/Endpoint rows.

    Returns (environment, created) where created is False when an existing
    environment was reused.
    """
    result = await db.execute(
        select(Environment).where(
            Environment.workspace_id == workspace_id,
            Environment.base_url == base_url,
        )
    )
    existing = result.scalar_one_or_none()
    if existing is not None:
        return existing, False

    environment = Environment(
        workspace_id=workspace_id,
        name=name,
        base_url=base_url,
        auth_type=auth_type,
        auth_config=auth_config or {},
        default_headers=default_headers or {},
        variables={},
    )
    db.add(environment)
    await db.flush()  # assign environment.id without committing
    return environment, True
