"""API-level tests for suite-level execution (dependency-ordered).

POST /api/suites/{id}/execute
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from pathlib import Path
from uuid import UUID

import httpx
import pytest
import respx
from httpx import AsyncClient
from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.core.constants import DEFAULT_WORKSPACE_ID
from app.models.dependency import Dependency
from app.models.environment import Environment
from app.models.spec import Spec
from app.models.test import Test
from app.services.environment_service import create_environment
from app.services.import_service import import_from_upload

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
async def db() -> AsyncGenerator[AsyncSession, None]:
    """Overrides the conftest `db` fixture to also purge Environment rows
    (Executions cascade-delete from either their Test or Environment FK)
    and Spec rows (this module imports the petstore fixture per test,
    same as test_api_test_execution.py — cascades clean up the suites/
    endpoints/tests/dependencies it creates).
    """
    settings = get_settings()
    engine = create_async_engine(settings.database_url, echo=False)
    factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
    try:
        async with factory() as session:
            try:
                await session.execute(text("SELECT 1"))
            except Exception as exc:  # noqa: BLE001
                pytest.skip(f"PostgreSQL not available: {exc}")
                return

            yield session

            try:
                await session.rollback()
            except Exception:  # noqa: BLE001
                pass
            try:
                await session.execute(
                    delete(Environment).where(
                        Environment.workspace_id == DEFAULT_WORKSPACE_ID
                    )
                )
                await session.execute(
                    delete(Spec).where(Spec.workspace_id == DEFAULT_WORKSPACE_ID)
                )
                await session.commit()
            except Exception:  # noqa: BLE001
                pass
    finally:
        await engine.dispose()


async def _create_suite_with_tests(db: AsyncSession, test_specs: list[dict]) -> tuple[UUID, dict[str, UUID]]:
    """Import the petstore fixture for a suite/endpoint to attach tests to,
    insert Test rows directly by name (bypassing AI generation), and wire
    up Dependency edges from each spec's `depends_on` (list of names).

    Returns (suite_id, {name: test_id}).
    """
    content = (FIXTURES / "petstore_v3.json").read_bytes()
    suite = await import_from_upload(db, DEFAULT_WORKSPACE_ID, content, "petstore_v3.json")
    endpoint_id = suite.endpoints[0].id

    tests_by_name: dict[str, Test] = {}
    for spec in test_specs:
        test = Test(
            suite_id=suite.id,
            endpoint_id=endpoint_id,
            name=spec["name"],
            category="POSITIVE",
            method=spec["method"],
            path=spec["path"],
            headers=spec.get("headers", {}),
            query_params=spec.get("query_params", {}),
            body=spec.get("body"),
            validations=spec.get("validations", []),
            extractions=spec.get("extractions", []),
        )
        db.add(test)
        tests_by_name[spec["name"]] = test
    await db.flush()

    for spec in test_specs:
        for dep_name in spec.get("depends_on", []):
            db.add(
                Dependency(
                    test_id=tests_by_name[spec["name"]].id,
                    depends_on_test_id=tests_by_name[dep_name].id,
                    source="auto",
                )
            )
    await db.commit()

    return suite.id, {name: t.id for name, t in tests_by_name.items()}


async def _create_environment(db: AsyncSession, **overrides) -> UUID:
    base = {
        "name": "Test Env",
        "base_url": "https://api.example.com",
        "auth_type": "none",
    }
    base.update(overrides)
    environment = await create_environment(db=db, workspace_id=DEFAULT_WORKSPACE_ID, **base)
    return environment.id


STATUS_OK = {"type": "STATUS_CODE", "expected": 200, "description": "is 200", "severity": "CRITICAL"}


# ---------------------------------------------------------------------------
# create -> get -> delete chain: id flows through correctly
# ---------------------------------------------------------------------------


@respx.mock
async def test_suite_execution_runs_chain_in_order_and_flows_id(
    client: AsyncClient, db: AsyncSession
) -> None:
    create_route = respx.post("https://api.example.com/pets").mock(
        return_value=httpx.Response(201, json={"id": 99, "name": "Fido"})
    )
    get_route = respx.get("https://api.example.com/pets/99").mock(
        return_value=httpx.Response(200, json={"id": 99, "name": "Fido"})
    )
    delete_route = respx.delete("https://api.example.com/pets/99").mock(
        return_value=httpx.Response(200, json={"deleted": True})
    )

    suite_id, test_ids = await _create_suite_with_tests(
        db,
        [
            {
                "name": "Create Pet",
                "method": "POST",
                "path": "/pets",
                "body": {"name": "Fido"},
                "validations": [STATUS_OK.copy() | {"expected": 201}],
                "extractions": [{"name": "petId", "source": "$.id"}],
            },
            {
                "name": "Get Pet",
                "method": "GET",
                "path": "/pets/{{petId}}",
                "validations": [STATUS_OK.copy()],
                "depends_on": ["Create Pet"],
            },
            {
                "name": "Delete Pet",
                "method": "DELETE",
                "path": "/pets/{{petId}}",
                "validations": [STATUS_OK.copy()],
                "depends_on": ["Get Pet"],
            },
        ],
    )
    environment_id = await _create_environment(db)

    response = await client.post(
        f"/api/suites/{suite_id}/execute", json={"environment_id": str(environment_id)}
    )

    assert response.status_code == 201, response.text
    data = response.json()
    assert len(data) == 3
    assert create_route.called and get_route.called and delete_route.called

    by_test_name = {}
    for execution in data:
        for name, tid in test_ids.items():
            if execution["test_id"] == str(tid):
                by_test_name[name] = execution

    assert by_test_name["Create Pet"]["results"][0]["status"] == "passed"
    assert by_test_name["Get Pet"]["results"][0]["status"] == "passed"
    assert by_test_name["Delete Pet"]["results"][0]["status"] == "passed"

    # the id extracted from Create Pet's response resolved into Get/Delete's URL
    assert get_route.calls.last.request.url.path == "/pets/99"
    assert delete_route.calls.last.request.url.path == "/pets/99"


# ---------------------------------------------------------------------------
# first test fails -> downstream skipped, never called
# ---------------------------------------------------------------------------


@respx.mock
async def test_suite_execution_skips_downstream_on_failure(
    client: AsyncClient, db: AsyncSession
) -> None:
    create_route = respx.post("https://api.example.com/pets").mock(
        return_value=httpx.Response(500, json={"error": "boom"})
    )
    # Deliberately no mocks registered for Get/Delete Pet — they must never
    # actually be called (they're skipped because Create Pet failed); respx
    # would raise AllMockedAssertionError if either one made a real request.

    suite_id, test_ids = await _create_suite_with_tests(
        db,
        [
            {
                "name": "Create Pet",
                "method": "POST",
                "path": "/pets",
                "validations": [STATUS_OK.copy() | {"expected": 201}],
                "extractions": [{"name": "petId", "source": "$.id"}],
            },
            {
                "name": "Get Pet",
                "method": "GET",
                "path": "/pets/{{petId}}",
                "validations": [STATUS_OK.copy()],
                "depends_on": ["Create Pet"],
            },
            {
                "name": "Delete Pet",
                "method": "DELETE",
                "path": "/pets/{{petId}}",
                "validations": [STATUS_OK.copy()],
                "depends_on": ["Get Pet"],
            },
        ],
    )
    environment_id = await _create_environment(db)

    response = await client.post(
        f"/api/suites/{suite_id}/execute", json={"environment_id": str(environment_id)}
    )

    assert response.status_code == 201, response.text
    data = response.json()

    by_test_name = {}
    for execution in data:
        for name, tid in test_ids.items():
            if execution["test_id"] == str(tid):
                by_test_name[name] = execution

    assert create_route.called

    assert by_test_name["Create Pet"]["results"][0]["status"] == "failed"
    get_result = by_test_name["Get Pet"]["results"][0]
    delete_result = by_test_name["Delete Pet"]["results"][0]
    assert get_result["status"] == "skipped"
    assert get_result["error"] == "skipped (dependency failed)"
    assert delete_result["status"] == "skipped"
    assert delete_result["error"] == "skipped (dependency failed)"


# ---------------------------------------------------------------------------
# Fix B (R4) — an 'inconclusive' result must not block dependents or
# discard extractions, unlike a genuine 'failed' result
# ---------------------------------------------------------------------------


@respx.mock
async def test_suite_execution_inconclusive_dependency_does_not_block_downstream(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Create Pet's enforced STATUS_CODE passes, but an advisory FIELD_EXISTS
    (a field that genuinely isn't in the response) fails -> 'inconclusive'.
    Get Pet depends on Create Pet and must still run (not skipped) and must
    receive the id extracted from Create Pet's response.
    """
    create_route = respx.post("https://api.example.com/pets").mock(
        return_value=httpx.Response(201, json={"id": 99, "name": "Fido"})
    )
    get_route = respx.get("https://api.example.com/pets/99").mock(
        return_value=httpx.Response(200, json={"id": 99, "name": "Fido"})
    )

    suite_id, test_ids = await _create_suite_with_tests(
        db,
        [
            {
                "name": "Create Pet",
                "method": "POST",
                "path": "/pets",
                "body": {"name": "Fido"},
                "validations": [
                    STATUS_OK.copy() | {"expected": 201},
                    {
                        "type": "FIELD_EXISTS",
                        "target": "$.token",
                        "description": "has a token",
                        "enforcement": "advisory",
                    },
                ],
                "extractions": [{"name": "petId", "source": "$.id"}],
            },
            {
                "name": "Get Pet",
                "method": "GET",
                "path": "/pets/{{petId}}",
                "validations": [STATUS_OK.copy()],
                "depends_on": ["Create Pet"],
            },
        ],
    )
    environment_id = await _create_environment(db)

    response = await client.post(
        f"/api/suites/{suite_id}/execute", json={"environment_id": str(environment_id)}
    )

    assert response.status_code == 201, response.text
    data = response.json()

    by_test_name = {}
    for execution in data:
        for name, tid in test_ids.items():
            if execution["test_id"] == str(tid):
                by_test_name[name] = execution

    assert create_route.called and get_route.called

    assert by_test_name["Create Pet"]["results"][0]["status"] == "inconclusive"
    # Not skipped, and the id extracted from the inconclusive Create Pet
    # response still resolved into Get Pet's URL.
    assert by_test_name["Get Pet"]["results"][0]["status"] == "passed"
    assert get_route.calls.last.request.url.path == "/pets/99"


