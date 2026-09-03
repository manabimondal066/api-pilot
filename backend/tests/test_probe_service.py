"""Tests for probe-grounded generation's probe step
(app/services/probe_service.py) — replaying a cURL-imported endpoint's
stored example request once, for real, and capturing the response.

Uses respx to mock the HTTP transport (no real network calls) and a real
Postgres session (via the shared `db` fixture) so the endpoint's stored
example request comes from an actual cURL import, exactly as it would in
production.
"""

from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

import httpx
import pytest
import respx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import DEFAULT_WORKSPACE_ID
from app.models.execution import Execution
from app.services import probe_service
from app.services.environment_service import create_environment
from app.services.import_service import import_from_curl

CURL_TEXT = (
    'curl -X POST "https://api.example.com/api/v1/login/otp/generate/" '
    '-H "Content-Type: application/json" '
    '-H "X-Api-Key: secret-123" '
    '-d \'{"phone": "5551234567"}\''
)


async def _create_curl_endpoint(db: AsyncSession) -> tuple[UUID, UUID]:
    """Import CURL_TEXT and return (endpoint_id, environment_id) — the
    environment is the one auto-created by import_from_curl itself."""
    suite = await import_from_curl(db, DEFAULT_WORKSPACE_ID, CURL_TEXT)
    return suite.endpoints[0].id, suite.environment_id


async def _load_endpoint(db: AsyncSession, endpoint_id: UUID):
    from app.models.endpoint import Endpoint  # noqa: PLC0415

    result = await db.execute(select(Endpoint).where(Endpoint.id == endpoint_id))
    return result.scalar_one()


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


@respx.mock
async def test_probe_endpoint_sends_exactly_one_request_and_returns_result(
    db: AsyncSession,
) -> None:
    route = respx.post("https://api.example.com/api/v1/login/otp/generate/").mock(
        return_value=httpx.Response(
            200, json={"message": "otp generated", "otp_provider": "Static"}
        )
    )
    endpoint_id, environment_id = await _create_curl_endpoint(db)
    endpoint = await _load_endpoint(db, endpoint_id)

    result = await probe_service.probe_endpoint(db, endpoint, environment_id, DEFAULT_WORKSPACE_ID)

    assert route.call_count == 1
    assert result is not None
    assert result.status_code == 200
    assert "otp generated" in result.body_text
    assert "otp_provider" in result.body_text
    # The probe replayed the endpoint's own stored body, not an invented one.
    import json  # noqa: PLC0415

    assert json.loads(route.calls.last.request.content) == {"phone": "5551234567"}
    # And its stored headers (beyond what the auto-created environment
    # already carries as defaults/auth).
    assert route.calls.last.request.headers["content-type"] == "application/json"


@respx.mock
async def test_probe_endpoint_never_creates_an_execution_record(db: AsyncSession) -> None:
    respx.post("https://api.example.com/api/v1/login/otp/generate/").mock(
        return_value=httpx.Response(200, json={"message": "ok"})
    )
    endpoint_id, environment_id = await _create_curl_endpoint(db)
    endpoint = await _load_endpoint(db, endpoint_id)

    await probe_service.probe_endpoint(db, endpoint, environment_id, DEFAULT_WORKSPACE_ID)

    result = await db.execute(select(Execution))
    assert result.scalars().all() == []


@respx.mock
async def test_probe_endpoint_handles_non_json_body_without_crashing(db: AsyncSession) -> None:
    respx.post("https://api.example.com/api/v1/login/otp/generate/").mock(
        return_value=httpx.Response(200, text="not json at all")
    )
    endpoint_id, environment_id = await _create_curl_endpoint(db)
    endpoint = await _load_endpoint(db, endpoint_id)

    result = await probe_service.probe_endpoint(db, endpoint, environment_id, DEFAULT_WORKSPACE_ID)

    assert result is not None
    assert result.status_code == 200
    assert "not json at all" in result.body_text


def test_truncate_body_caps_around_4000_characters() -> None:
    huge = {"data": "x" * 10_000}
    text = probe_service._truncate_body(huge)
    assert len(text) < 4100
    assert text.endswith("...(truncated)")


# ---------------------------------------------------------------------------
# Failure paths — every one must return None, never raise
# ---------------------------------------------------------------------------


async def test_probe_endpoint_returns_none_when_environment_id_is_none(db: AsyncSession) -> None:
    endpoint_id, _environment_id = await _create_curl_endpoint(db)
    endpoint = await _load_endpoint(db, endpoint_id)

    result = await probe_service.probe_endpoint(db, endpoint, None, DEFAULT_WORKSPACE_ID)

    assert result is None


async def test_probe_endpoint_returns_none_when_environment_not_found(db: AsyncSession) -> None:
    endpoint_id, _environment_id = await _create_curl_endpoint(db)
    endpoint = await _load_endpoint(db, endpoint_id)

    result = await probe_service.probe_endpoint(db, endpoint, uuid4(), DEFAULT_WORKSPACE_ID)

    assert result is None


@respx.mock
async def test_probe_endpoint_returns_none_on_connection_error(db: AsyncSession) -> None:
    respx.post("https://api.example.com/api/v1/login/otp/generate/").mock(
        side_effect=httpx.ConnectError("connection refused")
    )
    endpoint_id, environment_id = await _create_curl_endpoint(db)
    endpoint = await _load_endpoint(db, endpoint_id)

    result = await probe_service.probe_endpoint(db, endpoint, environment_id, DEFAULT_WORKSPACE_ID)

    assert result is None


async def test_probe_endpoint_returns_none_on_timeout(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exercises the 10s (here shortened) hard timeout without actually
    waiting ~10 real seconds."""
    monkeypatch.setattr(probe_service, "_PROBE_TIMEOUT_SECONDS", 0.05)

    async def _slow_execute(*_args, **_kwargs):
        await asyncio.sleep(1)
        raise AssertionError("should have been cancelled by the timeout")

    monkeypatch.setattr(probe_service, "run_execution", _slow_execute)

    endpoint_id, environment_id = await _create_curl_endpoint(db)
    endpoint = await _load_endpoint(db, endpoint_id)

    result = await probe_service.probe_endpoint(db, endpoint, environment_id, DEFAULT_WORKSPACE_ID)

    assert result is None


async def test_probe_endpoint_never_retries(db: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    """Exactly one call to the execution engine, even conceptually — no
    retry loop exists in probe_endpoint at all."""
    calls = []

    async def _counting_execute(*args, **kwargs):
        calls.append(1)
        raise httpx.ConnectError("boom")

    monkeypatch.setattr(probe_service, "run_execution", _counting_execute)

    endpoint_id, environment_id = await _create_curl_endpoint(db)
    endpoint = await _load_endpoint(db, endpoint_id)

    result = await probe_service.probe_endpoint(db, endpoint, environment_id, DEFAULT_WORKSPACE_ID)

    assert result is None
    assert len(calls) == 1
