"""Test detail + execution routes.

GET    /api/tests/{test_id}                             — a single generated test case
POST   /api/tests/{test_id}/execute                      — run the test against an environment
                                                            (synchronous, no AI — see
                                                            app/services/execution_service.py)
POST   /api/tests/{test_id}/validations                  — add a validation
DELETE /api/tests/{test_id}/validations/{validation_id}  — remove a validation
PUT    /api/tests/{test_id}/body                          — replace the request body

The validations/body routes and the chat agent's add_validation/
remove_validation/update_test_body tools (app/ai/tools/chat_tools.py) both
call app.services.test_service directly — same write path either way, no
shortcut.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_workspace_id, get_db
from app.schemas.api import AddValidationIn, ExecuteTestIn, ExecutionOut, TestOut, UpdateTestBodyIn
from app.services import EnvironmentNotFoundError, TestNotFoundError, ValidationNotFoundError
from app.services import execution_service, test_service

router = APIRouter()


@router.get(
    "/tests/{test_id}",
    response_model=TestOut,
    summary="Get a single test",
)
async def get_test(
    test_id: UUID,
    workspace_id: UUID = Depends(get_current_workspace_id),
    db: AsyncSession = Depends(get_db),
) -> TestOut:
    """Return a single test by ID.

    Raises HTTP 404 if the test does not exist or belongs to a different
    workspace.
    """
    try:
        test = await test_service.get_test(
            db=db,
            test_id=test_id,
            workspace_id=workspace_id,
        )
    except TestNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Test not found") from exc

    return TestOut.model_validate(test)


@router.post(
    "/tests/{test_id}/execute",
    response_model=ExecutionOut,
    status_code=201,
    summary="Execute a test against an environment",
)
async def execute_test(
    test_id: UUID,
    payload: ExecuteTestIn,
    workspace_id: UUID = Depends(get_current_workspace_id),
    db: AsyncSession = Depends(get_db),
) -> ExecutionOut:
    """Make a real HTTP call for *test_id* against *payload.environment_id*
    and check the response against its validations. Deterministic — no AI
    is involved. Runs synchronously (bounded by the engine's 30s HTTP
    timeout) and returns the persisted Execution + its result.
    """
    try:
        execution = await execution_service.execute_test(
            db=db,
            test_id=test_id,
            environment_id=payload.environment_id,
            workspace_id=workspace_id,
        )
    except TestNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Test not found") from exc
    except EnvironmentNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Environment not found") from exc

    return ExecutionOut.model_validate(execution)


@router.post(
    "/tests/{test_id}/validations",
    response_model=TestOut,
    status_code=201,
    summary="Add a validation to a test",
)
async def add_validation(
    test_id: UUID,
    payload: AddValidationIn,
    workspace_id: UUID = Depends(get_current_workspace_id),
    db: AsyncSession = Depends(get_db),
) -> TestOut:
    try:
        test = await test_service.add_validation(
            db=db,
            test_id=test_id,
            workspace_id=workspace_id,
            validation=payload.validation,
        )
    except TestNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Test not found") from exc
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid validation: {exc}") from exc

    return TestOut.model_validate(test)


@router.delete(
    "/tests/{test_id}/validations/{validation_id}",
    response_model=TestOut,
    summary="Remove a validation from a test",
)
async def remove_validation(
    test_id: UUID,
    validation_id: str,
    workspace_id: UUID = Depends(get_current_workspace_id),
    db: AsyncSession = Depends(get_db),
) -> TestOut:
    try:
        test = await test_service.remove_validation(
            db=db,
            test_id=test_id,
            workspace_id=workspace_id,
            validation_id=validation_id,
        )
    except TestNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Test not found") from exc
    except ValidationNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Validation not found") from exc

    return TestOut.model_validate(test)


@router.put(
    "/tests/{test_id}/body",
    response_model=TestOut,
    summary="Replace a test's request body",
)
async def update_test_body(
    test_id: UUID,
    payload: UpdateTestBodyIn,
    workspace_id: UUID = Depends(get_current_workspace_id),
    db: AsyncSession = Depends(get_db),
) -> TestOut:
    try:
        test = await test_service.update_test_body(
            db=db,
            test_id=test_id,
            workspace_id=workspace_id,
            body=payload.body,
        )
    except TestNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Test not found") from exc

    return TestOut.model_validate(test)
