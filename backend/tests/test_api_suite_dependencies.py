"""API-level tests for heuristic dependency detection.

POST /api/suites/{id}/detect-dependencies
GET  /api/suites/{id}/dependencies
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import DEFAULT_WORKSPACE_ID
from app.models.test import Test
from app.services.import_service import import_from_upload

FIXTURES = Path(__file__).parent / "fixtures"


async def _create_suite_with_tests_named(
    db: AsyncSession, test_specs: list[dict]
) -> tuple[UUID, dict[str, UUID]]:
    """Same as _create_suite_with_tests but also returns {name: test_id},
    for tests that need to reference specific tests by id (add/remove
    dependency edges).
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
            extractions=spec.get("extractions", []),
        )
        db.add(test)
        tests_by_name[spec["name"]] = test
    await db.commit()

    return suite.id, {name: t.id for name, t in tests_by_name.items()}


async def _create_suite_with_tests(db: AsyncSession, test_specs: list[dict]) -> UUID:
    """Import the petstore fixture for a suite/endpoint to attach tests to,
    then insert Test rows directly (bypassing AI generation — this suite
    only exists to exercise dependency detection over hand-picked
    method/path/extraction combinations).
    """
    content = (FIXTURES / "petstore_v3.json").read_bytes()
    suite = await import_from_upload(db, DEFAULT_WORKSPACE_ID, content, "petstore_v3.json")
    endpoint_id = suite.endpoints[0].id

    tests = [
        Test(
            suite_id=suite.id,
            endpoint_id=endpoint_id,
            name=spec.get("name", spec["method"] + " " + spec["path"]),
            category="POSITIVE",
            method=spec["method"],
            path=spec["path"],
            headers=spec.get("headers", {}),
            query_params=spec.get("query_params", {}),
            body=spec.get("body"),
            extractions=spec.get("extractions", []),
        )
        for spec in test_specs
    ]
    db.add_all(tests)
    await db.commit()
    return suite.id


# ---------------------------------------------------------------------------
# POST /api/suites/{id}/detect-dependencies
# ---------------------------------------------------------------------------


async def test_detect_dependencies_finds_create_get_chain(
    client: AsyncClient, db: AsyncSession
) -> None:
    suite_id = await _create_suite_with_tests(
        db,
        [
            {
                "name": "Create User",
                "method": "POST",
                "path": "/users",
                "extractions": [{"name": "userId", "source": "$.id"}],
            },
            {"name": "Get User", "method": "GET", "path": "/users/{{userId}}"},
            {
                "name": "Update User",
                "method": "PUT",
                "path": "/users/{{userId}}",
                "body": {"name": "Bob"},
            },
            {"name": "Delete User", "method": "DELETE", "path": "/users/{{userId}}"},
        ],
    )

    response = await client.post(f"/api/suites/{suite_id}/detect-dependencies")
    assert response.status_code == 200, response.text
    data = response.json()

    reasons = {(d["source"]) for d in data}
    assert reasons == {"auto"}
    assert len(data) == 3  # get, update, delete each depend on create


async def test_detect_dependencies_no_false_positive_for_unrelated_tests(
    client: AsyncClient, db: AsyncSession
) -> None:
    suite_id = await _create_suite_with_tests(
        db,
        [
            {
                "name": "Create User",
                "method": "POST",
                "path": "/users",
                "extractions": [{"name": "userId", "source": "$.id"}],
            },
            {"name": "List Orders", "method": "GET", "path": "/orders"},
        ],
    )

    response = await client.post(f"/api/suites/{suite_id}/detect-dependencies")
    assert response.status_code == 200, response.text
    assert response.json() == []


async def test_detect_dependencies_rejects_cycle(client: AsyncClient, db: AsyncSession) -> None:
    suite_id = await _create_suite_with_tests(
        db,
        [
            {
                "name": "A",
                "method": "PUT",
                "path": "/items/{{bId}}",
                "extractions": [{"name": "aId", "source": "$.id"}],
            },
            {
                "name": "B",
                "method": "PUT",
                "path": "/items/{{aId}}",
                "extractions": [{"name": "bId", "source": "$.id"}],
            },
        ],
    )

    response = await client.post(f"/api/suites/{suite_id}/detect-dependencies")
    assert response.status_code == 409, response.text


