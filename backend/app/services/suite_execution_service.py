"""Suite-level execution service (PRD §12/§14, Implementation Plan Module 6,
Sprint 4). Extends the single-test execution engine
(app/services/execution_engine.py) to run every test in a suite in
dependency order, threading extracted values between tests.

Public functions
----------------
execute_suite(db, suite_id, environment_id, workspace_id) -> list[Execution]
    Runs every test in the suite against one environment, dependencies
    first, and returns one persisted Execution (with its ExecutionResult)
    per test — same row shape as a single-test execute_test call.

Ordering and skipping
----------------------
Tests are ordered via Kahn's algorithm over the suite's Dependency edges
(app/models/dependency.py): a test only runs once every test it depends on
has run. If a dependency fails validations ('failed'), errors ('error'),
or is itself skipped, every test that depends on it (directly or
transitively) is recorded as status='skipped' with
error="skipped (dependency failed)" — the request is never sent.

Cycle handling — reject up front, run nothing
-----------------------------------------------
detect_dependencies() rejects a cycle before persisting, but a manual
'user' edge (app/services/dependency_service.add_dependency) can still
introduce one — add_dependency itself also rejects a cycle at add time,
but two independently-valid edges can combine into a cycle no single add
call would have seen (should be rare, not impossible). Rather than
starting the run and silently skipping the tests caught in it (a
"generic failure" that just looks like a burned test), execute_suite
checks for a cycle across every test in the suite *before* running
anything, and raises DependencyCycleError naming the specific tests
involved — no Execution rows are created for a rejected run.

Variable propagation
---------------------
A shared `variables_context` dict accumulates every `Extraction` resolved
from a *passed* test's response (execution_engine.extract_variables).
Downstream tests' `{{variable}}` references resolve against this context
before falling back to the environment's own `variables` — see
execution_engine.build_request's `extra_variables` parameter. A 'failed'
test's extractions are discarded — "if a test fails, don't trust anything
it produced."

Synchronous by design — same "no queue yet" reasoning as execute_test
(app/services/execution_service.py). Do not add a queue or polling
endpoint here.
"""

from __future__ import annotations

from collections import deque
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.execution import Execution
from app.models.suite import Suite
from app.models.test import Test
from app.services import DependencyCycleError, SuiteNotFoundError
from app.services import dependency_service, environment_service, execution_service
from app.services.execution_engine import ExecutionOutcome
from app.services.execution_engine import execute as run_execution

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _load_suite(db: AsyncSession, suite_id: UUID, workspace_id: UUID) -> Suite:
    result = await db.execute(
        select(Suite).where(Suite.id == suite_id, Suite.workspace_id == workspace_id)
    )
    suite = result.scalar_one_or_none()
    if suite is None:
        raise SuiteNotFoundError(f"Suite {suite_id} not found in workspace {workspace_id}")
    return suite


async def _load_tests(db: AsyncSession, suite_id: UUID) -> list[Test]:
    result = await db.execute(select(Test).where(Test.suite_id == suite_id))
    return list(result.scalars().all())


def _topological_order(
    test_ids: set[UUID], predecessors: dict[UUID, set[UUID]]
) -> tuple[list[UUID], set[UUID]]:
    """Kahn's algorithm. Returns (order, unresolved) — unresolved holds any
    test_ids that never reached in-degree 0, i.e. they're part of a cycle
    (or depend, transitively, on one).
    """
    in_degree = {t: len(predecessors.get(t, set())) for t in test_ids}
    successors: dict[UUID, set[UUID]] = {t: set() for t in test_ids}
    for test_id, deps in predecessors.items():
        for dep_id in deps:
            if dep_id in successors:
                successors[dep_id].add(test_id)

    # Sorted seed for deterministic ordering when there's no dependency
    # relationship at all — order doesn't matter functionally, but a stable
    # order makes runs reproducible/debuggable.
    queue = deque(sorted((t for t in test_ids if in_degree[t] == 0), key=str))
    order: list[UUID] = []
    while queue:
        node = queue.popleft()
        order.append(node)
        for successor in sorted(successors.get(node, set()), key=str):
            in_degree[successor] -= 1
            if in_degree[successor] == 0:
                queue.append(successor)

    unresolved = test_ids - set(order)
    return order, unresolved


def _skipped_outcome(reason: str) -> ExecutionOutcome:
    return ExecutionOutcome(
        status="skipped",
        request_snapshot={},
        response_snapshot=None,
        validation_results=[],
        duration_ms=None,
        error=reason,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def execute_suite(
    db: AsyncSession,
    suite_id: UUID,
    environment_id: UUID,
    workspace_id: UUID,
) -> list[Execution]:
    """Run every test in *suite_id* against *environment_id*, dependencies
    first, threading extracted values between tests.

    Raises:
        SuiteNotFoundError: if the suite doesn't exist in the workspace.
        EnvironmentNotFoundError: if the environment doesn't exist in the
            workspace.
        DependencyCycleError: if the suite's dependency edges contain a
            cycle. Nothing is executed and no Execution rows are created —
            the caller should surface exc.test_ids / str(exc) to the user
            rather than retrying.
    """
    await _load_suite(db, suite_id, workspace_id)
    environment = await environment_service.get_environment(db, environment_id, workspace_id)
    tests = await _load_tests(db, suite_id)
    if not tests:
        return []

    tests_by_id = {test.id: test for test in tests}
    test_ids = set(tests_by_id)

    dependencies = await dependency_service.list_dependencies(db, suite_id, workspace_id)
    predecessors: dict[UUID, set[UUID]] = {test_id: set() for test_id in test_ids}
    for dependency in dependencies:
        if dependency.test_id in test_ids and dependency.depends_on_test_id in test_ids:
            predecessors[dependency.test_id].add(dependency.depends_on_test_id)

    order, unresolved = _topological_order(test_ids, predecessors)

    if unresolved:
        cycle_names = [
            f"'{tests_by_id[test_id].name}'" for test_id in sorted(unresolved, key=str)
        ]
        raise DependencyCycleError(
            test_ids=[str(test_id) for test_id in unresolved],
            message=(
                "Can't run this suite: a dependency cycle was found among "
                f"{len(unresolved)} test{'s' if len(unresolved) != 1 else ''} — "
                f"{', '.join(cycle_names)}. Remove or fix the conflicting "
                "dependency (see the suite's Dependencies panel) and try again."
            ),
        )

    variables_context: dict[str, Any] = {}
    blocked: set[UUID] = set()
    execution_ids: list[UUID] = []

    for test_id in order:
        test = tests_by_id[test_id]

        if predecessors[test_id] & blocked:
            outcome = _skipped_outcome("skipped (dependency failed)")
            blocked.add(test_id)
        else:
            outcome = await run_execution(test, environment, extra_variables=variables_context)
            if outcome.status == "passed":
                variables_context.update(outcome.extracted_variables)
            else:
                blocked.add(test_id)

        execution = await execution_service.record_execution(db, test, environment, outcome)
        await db.commit()
        execution_ids.append(execution.id)

    return [
        await execution_service.get_execution(db, execution_id, workspace_id)
        for execution_id in execution_ids
    ]