# ---------------------------------------------------------------------------
# no dependencies -> everything runs, nothing skipped
# ---------------------------------------------------------------------------


@respx.mock
async def test_suite_execution_no_dependencies_all_run(
    client: AsyncClient, db: AsyncSession
) -> None:
    respx.get("https://api.example.com/pets/1").mock(
        return_value=httpx.Response(200, json={"id": 1})
    )
    respx.get("https://api.example.com/pets/2").mock(
        return_value=httpx.Response(200, json={"id": 2})
    )
    respx.get("https://api.example.com/pets/3").mock(
        return_value=httpx.Response(200, json={"id": 3})
    )

    suite_id, test_ids = await _create_suite_with_tests(
        db,
        [
            {
                "name": "Get Pet 1",
                "method": "GET",
                "path": "/pets/1",
                "validations": [STATUS_OK.copy()],
            },
            {
                "name": "Get Pet 2",
                "method": "GET",
                "path": "/pets/2",
                "validations": [STATUS_OK.copy()],
            },
            {
                "name": "Get Pet 3",
                "method": "GET",
                "path": "/pets/3",
                "validations": [STATUS_OK.copy()],
            },
        ],
    )
    environment_id = await _create_environment(db)

    response = await client.post(
        f"/api/suites/{suite_id}/execute", json={"environment_id": str(environment_id)}
    )

    assert response.status_code == 201, response.text
    data = response.json()
    assert len(data) == 3
    statuses = {e["results"][0]["status"] for e in data}
    assert statuses == {"passed"}


