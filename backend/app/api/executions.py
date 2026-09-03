"""Execution query routes.

GET /api/executions      — list executions in the current workspace
GET /api/executions/{id} — a single execution with its result(s)
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_workspace_id, get_db
from app.schemas.api import ExecutionOut
from app.services import ExecutionNotFoundError, execution_service

router = APIRouter()


@router.get(
    "/executions",
    response_model=list[ExecutionOut],
    summary="List executions in the current workspace",
)
async def list_executions(
    workspace_id: UUID = Depends(get_current_workspace_id),
    db: AsyncSession = Depends(get_db),
) -> list[ExecutionOut]:
    executions = await execution_service.list_executions(db, workspace_id)
    return [ExecutionOut.model_validate(e) for e in executions]


@router.get(
    "/executions/{execution_id}",
    response_model=ExecutionOut,
    summary="Get a single execution",
)
async def get_execution(
    execution_id: UUID,
    workspace_id: UUID = Depends(get_current_workspace_id),
    db: AsyncSession = Depends(get_db),
) -> ExecutionOut:
    try:
        execution = await execution_service.get_execution(db, execution_id, workspace_id)
    except ExecutionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Execution not found") from exc
    return ExecutionOut.model_validate(execution)
