"""API-level tests for the deterministic test execution engine.

POST /api/tests/{id}/execute
GET  /api/executions
GET  /api/executions/{id}

Uses respx to mock the HTTP transport — no real network calls happen here.
See scripts/smoke_test_execute.py for a real-network manual check against
https://reqres.in.
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

from app.ai.providers.factory import get_llm_provider
from app.ai.schemas.test_case import (
    Grounding,
    Severity,
    TestCase,
    TestCaseList,
    TestCategory,
    Validation,
    ValidationType,
)
from app.config import get_settings
from app.core.constants import DEFAULT_WORKSPACE_ID
from app.models.environment import Environment
from app.parsers.enums import HttpMethod
from app.services.environment_service import create_environment
from app.services.import_service import import_from_upload

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
async def db() -> AsyncGenerator[AsyncSession, None]:
    """Overrides the conftest `db` fixture to also purge Environment rows
    (Executions cascade-delete from either their Test or Environment FK, so
    purging both Spec and Environment rows cleans everything up).
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
                await session.commit()
            except Exception:  # noqa: BLE001
                pass
    finally:
        await engine.dispose()


async def _create_test_with_validations(db: AsyncSession, validations: list[Validation]) -> UUID:
    """Import the petstore fixture, seed the mock LLM with one TestCase, and
    generate it via the real service call — returns the persisted Test id.
    """
    provider = get_llm_provider()
    provider.seed_structured(
        TestCaseList,
        TestCaseList(
            tests=[
                TestCase(
                    name="Get pet by id",
                    category=TestCategory.POSITIVE,
                    description="Happy path",
                    method=HttpMethod.GET,
                    path="/pet/{{petId}}",
                    validations=validations,
                )
            ]
        ),
    )

    content = (FIXTURES / "petstore_v3.json").read_bytes()
    suite = await import_from_upload(db, DEFAULT_WORKSPACE_ID, content, "petstore_v3.json")
    endpoint = next(
        e for e in suite.endpoints if e.method == "GET" and e.path == "/pet/{petId}"
    )

    from app.services.test_service import generate_tests_for_endpoint  # noqa: PLC0415

    tests = await generate_tests_for_endpoint(db, endpoint.id, DEFAULT_WORKSPACE_ID)
    return tests[0].id


async def _create_environment(db: AsyncSession, **overrides) -> UUID:
    base = {
        "name": "Test Env",
        "base_url": "https://api.example.com",
        "auth_type": "none",
    }
    base.update(overrides)
    environment = await create_environment(db=db, workspace_id=DEFAULT_WORKSPACE_ID, **base)
    return environment.id


# ---------------------------------------------------------------------------
# POST /api/tests/{id}/execute
# ---------------------------------------------------------------------------


@respx.mock
async def test_execute_test_passed(client: AsyncClient, db: AsyncSession) -> None:
    respx.get("https://api.example.com/pet/{petId}".replace("{petId}", "42")).mock(
        return_value=httpx.Response(200, json={"id": 42, "name": "Fido"})
    )

    test_id = await _create_test_with_validations(
        db,
        [
            Validation(
                type=ValidationType.STATUS_CODE,
                description="Status code is 200",
                expected=200,
                severity=Severity.CRITICAL,
            ),
            Validation(
                type=ValidationType.FIELD_EQUALS,
                description="name is Fido",
                target="$.name",
                expected="Fido",
                severity=Severity.CRITICAL,
                grounding=Grounding.SPEC,
            ),
        ],
    )
    environment_id = await _create_environment(db, variables={"petId": "42"})

    response = await client.post(
        f"/api/tests/{test_id}/execute", json={"environment_id": str(environment_id)}
    )

    assert response.status_code == 201, response.text
    data = response.json()
    assert data["status"] == "completed"
    assert len(data["results"]) == 1
    result = data["results"][0]
    assert result["status"] == "passed"
    assert result["response_snapshot"]["status_code"] == 200
    assert result["response_snapshot"]["body"] == {"id": 42, "name": "Fido"}
    assert all(v["passed"] for v in result["validation_results"])
    assert result["duration_ms"] is not None
    assert result["request_snapshot"]["url"] == "https://api.example.com/pet/42"