async def test_detect_dependencies_unknown_suite_returns_404(client: AsyncClient) -> None:
    unknown_id = UUID("00000000-0000-0000-0000-000000000099")
    response = await client.post(f"/api/suites/{unknown_id}/detect-dependencies")
    assert response.status_code == 404, response.text


# ---------------------------------------------------------------------------
# GET /api/suites/{id}/dependencies
# ---------------------------------------------------------------------------


async def test_get_dependencies_returns_persisted_edges(
    client: AsyncClient, db: AsyncSession
) -> None:
    suite_id = await _create_suite_with_tests(
        db,
        [
            {
                "name": "Create User",
                "method": "POST",
                "path": "/users",
                "extractions": [{"name": "userId", "source": "$.id"}],
            },
            {"name": "Get User", "method": "GET", "path": "/users/{{userId}}"},
        ],
    )

    detect_response = await client.post(f"/api/suites/{suite_id}/detect-dependencies")
    assert detect_response.status_code == 200, detect_response.text

    get_response = await client.get(f"/api/suites/{suite_id}/dependencies")
    assert get_response.status_code == 200, get_response.text
    assert len(get_response.json()) == 1


async def test_get_dependencies_unknown_suite_returns_404(client: AsyncClient) -> None:
    unknown_id = UUID("00000000-0000-0000-0000-000000000099")
    response = await client.get(f"/api/suites/{unknown_id}/dependencies")
    assert response.status_code == 404, response.text


