"""Environment CRUD endpoints.

POST   /api/environments       — create
GET    /api/environments       — list (current workspace)
GET    /api/environments/{id}  — get one
PATCH  /api/environments/{id}  — partial update
DELETE /api/environments/{id}  — delete
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_workspace_id, get_db
from app.schemas.api import EnvironmentIn, EnvironmentOut, EnvironmentUpdateIn
from app.services import EnvironmentNotFoundError, environment_service

router = APIRouter()


@router.post(
    "/environments",
    response_model=EnvironmentOut,
    status_code=201,
    summary="Create an environment",
)
async def create_environment(
    payload: EnvironmentIn,
    workspace_id: UUID = Depends(get_current_workspace_id),
    db: AsyncSession = Depends(get_db),
) -> EnvironmentOut:
    environment = await environment_service.create_environment(
        db=db,
        workspace_id=workspace_id,
        name=payload.name,
        base_url=str(payload.base_url),
        auth_type=payload.auth_type,
        auth_config=payload.auth_config,
        default_headers=payload.default_headers,
        variables=payload.variables,
    )
    return EnvironmentOut.model_validate(environment)


@router.get(
    "/environments",
    response_model=list[EnvironmentOut],
    summary="List environments in the current workspace",
)
async def list_environments(
    workspace_id: UUID = Depends(get_current_workspace_id),
    db: AsyncSession = Depends(get_db),
) -> list[EnvironmentOut]:
    environments = await environment_service.list_environments(db, workspace_id)
    return [EnvironmentOut.model_validate(e) for e in environments]


@router.get(
    "/environments/{environment_id}",
    response_model=EnvironmentOut,
    summary="Get a single environment",
)
async def get_environment(
    environment_id: UUID,
    workspace_id: UUID = Depends(get_current_workspace_id),
    db: AsyncSession = Depends(get_db),
) -> EnvironmentOut:
    try:
        environment = await environment_service.get_environment(
            db, environment_id, workspace_id
        )
    except EnvironmentNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Environment not found") from exc
    return EnvironmentOut.model_validate(environment)


@router.patch(
    "/environments/{environment_id}",
    response_model=EnvironmentOut,
    summary="Update an environment",
)
async def update_environment(
    environment_id: UUID,
    payload: EnvironmentUpdateIn,
    workspace_id: UUID = Depends(get_current_workspace_id),
    db: AsyncSession = Depends(get_db),
) -> EnvironmentOut:
    updates = payload.model_dump(exclude_unset=True)
    if "base_url" in updates and updates["base_url"] is not None:
        updates["base_url"] = str(updates["base_url"])

    try:
        environment = await environment_service.update_environment(
            db, environment_id, workspace_id, **updates
        )
    except EnvironmentNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Environment not found") from exc
    return EnvironmentOut.model_validate(environment)


@router.delete(
    "/environments/{environment_id}",
    status_code=204,
    summary="Delete an environment",
)
async def delete_environment(
    environment_id: UUID,
    workspace_id: UUID = Depends(get_current_workspace_id),
    db: AsyncSession = Depends(get_db),
) -> None:
    try:
        await environment_service.delete_environment(db, environment_id, workspace_id)
    except EnvironmentNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Environment not found") from exc
