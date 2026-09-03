"""Execution persistence service.

Public functions
----------------
execute_test(db, test_id, environment_id, workspace_id) -> Execution
    Runs the deterministic execution engine (app/services/execution_engine.py)
    for one test against one environment, and persists an Execution +
    ExecutionResult row. Synchronous — see module docstring note below.

record_execution(db, test, environment, outcome) -> Execution
    Persists one ExecutionOutcome (from execution_engine.execute, or a
    synthetic 'skipped' outcome) as an Execution + ExecutionResult row.
    Does not commit — callers control the transaction boundary. Shared by
    execute_test and app/services/suite_execution_service.py so the two
    calling layers never duplicate this persistence logic.

get_execution(db, execution_id, workspace_id) -> Execution
list_executions(db, workspace_id) -> list[Execution]

Synchronous by design
----------------------
Like test generation (app/services/test_service.py), a single-test
execution runs on the request path and blocks until the HTTP call
completes (bounded by the engine's 30s timeout). There is no job queue in
V1 — Redis/arq-backed async execution is deferred (Implementation Plan
Module 12). Do not add a queue or polling endpoint for this.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.environment import Environment
from app.models.execution import Execution, ExecutionResult
from app.models.suite import Suite
from app.models.test import Test
from app.services import EnvironmentNotFoundError, ExecutionNotFoundError, TestNotFoundError
from app.services.execution_engine import ExecutionOutcome
from app.services.execution_engine import execute as run_execution

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _load_test(db: AsyncSession, test_id: UUID, workspace_id: UUID) -> Test:
    result = await db.execute(
        select(Test)
        .join(Suite, Test.suite_id == Suite.id)
        .where(Test.id == test_id, Suite.workspace_id == workspace_id)
    )
    test = result.scalar_one_or_none()
    if test is None:
        raise TestNotFoundError(f"Test {test_id} not found in workspace {workspace_id}")
    return test


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


def _set_display_names(execution: Execution) -> Execution:
    """Set test_name/environment_name as plain Python attributes (not
    mapped columns) so ExecutionOut can read them with from_attributes —
    same pattern as Suite.endpoint_count in suite_service. Requires
    execution.test and execution.environment to already be loaded
    (selectinload), since this runs outside an awaitable context.
    """
    execution.test_name = execution.test.name  # type: ignore[attr-defined]
    execution.environment_name = execution.environment.name  # type: ignore[attr-defined]
    return execution


async def _load_execution(
    db: AsyncSession, execution_id: UUID, workspace_id: UUID
) -> Execution:
    result = await db.execute(
        select(Execution)
        .join(Test, Execution.test_id == Test.id)
        .join(Suite, Test.suite_id == Suite.id)
        .options(
            selectinload(Execution.results),
            selectinload(Execution.test),
            selectinload(Execution.environment),
        )
        .where(Execution.id == execution_id, Suite.workspace_id == workspace_id)
    )
    execution = result.scalar_one_or_none()
    if execution is None:
        raise ExecutionNotFoundError(
            f"Execution {execution_id} not found in workspace {workspace_id}"
        )
    return _set_display_names(execution)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def record_execution(
    db: AsyncSession,
    test: Test,
    environment: Environment,
    outcome: ExecutionOutcome,
) -> Execution:
    """Persist *outcome* as an Execution + ExecutionResult row.

    Flushes but does not commit — the caller controls the transaction
    boundary (execute_test commits immediately; suite execution commits
    after each test so partial progress survives an unexpected error
    partway through the run).
    """
    execution = Execution(
        test_id=test.id,
        environment_id=environment.id,
        status="running",
    )
    db.add(execution)
    await db.flush()  # assign execution.id before building the result row

    result = ExecutionResult(
        execution_id=execution.id,
        test_id=test.id,
        status=outcome.status,
        request_snapshot=outcome.request_snapshot,
        response_snapshot=outcome.response_snapshot,
        validation_results=outcome.validation_results,
        duration_ms=outcome.duration_ms,
        error=outcome.error,
    )
    db.add(result)

    if outcome.status in ("error", "skipped"):
        execution.status = outcome.status
    else:
        execution.status = "completed"
    execution.finished_at = datetime.now(timezone.utc)

    return execution


async def execute_test(
    db: AsyncSession,
    test_id: UUID,
    environment_id: UUID,
    workspace_id: UUID,
) -> Execution:
    """Run *test_id* against *environment_id* and persist the outcome.

    Raises:
        TestNotFoundError: if the test doesn't exist in the workspace.
        EnvironmentNotFoundError: if the environment doesn't exist in the
            workspace.
    """
    test = await _load_test(db, test_id, workspace_id)
    environment = await _load_environment(db, environment_id, workspace_id)

    outcome = await run_execution(test, environment)
    execution = await record_execution(db, test, environment, outcome)

    await db.commit()
    return await _load_execution(db, execution.id, workspace_id)


async def get_execution(
    db: AsyncSession, execution_id: UUID, workspace_id: UUID
) -> Execution:
    """Raises ExecutionNotFoundError if no matching execution exists."""
    return await _load_execution(db, execution_id, workspace_id)


async def list_executions(db: AsyncSession, workspace_id: UUID) -> list[Execution]:
    """Return all executions in the workspace, newest first."""
    result = await db.execute(
        select(Execution)
        .join(Test, Execution.test_id == Test.id)
        .join(Suite, Test.suite_id == Suite.id)
        .options(
            selectinload(Execution.results),
            selectinload(Execution.test),
            selectinload(Execution.environment),
        )
        .where(Suite.workspace_id == workspace_id)
        .order_by(Execution.started_at.desc())
    )
    executions = list(result.scalars().unique().all())
    return [_set_display_names(e) for e in executions]
