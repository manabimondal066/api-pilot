"""API-level tests for the suite endpoints.

GET /api/suites           — list suites in the current workspace
GET /api/suites/{suite_id} — suite detail with endpoint list

Setup for tests that need data is done via the import service directly
(faster than going through the HTTP layer).  The ``db`` fixture from
conftest.py handles teardown.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import UUID

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import DEFAULT_WORKSPACE_ID
from app.services.import_service import import_from_upload

FIXTURES = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Test 1 — empty list
# ---------------------------------------------------------------------------


async def test_list_suites_empty_returns_empty_array(
    client: AsyncClient,
    db: AsyncSession,
) -> None:
    """When no suites exist the list endpoint returns an empty JSON array."""
    response = await client.get("/api/suites")
    assert response.status_code == 200, response.text
    assert response.json() == []


# ---------------------------------------------------------------------------
# Test 2 — list with data
# ---------------------------------------------------------------------------


async def test_list_suites_returns_imported_suites_with_counts(
    client: AsyncClient,
    db: AsyncSession,
) -> None:
    """After importing a spec, the list shows the suite with correct endpoint_count."""
    content = (FIXTURES / "petstore_v3.json").read_bytes()
    await import_from_upload(db, DEFAULT_WORKSPACE_ID, content, "petstore_v3.json")

    response = await client.get("/api/suites")
    assert response.status_code == 200, response.text

    data = response.json()
    assert len(data) == 1

    suite = data[0]
    assert suite["endpoint_count"] == 19
    assert "endpoints" not in suite, (
        "SuiteSummaryOut must NOT include the endpoint list — only endpoint_count"
    )
    assert suite["generation_status"] == "parsed"


# ---------------------------------------------------------------------------
# Test 3 — suite detail
# ---------------------------------------------------------------------------


async def test_get_suite_returns_full_detail(
    client: AsyncClient,
    db: AsyncSession,
) -> None:
    """The detail endpoint returns all 19 endpoints without the schema blob."""
    content = (FIXTURES / "petstore_v3.json").read_bytes()
    suite = await import_from_upload(db, DEFAULT_WORKSPACE_ID, content, "petstore_v3.json")

    response = await client.get(f"/api/suites/{suite.id}")
    assert response.status_code == 200, response.text

    data = response.json()
    assert "endpoints" in data
    endpoints = data["endpoints"]
    assert len(endpoints) == 19

    for ep in endpoints:
        assert "id" in ep
        assert "method" in ep
        assert "path" in ep
        assert "name" in ep
        # schema blob must NOT be present in the summary endpoint view
        assert "schema" not in ep, (
            f"Endpoint {ep.get('name')!r} unexpectedly contains a 'schema' key"
        )


# ---------------------------------------------------------------------------
# Test 4 — unknown suite → 404
# ---------------------------------------------------------------------------


async def test_get_unknown_suite_returns_404(
    client: AsyncClient,
    db: AsyncSession,
) -> None:
    """Requesting a suite that does not exist returns HTTP 404."""
    unknown_id = UUID("00000000-0000-0000-0000-000000000099")
    response = await client.get(f"/api/suites/{unknown_id}")
    assert response.status_code == 404, response.text


# ---------------------------------------------------------------------------
# Test 5 — ordering (newest first)
# ---------------------------------------------------------------------------


async def test_list_suites_orders_by_created_at_desc(
    client: AsyncClient,
    db: AsyncSession,
) -> None:
    """The suite list is ordered newest-first (created_at DESC)."""
    content = (FIXTURES / "petstore_v3.json").read_bytes()

    # Import twice; sleep ensures distinct created_at timestamps
    await import_from_upload(db, DEFAULT_WORKSPACE_ID, content, "petstore_v3.json")
    await asyncio.sleep(0.05)
    await import_from_upload(db, DEFAULT_WORKSPACE_ID, content, "petstore_v3.json")

    response = await client.get("/api/suites")
    assert response.status_code == 200, response.text

    data = response.json()
    assert len(data) == 2, f"Expected 2 suites, got {len(data)}"

    from datetime import datetime, timezone

    first_dt = datetime.fromisoformat(data[0]["created_at"])
    second_dt = datetime.fromisoformat(data[1]["created_at"])
    # Newest import should appear first
    assert first_dt >= second_dt, (
        f"Expected descending order: {first_dt} >= {second_dt}"
    )
