"""Suite endpoints.

GET    /api/suites                               — list suites in the current workspace
GET    /api/suites/{suite_id}                    — get suite detail with endpoint list
POST   /api/suites/{suite_id}/detect-dependencies — run heuristic dependency detection
GET    /api/suites/{suite_id}/dependencies       — current dependency edges
POST   /api/suites/{suite_id}/dependencies       — manually add a dependency edge
DELETE /api/suites/{suite_id}/dependencies/{dependency_id} — remove a dependency edge
POST   /api/suites/{suite_id}/execute            — run every test in the suite, in
                                                     dependency order
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_workspace_id, get_db
from app.schemas.api import (
    DependencyIn,
    DependencyOut,
    ExecuteSuiteIn,
    ExecutionOut,
    SuiteDetailOut,
    SuiteSummaryOut,
)
from app.services import (
    DependencyCycleError,
    DependencyNotFoundError,
    EnvironmentNotFoundError,
    InvalidDependencyError,
    SuiteNotFoundError,
)
from app.services import dependency_service, suite_execution_service, suite_service

router = APIRouter()


@router.get(
    "/suites",
    response_model=list[SuiteSummaryOut],
    summary="List suites in the current workspace",
)
async def list_suites(
    workspace_id: UUID = Depends(get_current_workspace_id),
    db: AsyncSession = Depends(get_db),
) -> list[SuiteSummaryOut]:
    """Return all suites for the current workspace, newest first.

    Each item includes an ``endpoint_count`` — no endpoint list in this view.
    """
    suites = await suite_service.list_suites(db=db, workspace_id=workspace_id)
    return [SuiteSummaryOut.model_validate(s) for s in suites]


@router.get(
    "/suites/{suite_id}",
    response_model=SuiteDetailOut,
    summary="Get suite detail",
)
async def get_suite(
    suite_id: UUID,
    workspace_id: UUID = Depends(get_current_workspace_id),
    db: AsyncSession = Depends(get_db),
) -> SuiteDetailOut:
    """Return a single suite with its endpoint list.

    Each endpoint includes ``id``, ``method``, ``path``, ``name``, and
    ``description`` — the full ``schema`` blob is omitted (use
    GET /api/endpoints/{id} for that, Sprint 1d).

    Raises HTTP 404 if the suite does not exist or belongs to a different
    workspace.
    """
    try:
        suite = await suite_service.get_suite(
            db=db,
            suite_id=suite_id,
            workspace_id=workspace_id,
        )
    except SuiteNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Suite not found") from exc

    return SuiteDetailOut.model_validate(suite)


@router.post(
    "/suites/{suite_id}/detect-dependencies",
    response_model=list[DependencyOut],
    summary="Run heuristic dependency detection for a suite",
)
async def detect_dependencies(
    suite_id: UUID,
    workspace_id: UUID = Depends(get_current_workspace_id),
    db: AsyncSession = Depends(get_db),
) -> list[DependencyOut]:
    """Run the Stage 1 heuristic detector (no AI) over every test in the
    suite and persist the resulting dependency edges, replacing any
    previously auto-detected edges. 'user'-sourced overrides are left
    untouched (PRD §12.4).

    Raises HTTP 404 if the suite does not exist or belongs to a different
    workspace, and HTTP 409 if the detected edges form a cycle — nothing is
    persisted in that case.
    """
    try:
        dependencies = await dependency_service.detect_dependencies(
            db=db,
            suite_id=suite_id,
            workspace_id=workspace_id,
        )
    except SuiteNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Suite not found") from exc
    except DependencyCycleError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return [DependencyOut.model_validate(d) for d in dependencies]


@router.get(
    "/suites/{suite_id}/dependencies",
    response_model=list[DependencyOut],
    summary="Get current dependency edges for a suite",
)
async def get_dependencies(
    suite_id: UUID,
    workspace_id: UUID = Depends(get_current_workspace_id),
    db: AsyncSession = Depends(get_db),
) -> list[DependencyOut]:
    """Return all dependency edges (any source) for tests in the suite.

    Raises HTTP 404 if the suite does not exist or belongs to a different
    workspace.
    """
    try:
        dependencies = await dependency_service.list_dependencies(
            db=db,
            suite_id=suite_id,
            workspace_id=workspace_id,
        )
    except SuiteNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Suite not found") from exc

    return [DependencyOut.model_validate(d) for d in dependencies]


@router.post(
    "/suites/{suite_id}/dependencies",
    response_model=DependencyOut,
    status_code=201,
    summary="Manually add a dependency edge",
)
async def add_dependency(
    suite_id: UUID,
    payload: DependencyIn,
    workspace_id: UUID = Depends(get_current_workspace_id),
    db: AsyncSession = Depends(get_db),
) -> DependencyOut:
    """Manually add a 'user'-sourced edge: *payload.test_id* depends on
    *payload.depends_on_test_id* (PRD §12.4). Persists independently of
    detect-dependencies, which never touches 'user'-sourced edges.

    Raises HTTP 404 if the suite does not exist, HTTP 400 if the edge is
    invalid (self-loop, a test outside the suite, or a duplicate), and
    HTTP 409 if it would introduce a dependency cycle.
    """
    try:
        dependency = await dependency_service.add_dependency(
            db=db,
            suite_id=suite_id,
            workspace_id=workspace_id,
            test_id=payload.test_id,
            depends_on_test_id=payload.depends_on_test_id,
        )
    except SuiteNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Suite not found") from exc
    except InvalidDependencyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except DependencyCycleError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return DependencyOut.model_validate(dependency)


@router.delete(
    "/suites/{suite_id}/dependencies/{dependency_id}",
    status_code=204,
    summary="Remove a dependency edge",
)
async def remove_dependency(
    suite_id: UUID,
    dependency_id: UUID,
    workspace_id: UUID = Depends(get_current_workspace_id),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete one dependency edge, regardless of its source.

    Raises HTTP 404 if the suite or the dependency edge does not exist.
    """
    try:
        await dependency_service.remove_dependency(
            db=db,
            suite_id=suite_id,
            workspace_id=workspace_id,
            dependency_id=dependency_id,
        )
    except SuiteNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Suite not found") from exc
    except DependencyNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Dependency not found") from exc


