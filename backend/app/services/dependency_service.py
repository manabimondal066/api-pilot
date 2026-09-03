"""Dependency persistence service (PRD §12, Implementation Plan Module 5,
Sprint 4).

Public functions
----------------
detect_dependencies(db, suite_id, workspace_id) -> list[Dependency]
    Runs the Stage 1 heuristic detector (app/services/dependency_detector.py)
    over every test in the suite, replaces the suite's 'auto'-sourced
    dependency rows with the freshly detected edges, and returns them.

list_dependencies(db, suite_id, workspace_id) -> list[Dependency]
    Current dependency edges for the suite (any source), newest first.

add_dependency(db, suite_id, workspace_id, test_id, depends_on_test_id) -> Dependency
    Manually adds a 'user'-sourced edge (PRD §12.4 manual override).
    Rejects self-loops, tests outside the suite, duplicate edges, and
    edges that would introduce a cycle.

remove_dependency(db, suite_id, workspace_id, dependency_id) -> None
    Deletes one edge, regardless of its source.

Only 'auto' edges are replaced on re-detection — 'user' overrides are left
untouched (PRD §12.4 manual override), matching the "manual override wins"
requirement without a separate merge step.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.dependency import Dependency
from app.models.suite import Suite
from app.models.test import Test
from app.services import (
    DependencyNotFoundError,
    InvalidDependencyError,
    SuiteNotFoundError,
)
from app.services.dependency_detector import DetectableTest, DependencyCycleError, _find_cycle, detect

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


def _to_detectable(test: Test) -> DetectableTest:
    return DetectableTest(
        id=str(test.id),
        method=test.method,
        path=test.path,
        headers=test.headers or {},
        query_params=test.query_params or {},
        body=test.body,
        extractions=test.extractions or [],
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def detect_dependencies(
    db: AsyncSession,
    suite_id: UUID,
    workspace_id: UUID,
) -> list[Dependency]:
    """Detect and persist dependency edges for every test in *suite_id*.

    Raises:
        SuiteNotFoundError: if the suite doesn't exist in the workspace.
        DependencyCycleError: if the detected edges form a cycle — nothing
            is persisted in that case, and the exception carries the
            involved test ids for the caller to surface.
    """
    await _load_suite(db, suite_id, workspace_id)
    tests = await _load_tests(db, suite_id)
    test_ids = {test.id for test in tests}

    detectable = [_to_detectable(test) for test in tests]
    edges = detect(detectable)  # may raise DependencyCycleError

    await db.execute(
        delete(Dependency).where(
            Dependency.source == "auto", Dependency.test_id.in_(test_ids)
        )
    )

    rows = [
        Dependency(
            test_id=UUID(edge.test_id),
            depends_on_test_id=UUID(edge.depends_on_test_id),
            source="auto",
            reason=edge.reason,
        )
        for edge in edges
    ]
    db.add_all(rows)
    await db.commit()

    return await list_dependencies(db, suite_id, workspace_id)


async def list_dependencies(
    db: AsyncSession,
    suite_id: UUID,
    workspace_id: UUID,
) -> list[Dependency]:
    """Return all dependency edges (any source) for tests in *suite_id*.

    Raises:
        SuiteNotFoundError: if the suite doesn't exist in the workspace.
    """
    await _load_suite(db, suite_id, workspace_id)
    result = await db.execute(
        select(Dependency)
        .join(Test, Dependency.test_id == Test.id)
        .where(Test.suite_id == suite_id)
        .options(
            selectinload(Dependency.test),
            selectinload(Dependency.depends_on_test),
        )
        .order_by(Dependency.created_at.desc())
    )
    return list(result.scalars().unique().all())


async def add_dependency(
    db: AsyncSession,
    suite_id: UUID,
    workspace_id: UUID,
    test_id: UUID,
    depends_on_test_id: UUID,
) -> Dependency:
    """Manually add a 'user'-sourced edge: *test_id* depends on
    *depends_on_test_id* (PRD §12.4 manual override).

    Raises:
        SuiteNotFoundError: if the suite doesn't exist in the workspace.
        InvalidDependencyError: if test_id == depends_on_test_id, either
            test doesn't belong to the suite, the edge already exists, or
            adding it would introduce a cycle.
    """
    await _load_suite(db, suite_id, workspace_id)

    if test_id == depends_on_test_id:
        raise InvalidDependencyError("A test cannot depend on itself.")

    tests = await _load_tests(db, suite_id)
    test_ids = {test.id for test in tests}
    if test_id not in test_ids or depends_on_test_id not in test_ids:
        raise InvalidDependencyError(
            "Both tests must belong to the suite being edited."
        )

    existing = await list_dependencies(db, suite_id, workspace_id)
    if any(
        d.test_id == test_id and d.depends_on_test_id == depends_on_test_id
        for d in existing
    ):
        raise InvalidDependencyError("This dependency already exists.")

    graph: dict[str, set[str]] = {str(t): set() for t in test_ids}
    for d in existing:
        graph.setdefault(str(d.test_id), set()).add(str(d.depends_on_test_id))
    graph.setdefault(str(test_id), set()).add(str(depends_on_test_id))

    cycle = _find_cycle(graph)
    if cycle:
        raise DependencyCycleError(cycle)

    dependency = Dependency(
        test_id=test_id,
        depends_on_test_id=depends_on_test_id,
        source="user",
    )
    db.add(dependency)
    await db.commit()
    await db.refresh(dependency, attribute_names=["test", "depends_on_test"])
    return dependency


async def remove_dependency(
    db: AsyncSession,
    suite_id: UUID,
    workspace_id: UUID,
    dependency_id: UUID,
) -> None:
    """Delete one dependency edge, regardless of source.

    Raises:
        SuiteNotFoundError: if the suite doesn't exist in the workspace.
        DependencyNotFoundError: if no matching edge exists in the suite.
    """
    await _load_suite(db, suite_id, workspace_id)

    result = await db.execute(
        select(Dependency)
        .join(Test, Dependency.test_id == Test.id)
        .where(Dependency.id == dependency_id, Test.suite_id == suite_id)
    )
    dependency = result.scalar_one_or_none()
    if dependency is None:
        raise DependencyNotFoundError(
            f"Dependency {dependency_id} not found in suite {suite_id}"
        )

    await db.execute(delete(Dependency).where(Dependency.id == dependency_id))
    await db.commit()
