"""Endpoint-scoped test routes.

POST /api/endpoints/{endpoint_id}/generate-tests — generate tests via AI
GET  /api/endpoints/{endpoint_id}/tests           — list tests already generated

Generation is synchronous (see app/services/test_service.py docstring) —
Redis/arq-backed async generation is deferred to Sprint 9. The request
blocks until the LLM responds; there is no job queue or polling here.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_workspace_id, get_db
from app.schemas.api import TestOut
from app.services import EndpointNotFoundError, TestGenerationError
from app.services import test_service

router = APIRouter()


@router.post(
    "/endpoints/{endpoint_id}/generate-tests",
    response_model=list[TestOut],
    status_code=201,
    summary="Generate AI test cases for an endpoint",
)
async def generate_tests(
    endpoint_id: UUID,
    workspace_id: UUID = Depends(get_current_workspace_id),
    db: AsyncSession = Depends(get_db),
) -> list[TestOut]:
    """Call the AI orchestration layer for *endpoint_id* and persist the result.

    This call is synchronous — it blocks until the LLM responds. Free-tier
    NIM has real connection/queue overhead, so this can take anywhere from
    ~25s to a minute or two. There is no background job queue in V1.
    """
    try:
        tests = await test_service.generate_tests_for_endpoint(
            db=db,
            endpoint_id=endpoint_id,
            workspace_id=workspace_id,
        )
    except EndpointNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Endpoint not found") from exc
    except TestGenerationError as exc:
        # detail is an object (not a plain string): `message` is the raw
        # provider error text (shown to the user as-is — see
        # app/services/test_service.py) and `reason` is kept alongside it
        # for internal classification/logging only. `reset_at`/`provider`
        # are only meaningful for reason == "quota_exhausted" (see
        # TestGenerationError).
        raise HTTPException(
            status_code=502,
            detail={
                "message": str(exc),
                "reason": exc.reason,
                "reset_at": exc.reset_at,
                "provider": exc.provider,
            },
        ) from exc

    return [TestOut.model_validate(t) for t in tests]


@router.get(
    "/endpoints/{endpoint_id}/tests",
    response_model=list[TestOut],
    summary="List tests generated for an endpoint",
)
async def list_tests(
    endpoint_id: UUID,
    workspace_id: UUID = Depends(get_current_workspace_id),
    db: AsyncSession = Depends(get_db),
) -> list[TestOut]:
    """Return all tests already generated for *endpoint_id*, newest first."""
    try:
        tests = await test_service.list_tests_for_endpoint(
            db=db,
            endpoint_id=endpoint_id,
            workspace_id=workspace_id,
        )
    except EndpointNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Endpoint not found") from exc

    return [TestOut.model_validate(t) for t in tests]
