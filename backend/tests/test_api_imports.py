"""API-level tests for the import endpoints.

POST /api/imports/upload  — multipart file upload
POST /api/imports/url     — JSON body with URL

These tests use a real PostgreSQL database and the FastAPI ASGI test client.
DB state is cleaned up after each test by the ``db`` fixture from conftest.py.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

FIXTURES = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Test 1 — successful file upload
# ---------------------------------------------------------------------------


async def test_upload_petstore_v3_returns_201_with_suite(
    client: AsyncClient,
    db: AsyncSession,
) -> None:
    """Uploading a valid Swagger spec creates a suite and returns 201."""
    content = (FIXTURES / "petstore_v3.json").read_bytes()

    response = await client.post(
        "/api/imports/upload",
        files={"file": ("petstore_v3.json", content, "application/json")},
    )

    assert response.status_code == 201, response.text

    data = response.json()
    assert "id" in data
    assert data["name"] == "Swagger Petstore - OpenAPI 3.0"
    assert data["generation_status"] == "parsed"
    assert isinstance(data["endpoints"], list)
    assert len(data["endpoints"]) == 19

    # Verify each endpoint has the expected summary fields only
    ep = data["endpoints"][0]
    assert "id" in ep
    assert "method" in ep
    assert "path" in ep
    assert "name" in ep
    assert "schema" not in ep  # EndpointDetailOut is deferred to Sprint 1d


# ---------------------------------------------------------------------------
# Test 2 — empty file → 400
# ---------------------------------------------------------------------------


async def test_upload_empty_file_returns_400(client: AsyncClient) -> None:
    """An empty file upload must be rejected with 400 before hitting the service."""
    response = await client.post(
        "/api/imports/upload",
        files={"file": ("empty.json", b"", "application/json")},
    )
    assert response.status_code == 400, response.text


# ---------------------------------------------------------------------------
# Test 3 — invalid spec → 422
# ---------------------------------------------------------------------------


async def test_upload_invalid_swagger_returns_422(
    client: AsyncClient,
    db: AsyncSession,
) -> None:
    """Content that is not a Swagger spec returns 422 with a detail message."""
    response = await client.post(
        "/api/imports/upload",
        files={"file": ("bad.json", b"not a swagger spec", "application/json")},
    )
    assert response.status_code == 422, response.text
    body = response.json()
    assert "detail" in body
    # The detail should mention parsing (not an internal server error message)
    assert len(body["detail"]) > 0


# ---------------------------------------------------------------------------
# Test 4 — URL import (monkeypatched fetcher)
# ---------------------------------------------------------------------------


async def test_import_from_url_works_with_mock(
    client: AsyncClient,
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """URL import delegates to the fetcher; mocking it exercises the happy path."""
    petstore_bytes = (FIXTURES / "petstore_v3.json").read_bytes()

    async def _mock_fetch(url: str, timeout: float = 30.0) -> tuple[bytes, str]:
        return petstore_bytes, "openapi.json"

    monkeypatch.setattr(
        "app.services.import_service.fetch_spec_from_url", _mock_fetch
    )

    response = await client.post(
        "/api/imports/url",
        json={"url": "https://example.com/openapi.json"},
    )

    assert response.status_code == 201, response.text
    data = response.json()
    assert "id" in data
    assert isinstance(data["endpoints"], list)
    assert len(data["endpoints"]) > 0


# ---------------------------------------------------------------------------
# Test 5 — invalid URL body → 422 (Pydantic validation)
# ---------------------------------------------------------------------------


async def test_import_from_url_invalid_url_returns_422(
    client: AsyncClient,
) -> None:
    """A non-URL string in the request body must fail Pydantic validation (422)."""
    response = await client.post(
        "/api/imports/url",
        json={"url": "not-a-url"},
    )
    assert response.status_code == 422, response.text


# ---------------------------------------------------------------------------
# Test 6 — cURL import happy path
# ---------------------------------------------------------------------------


async def test_import_from_curl_returns_201_with_suite(
    client: AsyncClient,
    db: AsyncSession,
) -> None:
    """Importing curl commands creates a suite with one endpoint per command."""
    curl_text = (
        "curl https://api.example.com/users\n"
        "curl -X POST https://api.example.com/users "
        "-H 'Content-Type: application/json' -d '{\"name\": \"Alice\"}'"
    )

    response = await client.post(
        "/api/imports/curl",
        json={"curl_text": curl_text},
    )

    assert response.status_code == 201, response.text
    data = response.json()
    assert data["name"] == "https://api.example.com"
    assert len(data["endpoints"]) == 2
    assert {e["method"] for e in data["endpoints"]} == {"GET", "POST"}


async def test_import_from_curl_respects_suite_name_override(
    client: AsyncClient,
    db: AsyncSession,
) -> None:
    """An explicit suite_name overrides the derived title."""
    response = await client.post(
        "/api/imports/curl",
        json={
            "curl_text": "curl https://api.example.com/users",
            "suite_name": "My Custom Suite",
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["name"] == "My Custom Suite"


async def test_import_from_curl_invalid_text_returns_422(
    client: AsyncClient,
) -> None:
    """Text that contains no valid curl command returns 422."""
    response = await client.post(
        "/api/imports/curl",
        json={"curl_text": "not a curl command"},
    )
    assert response.status_code == 422, response.text
    assert "detail" in response.json()


async def test_import_from_curl_response_includes_environment_id(
    client: AsyncClient,
    db: AsyncSession,
) -> None:
    """A cURL import response carries the auto-created environment's id so
    the frontend can pre-select it on the suite detail page."""
    response = await client.post(
        "/api/imports/curl",
        json={
            "curl_text": (
                "curl https://api.example.com/users "
                "-H 'Authorization: Bearer abc123'"
            )
        },
    )
    assert response.status_code == 201, response.text
    data = response.json()
    assert data["environment_id"] is not None

    env_response = await client.get(f"/api/environments/{data['environment_id']}")
    assert env_response.status_code == 200, env_response.text
    env = env_response.json()
    assert env["base_url"] == "https://api.example.com"
    assert env["auth_type"] == "bearer"
    assert env["is_incomplete"] is False


async def test_upload_petstore_v3_response_has_null_environment_id(
    client: AsyncClient,
    db: AsyncSession,
) -> None:
    """Swagger imports are unaffected — no base URL/credentials to draw an
    environment from, so environment_id stays null."""
    content = (FIXTURES / "petstore_v3.json").read_bytes()

    response = await client.post(
        "/api/imports/upload",
        files={"file": ("petstore_v3.json", content, "application/json")},
    )
    assert response.status_code == 201, response.text
    assert response.json()["environment_id"] is None


async def test_import_from_curl_empty_text_returns_422(
    client: AsyncClient,
) -> None:
    """Empty curl_text fails Pydantic validation (min_length=1)."""
    response = await client.post(
        "/api/imports/curl",
        json={"curl_text": ""},
    )
    assert response.status_code == 422, response.text