async def test_redetect_replaces_auto_edges_not_user_edges(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Re-running detection should not duplicate 'auto' edges, and must
    leave a manually-added 'user' edge untouched (PRD §12.4)."""
    suite_id = await _create_suite_with_tests(
        db,
        [
            {
                "name": "Create User",
                "method": "POST",
                "path": "/users",
                "extractions": [{"name": "userId", "source": "$.id"}],
            },
            {"name": "Get User", "method": "GET", "path": "/users/{{userId}}"},
        ],
    )

    from app.models.dependency import Dependency
    from app.services.dependency_service import _load_tests  # noqa: PLC0415

    tests = await _load_tests(db, suite_id)
    manual_edge = Dependency(
        test_id=tests[0].id, depends_on_test_id=tests[1].id, source="user"
    )
    db.add(manual_edge)
    await db.commit()

    first = await client.post(f"/api/suites/{suite_id}/detect-dependencies")
    second = await client.post(f"/api/suites/{suite_id}/detect-dependencies")
    assert first.status_code == 200 and second.status_code == 200

    all_deps = await client.get(f"/api/suites/{suite_id}/dependencies")
    data = all_deps.json()
    sources = [d["source"] for d in data]
    assert sources.count("auto") == 1
    assert sources.count("user") == 1


# ---------------------------------------------------------------------------
# POST   /api/suites/{id}/dependencies   — manual add
# DELETE /api/suites/{id}/dependencies/{dependency_id} — manual remove
# ---------------------------------------------------------------------------


async def test_add_dependency_persists_and_is_listed(
    client: AsyncClient, db: AsyncSession
) -> None:
    suite_id, test_ids = await _create_suite_with_tests_named(
        db,
        [
            {"name": "Create User", "method": "POST", "path": "/users"},
            {"name": "Get User", "method": "GET", "path": "/users/1"},
        ],
    )

    response = await client.post(
        f"/api/suites/{suite_id}/dependencies",
        json={
            "test_id": str(test_ids["Get User"]),
            "depends_on_test_id": str(test_ids["Create User"]),
        },
    )
    assert response.status_code == 201, response.text
    data = response.json()
    assert data["source"] == "user"
    assert data["test_id"] == str(test_ids["Get User"])
    assert data["depends_on_test_id"] == str(test_ids["Create User"])

    listed = await client.get(f"/api/suites/{suite_id}/dependencies")
    assert len(listed.json()) == 1


async def test_add_dependency_rejects_self_loop(client: AsyncClient, db: AsyncSession) -> None:
    suite_id, test_ids = await _create_suite_with_tests_named(
        db, [{"name": "Create User", "method": "POST", "path": "/users"}]
    )

    response = await client.post(
        f"/api/suites/{suite_id}/dependencies",
        json={
            "test_id": str(test_ids["Create User"]),
            "depends_on_test_id": str(test_ids["Create User"]),
        },
    )
    assert response.status_code == 400, response.text


async def test_add_dependency_rejects_duplicate(client: AsyncClient, db: AsyncSession) -> None:
    suite_id, test_ids = await _create_suite_with_tests_named(
        db,
        [
            {"name": "Create User", "method": "POST", "path": "/users"},
            {"name": "Get User", "method": "GET", "path": "/users/1"},
        ],
    )
    payload = {
        "test_id": str(test_ids["Get User"]),
        "depends_on_test_id": str(test_ids["Create User"]),
    }
    first = await client.post(f"/api/suites/{suite_id}/dependencies", json=payload)
    assert first.status_code == 201, first.text

    second = await client.post(f"/api/suites/{suite_id}/dependencies", json=payload)
    assert second.status_code == 400, second.text


async def test_add_dependency_rejects_cycle(client: AsyncClient, db: AsyncSession) -> None:
    suite_id, test_ids = await _create_suite_with_tests_named(
        db,
        [
            {"name": "A", "method": "GET", "path": "/a"},
            {"name": "B", "method": "GET", "path": "/b"},
        ],
    )
    first = await client.post(
        f"/api/suites/{suite_id}/dependencies",
        json={"test_id": str(test_ids["B"]), "depends_on_test_id": str(test_ids["A"])},
    )
    assert first.status_code == 201, first.text

    # A depends on B would close the loop A -> B -> A
    second = await client.post(
        f"/api/suites/{suite_id}/dependencies",
        json={"test_id": str(test_ids["A"]), "depends_on_test_id": str(test_ids["B"])},
    )
    assert second.status_code == 409, second.text


async def test_add_dependency_unknown_suite_returns_404(client: AsyncClient) -> None:
    unknown_id = UUID("00000000-0000-0000-0000-000000000099")
    response = await client.post(
        f"/api/suites/{unknown_id}/dependencies",
        json={
            "test_id": str(unknown_id),
            "depends_on_test_id": str(UUID("00000000-0000-0000-0000-000000000098")),
        },
    )
    assert response.status_code == 404, response.text


async def test_remove_dependency_persists_after_reload(
    client: AsyncClient, db: AsyncSession
) -> None:
    suite_id, test_ids = await _create_suite_with_tests_named(
        db,
        [
            {"name": "Create User", "method": "POST", "path": "/users"},
            {"name": "Get User", "method": "GET", "path": "/users/1"},
        ],
    )
    add_response = await client.post(
        f"/api/suites/{suite_id}/dependencies",
        json={
            "test_id": str(test_ids["Get User"]),
            "depends_on_test_id": str(test_ids["Create User"]),
        },
    )
    dependency_id = add_response.json()["id"]

    delete_response = await client.delete(
        f"/api/suites/{suite_id}/dependencies/{dependency_id}"
    )
    assert delete_response.status_code == 204, delete_response.text

    listed = await client.get(f"/api/suites/{suite_id}/dependencies")
    assert listed.json() == []


async def test_remove_dependency_unknown_id_returns_404(
    client: AsyncClient, db: AsyncSession
) -> None:
    suite_id, _ = await _create_suite_with_tests_named(
        db, [{"name": "Create User", "method": "POST", "path": "/users"}]
    )
    unknown_id = UUID("00000000-0000-0000-0000-000000000099")
    response = await client.delete(f"/api/suites/{suite_id}/dependencies/{unknown_id}")
    assert response.status_code == 404, response.text
