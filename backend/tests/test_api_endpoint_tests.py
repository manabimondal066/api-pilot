"""API-level tests for AI test generation.

POST /api/endpoints/{id}/generate-tests — synchronous generation + persistence
GET  /api/endpoints/{id}/tests           — list generated tests
GET  /api/tests/{id}                     — single test detail

Uses the MockProvider (LLM_PROVIDER=mock, forced in conftest.py) seeded with
a fixed TestCaseList so generation is deterministic and requires no network
call or API key.
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.providers.base import LLMProviderError
from app.ai.providers.errors import attach_reset_marker
from app.ai.providers.factory import get_llm_provider, reset_provider_cache
from app.ai.schemas.test_case import (
    Severity,
    TestCase,
    TestCaseList,
    TestCategory,
    Validation,
    ValidationType,
)
from app.core.constants import DEFAULT_WORKSPACE_ID
from app.parsers.enums import HttpMethod
from app.services.import_service import import_from_upload

FIXTURES = Path(__file__).parent / "fixtures"


def _seed_one_test() -> None:
    """Seed the (cached, mock) provider with a single deterministic test case."""
    provider = get_llm_provider()
    provider.seed_structured(
        TestCaseList,
        TestCaseList(
            tests=[
                TestCase(
                    name="Create pet with valid input returns 200",
                    category=TestCategory.POSITIVE,
                    description="Happy path",
                    method=HttpMethod.POST,
                    path="/pet",
                    body={"name": "Fido"},
                    validations=[
                        Validation(
                            type=ValidationType.STATUS_CODE,
                            description="Status code is 200",
                            expected=200,
                            severity=Severity.CRITICAL,
                        )
                    ],
                )
            ]
        ),
    )


async def _import_and_get_endpoint_id(db: AsyncSession) -> UUID:
    content = (FIXTURES / "petstore_v3.json").read_bytes()
    suite = await import_from_upload(db, DEFAULT_WORKSPACE_ID, content, "petstore_v3.json")
    target = next(
        ep for ep in suite.endpoints if ep.method == "POST" and ep.path == "/pet"
    )
    return target.id


# ---------------------------------------------------------------------------
# Test 1 — generate-tests happy path
# ---------------------------------------------------------------------------


async def test_generate_tests_persists_and_returns_tests(
    client: AsyncClient,
    db: AsyncSession,
) -> None:
    _seed_one_test()
    endpoint_id = await _import_and_get_endpoint_id(db)

    response = await client.post(f"/api/endpoints/{endpoint_id}/generate-tests")

    assert response.status_code == 201, response.text
    data = response.json()
    assert len(data) == 1

    test = data[0]
    assert test["name"] == "Create pet with valid input returns 200"
    assert test["category"] == "POSITIVE"
    assert test["method"] == "POST"
    assert str(test["endpoint_id"]) == str(endpoint_id)
    assert test["created_by"] == "ai"
    assert len(test["validations"]) == 1
    assert test["validations"][0]["type"] == "STATUS_CODE"


async def test_generate_tests_accepts_use_probe_body_with_flag_off(
    client: AsyncClient,
    db: AsyncSession,
) -> None:
    """Phase B: the route accepts use_probe/environment_id in the request
    body. ENABLE_PROBE_GENERATION is off by default (untouched here), so
    this must behave identically to the no-body call above — no probe, no
    error, same generated test.
    """
    _seed_one_test()
    endpoint_id = await _import_and_get_endpoint_id(db)

    response = await client.post(
        f"/api/endpoints/{endpoint_id}/generate-tests",
        json={"use_probe": True, "environment_id": "00000000-0000-0000-0000-000000000099"},
    )

    assert response.status_code == 201, response.text
    data = response.json()
    assert len(data) == 1
    assert data[0]["name"] == "Create pet with valid input returns 200"


# ---------------------------------------------------------------------------
# Test 2 — generate-tests on unknown endpoint → 404
# ---------------------------------------------------------------------------


async def test_generate_tests_unknown_endpoint_returns_404(
    client: AsyncClient,
    db: AsyncSession,
) -> None:
    unknown_id = UUID("00000000-0000-0000-0000-000000000099")
    response = await client.post(f"/api/endpoints/{unknown_id}/generate-tests")
    assert response.status_code == 404, response.text


# ---------------------------------------------------------------------------
# Test 3 — generate-tests when AI returns zero tests → 502
# ---------------------------------------------------------------------------


async def test_generate_tests_ai_failure_returns_502(
    client: AsyncClient,
    db: AsyncSession,
) -> None:
    get_llm_provider().seed_structured(TestCaseList, TestCaseList(tests=[]))
    endpoint_id = await _import_and_get_endpoint_id(db)

    response = await client.post(f"/api/endpoints/{endpoint_id}/generate-tests")

    assert response.status_code == 502, response.text
    detail = response.json()["detail"]
    assert "message" in detail
    assert "reason" in detail


# ---------------------------------------------------------------------------
# Test 4 — list tests for an endpoint
# ---------------------------------------------------------------------------


async def test_list_tests_for_endpoint(
    client: AsyncClient,
    db: AsyncSession,
) -> None:
    _seed_one_test()
    endpoint_id = await _import_and_get_endpoint_id(db)

    await client.post(f"/api/endpoints/{endpoint_id}/generate-tests")
    response = await client.get(f"/api/endpoints/{endpoint_id}/tests")

    assert response.status_code == 200, response.text
    data = response.json()
    assert len(data) == 1
    assert data[0]["name"] == "Create pet with valid input returns 200"


async def test_list_tests_unknown_endpoint_returns_404(
    client: AsyncClient,
    db: AsyncSession,
) -> None:
    unknown_id = UUID("00000000-0000-0000-0000-000000000099")
    response = await client.get(f"/api/endpoints/{unknown_id}/tests")
    assert response.status_code == 404, response.text


# ---------------------------------------------------------------------------
# Test 5 — get single test
# ---------------------------------------------------------------------------


async def test_get_test_returns_detail(
    client: AsyncClient,
    db: AsyncSession,
) -> None:
    _seed_one_test()
    endpoint_id = await _import_and_get_endpoint_id(db)

    gen_response = await client.post(f"/api/endpoints/{endpoint_id}/generate-tests")
    test_id = gen_response.json()[0]["id"]

    response = await client.get(f"/api/tests/{test_id}")

    assert response.status_code == 200, response.text
    assert response.json()["id"] == test_id


async def test_generate_tests_missing_api_key_returns_502_not_500(
    client: AsyncClient,
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression test: a provider construction failure (e.g. missing API
    key) must surface as a clean 502, not an unhandled 500. Previously
    AIOrchestrationService() raised LLMProviderError from its constructor,
    which wasn't caught by the service-layer try/except.
    """
    endpoint_id = await _import_and_get_endpoint_id(db)

    monkeypatch.setenv("LLM_PROVIDER", "nvidia_nim")
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    reset_provider_cache()
    try:
        response = await client.post(f"/api/endpoints/{endpoint_id}/generate-tests")
    finally:
        monkeypatch.setenv("LLM_PROVIDER", "mock")
        reset_provider_cache()

    assert response.status_code == 502, response.text
    detail = response.json()["detail"]
    assert "NVIDIA_API_KEY" in detail["message"]
    assert detail["reason"] == "unknown"