async def test_suite_execution_unknown_suite_returns_404(client: AsyncClient, db: AsyncSession) -> None:
    unknown_id = UUID("00000000-0000-0000-0000-000000000099")
    environment_id = await _create_environment(db)
    response = await client.post(
        f"/api/suites/{unknown_id}/execute", json={"environment_id": str(environment_id)}
    )
    assert response.status_code == 404, response.text


@respx.mock
async def test_suite_execution_unknown_environment_returns_404(
    client: AsyncClient, db: AsyncSession
) -> None:
    respx.get("https://api.example.com/pets/1").mock(return_value=httpx.Response(200, json={"id": 1}))
    suite_id, _ = await _create_suite_with_tests(
        db, [{"name": "Get Pet", "method": "GET", "path": "/pets/1", "validations": [STATUS_OK.copy()]}]
    )
    unknown_env_id = UUID("00000000-0000-0000-0000-000000000099")
    response = await client.post(
        f"/api/suites/{suite_id}/execute", json={"environment_id": str(unknown_env_id)}
    )
    assert response.status_code == 404, response.text


# ---------------------------------------------------------------------------
# Dependency cycle — rejected up front, no partial run
# ---------------------------------------------------------------------------


async def test_suite_execution_rejects_dependency_cycle(
    client: AsyncClient, db: AsyncSession
) -> None:
    """A -> depends on -> B -> depends on -> A (e.g. from two independently
    valid manual overrides) must be rejected with a clear, specific 409 —
    not run partially, not hang, not silently skip.
    """
    suite_id, test_ids = await _create_suite_with_tests(
        db,
        [
            {
                "name": "Create Pet",
                "method": "POST",
                "path": "/pets",
                "depends_on": ["Get Pet"],
            },
            {
                "name": "Get Pet",
                "method": "GET",
                "path": "/pets/1",
                "depends_on": ["Create Pet"],
            },
        ],
    )
    environment_id = await _create_environment(db)

    response = await client.post(
        f"/api/suites/{suite_id}/execute", json={"environment_id": str(environment_id)}
    )

    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert "Create Pet" in detail
    assert "Get Pet" in detail
    assert "cycle" in detail.lower()

    # No Execution rows should exist for either test — a rejected run must
    # not partially execute.
    history = await client.get("/api/executions")
    test_id_strs = {str(test_ids["Create Pet"]), str(test_ids["Get Pet"])}
    assert not any(e["test_id"] in test_id_strs for e in history.json())