@respx.mock
async def test_execute_test_failed_validation(client: AsyncClient, db: AsyncSession) -> None:
    respx.get("https://api.example.com/pet/42").mock(
        return_value=httpx.Response(200, json={"id": 42, "name": "Rex"})
    )

    test_id = await _create_test_with_validations(
        db,
        [
            Validation(
                type=ValidationType.FIELD_EQUALS,
                description="name is Fido",
                target="$.name",
                expected="Fido",
                severity=Severity.CRITICAL,
                grounding=Grounding.SPEC,
            ),
        ],
    )
    environment_id = await _create_environment(db, variables={"petId": "42"})

    response = await client.post(
        f"/api/tests/{test_id}/execute", json={"environment_id": str(environment_id)}
    )

    assert response.status_code == 201, response.text
    result = response.json()["results"][0]
    assert result["status"] == "failed"
    assert result["validation_results"][0]["passed"] is False


@respx.mock
async def test_execute_test_connection_error(client: AsyncClient, db: AsyncSession) -> None:
    respx.get("https://api.example.com/pet/42").mock(
        side_effect=httpx.ConnectError("connection refused")
    )

    test_id = await _create_test_with_validations(
        db,
        [
            Validation(
                type=ValidationType.STATUS_CODE,
                description="is 200",
                expected=200,
                severity=Severity.CRITICAL,
            )
        ],
    )
    environment_id = await _create_environment(db, variables={"petId": "42"})

    response = await client.post(
        f"/api/tests/{test_id}/execute", json={"environment_id": str(environment_id)}
    )

    assert response.status_code == 201, response.text
    data = response.json()
    assert data["status"] == "error"
    result = data["results"][0]
    assert result["status"] == "error"
    assert result["response_snapshot"] is None
    assert "ConnectError" in result["error"]


async def test_execute_test_unknown_test_returns_404(
    client: AsyncClient, db: AsyncSession
) -> None:
    unknown_id = UUID("00000000-0000-0000-0000-000000000099")
    environment_id = await _create_environment(db)

    response = await client.post(
        f"/api/tests/{unknown_id}/execute", json={"environment_id": str(environment_id)}
    )
    assert response.status_code == 404, response.text


@respx.mock
async def test_execute_test_unknown_environment_returns_404(
    client: AsyncClient, db: AsyncSession
) -> None:
    test_id = await _create_test_with_validations(
        db,
        [
            Validation(
                type=ValidationType.STATUS_CODE,
                description="is 200",
                expected=200,
                severity=Severity.CRITICAL,
            )
        ],
    )
    unknown_env_id = UUID("00000000-0000-0000-0000-000000000099")

    response = await client.post(
        f"/api/tests/{test_id}/execute", json={"environment_id": str(unknown_env_id)}
    )
    assert response.status_code == 404, response.text


# ---------------------------------------------------------------------------
# GET /api/executions, GET /api/executions/{id}
# ---------------------------------------------------------------------------


@respx.mock
async def test_list_and_get_execution(client: AsyncClient, db: AsyncSession) -> None:
    respx.get("https://api.example.com/pet/42").mock(
        return_value=httpx.Response(200, json={"id": 42, "name": "Fido"})
    )

    test_id = await _create_test_with_validations(
        db,
        [
            Validation(
                type=ValidationType.STATUS_CODE,
                description="is 200",
                expected=200,
                severity=Severity.CRITICAL,
            )
        ],
    )
    environment_id = await _create_environment(db, variables={"petId": "42"})

    exec_response = await client.post(
        f"/api/tests/{test_id}/execute", json={"environment_id": str(environment_id)}
    )
    execution_id = exec_response.json()["id"]

    list_response = await client.get("/api/executions")
    assert list_response.status_code == 200, list_response.text
    ids = {e["id"] for e in list_response.json()}
    assert execution_id in ids

    get_response = await client.get(f"/api/executions/{execution_id}")
    assert get_response.status_code == 200, get_response.text
    data = get_response.json()
    assert data["id"] == execution_id
    assert str(data["test_id"]) == str(test_id)
    assert str(data["environment_id"]) == str(environment_id)
    assert len(data["results"]) == 1


async def test_get_unknown_execution_returns_404(client: AsyncClient, db: AsyncSession) -> None:
    unknown_id = UUID("00000000-0000-0000-0000-000000000099")
    response = await client.get(f"/api/executions/{unknown_id}")
    assert response.status_code == 404, response.text