async def test_generate_tests_quota_exhausted_without_reset_time(
    client: AsyncClient,
    db: AsyncSession,
) -> None:
    """Quota exhaustion is a distinct reason from rate_limited, and the
    reset_at is None when the provider gave no indication of one — the
    frontend then shows "try again later" rather than fabricating a time."""
    endpoint_id = await _import_and_get_endpoint_id(db)
    get_llm_provider().seed_structured_error(
        LLMProviderError(
            "LLM API error (nvidia_nim): Error code: 429 - {'error': "
            "{'message': 'You exceeded your current quota, please check "
            "your plan and billing details.', 'type': 'insufficient_quota'}}"
        )
    )
    try:
        response = await client.post(f"/api/endpoints/{endpoint_id}/generate-tests")
    finally:
        reset_provider_cache()

    assert response.status_code == 502, response.text
    detail = response.json()["detail"]
    assert detail["reason"] == "quota_exhausted"
    assert detail["reset_at"] is None
    assert detail["provider"] == "mock"


async def test_generate_tests_quota_exhausted_with_reset_time(
    client: AsyncClient,
    db: AsyncSession,
) -> None:
    """When the provider's response does include a reset time, it must be
    surfaced (never fabricated) so the frontend can tell the user exactly
    when the quota resets."""
    endpoint_id = await _import_and_get_endpoint_id(db)
    message = attach_reset_marker(
        "LLM API error (nvidia_nim): insufficient_quota — quota exceeded",
        "2026-09-03T00:00:00+00:00",
    )
    get_llm_provider().seed_structured_error(LLMProviderError(message))
    try:
        response = await client.post(f"/api/endpoints/{endpoint_id}/generate-tests")
    finally:
        reset_provider_cache()

    assert response.status_code == 502, response.text
    detail = response.json()["detail"]
    assert detail["reason"] == "quota_exhausted"
    assert detail["reset_at"] == "2026-09-03T00:00:00+00:00"
    assert detail["provider"] == "mock"
    # message is the raw provider text shown to the user as-is — the
    # internal reset marker must not leak into it (reset_at above already
    # carries that information in structured form).
    assert "insufficient_quota" in detail["message"]
    assert "[quota_reset_at=" not in detail["message"]


async def test_generate_tests_request_too_large_classified_distinctly(
    client: AsyncClient,
    db: AsyncSession,
) -> None:
    """The exact Groq 413 'Request too large ... Requested X, Limit Y'
    shape must classify as request_too_large — not rate_limited (despite
    the body's own 'code': 'rate_limit_exceeded') and not unknown."""
    endpoint_id = await _import_and_get_endpoint_id(db)
    get_llm_provider().seed_structured_error(
        LLMProviderError(
            "LLM API error (groq): Error code: 413 - {'error': {'message': "
            "'Request too large for model `llama-3.3-70b-versatile` in "
            "organization `org_abc` service tier `on_demand` on tokens per "
            "minute (TPM): Limit 6000, Requested 8000, please reduce your "
            "message size and try again.', 'type': 'tokens', "
            "'code': 'rate_limit_exceeded'}}"
        )
    )
    try:
        response = await client.post(f"/api/endpoints/{endpoint_id}/generate-tests")
    finally:
        reset_provider_cache()

    assert response.status_code == 502, response.text
    detail = response.json()["detail"]
    assert detail["reason"] == "request_too_large"


async def test_get_unknown_test_returns_404(
    client: AsyncClient,
    db: AsyncSession,
) -> None:
    unknown_id = UUID("00000000-0000-0000-0000-000000000099")
    response = await client.get(f"/api/tests/{unknown_id}")
    assert response.status_code == 404, response.text