@router.post(
    "/suites/{suite_id}/execute",
    response_model=list[ExecutionOut],
    status_code=201,
    summary="Execute every test in a suite, in dependency order",
)
async def execute_suite(
    suite_id: UUID,
    payload: ExecuteSuiteIn,
    workspace_id: UUID = Depends(get_current_workspace_id),
    db: AsyncSession = Depends(get_db),
) -> list[ExecutionOut]:
    """Run every test in the suite against *payload.environment_id*,
    dependencies first (app/services/suite_execution_service.py). Values
    extracted from a passed (or inconclusive — see Fix B in
    app/services/validation_enforcement.py) test's response are available
    to downstream tests' `{{variable}}` references. A test whose dependency
    failed, errored, or was itself skipped is recorded as status='skipped'
    rather than executed. Deterministic — no AI is involved. Runs synchronously,
    one test at a time (no queue in V1), and returns the persisted
    Execution + result for every test in the suite.

    Raises HTTP 404 if the suite or environment does not exist (or belongs
    to a different workspace), and HTTP 409 if the suite's dependency edges
    contain a cycle — the specific tests involved are named in the error
    message, and nothing is executed in that case (no partial run).
    """
    try:
        executions = await suite_execution_service.execute_suite(
            db=db,
            suite_id=suite_id,
            environment_id=payload.environment_id,
            workspace_id=workspace_id,
        )
    except SuiteNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Suite not found") from exc
    except EnvironmentNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Environment not found") from exc
    except DependencyCycleError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return [ExecutionOut.model_validate(e) for e in executions]
