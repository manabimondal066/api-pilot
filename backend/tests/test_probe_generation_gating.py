"""Tests for the three-way gate that decides whether generate_tests_for_endpoint
probes before generating (Phase B): ENABLE_PROBE_GENERATION setting, the
caller's use_probe flag, and the endpoint's suite being cURL-sourced.

Uses the MockProvider (LLM_PROVIDER=mock, see conftest.py) so no real LLM
call happens, and monkeypatches app.services.test_service.probe_service.
probe_endpoint directly rather than exercising the real HTTP probe (that's
covered by tests/test_probe_service.py) — this file is purely about the
gating decision and prompt wiring.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.providers.factory import get_llm_provider
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
from app.services import probe_service, test_service
from app.services.import_service import import_from_curl, import_from_upload
from app.services.probe_service import ProbeResult

FIXTURES = Path(__file__).parent / "fixtures"

CURL_TEXT = (
    'curl -X POST "https://api.example.com/api/v1/login/otp/generate/" '
    '-H "Content-Type: application/json" '
    "-d '{\"phone\": \"5551234567\"}'"
)


def _seed_one_test() -> None:
    provider = get_llm_provider()
    provider.seed_structured(
        TestCaseList,
        TestCaseList(
            tests=[
                TestCase(
                    name="Generates OTP successfully",
                    category=TestCategory.POSITIVE,
                    description="Happy path",
                    method=HttpMethod.POST,
                    path="/api/v1/login/otp/generate/",
                    body={"phone": "5551234567"},
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


async def _create_curl_endpoint(db: AsyncSession) -> tuple[UUID, UUID]:
    suite = await import_from_curl(db, DEFAULT_WORKSPACE_ID, CURL_TEXT)
    return suite.endpoints[0].id, suite.environment_id


async def _create_swagger_endpoint(db: AsyncSession) -> UUID:
    content = (FIXTURES / "petstore_v3.json").read_bytes()
    suite = await import_from_upload(db, DEFAULT_WORKSPACE_ID, content, "petstore_v3.json")
    return suite.endpoints[0].id


def _fake_settings(enable_probe_generation: bool):
    return SimpleNamespace(enable_probe_generation=enable_probe_generation)


def _never_call(*_args, **_kwargs):
    raise AssertionError("probe_service.probe_endpoint should not have been called")


# ---------------------------------------------------------------------------
# Gate: flag off -> never probes, regardless of use_probe or source
# ---------------------------------------------------------------------------


async def test_flag_off_never_probes_even_with_use_probe_true(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(test_service, "get_settings", lambda: _fake_settings(False))
    monkeypatch.setattr(probe_service, "probe_endpoint", _never_call)
    _seed_one_test()
    endpoint_id, environment_id = await _create_curl_endpoint(db)

    tests = await test_service.generate_tests_for_endpoint(
        db, endpoint_id, DEFAULT_WORKSPACE_ID, use_probe=True, environment_id=environment_id
    )

    assert len(tests) == 1
    assert "observed" not in get_llm_provider().calls[-1]["prompt"].lower()


# ---------------------------------------------------------------------------
# Gate: flag on, use_probe false -> never probes
# ---------------------------------------------------------------------------


async def test_flag_on_use_probe_false_never_probes(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(test_service, "get_settings", lambda: _fake_settings(True))
    monkeypatch.setattr(probe_service, "probe_endpoint", _never_call)
    _seed_one_test()
    endpoint_id, environment_id = await _create_curl_endpoint(db)

    tests = await test_service.generate_tests_for_endpoint(
        db, endpoint_id, DEFAULT_WORKSPACE_ID, use_probe=False, environment_id=environment_id
    )

    assert len(tests) == 1


# ---------------------------------------------------------------------------
# Gate: flag on, use_probe true, but Swagger-sourced -> never probes
# ---------------------------------------------------------------------------


async def test_flag_on_use_probe_true_but_swagger_source_never_probes(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(test_service, "get_settings", lambda: _fake_settings(True))
    monkeypatch.setattr(probe_service, "probe_endpoint", _never_call)
    _seed_one_test()
    endpoint_id = await _create_swagger_endpoint(db)

    tests = await test_service.generate_tests_for_endpoint(
        db, endpoint_id, DEFAULT_WORKSPACE_ID, use_probe=True, environment_id=None
    )

    assert len(tests) == 1


# ---------------------------------------------------------------------------
# Gate open: flag on, use_probe true, cURL-sourced -> probes, and the
# observed response reaches the prompt
# ---------------------------------------------------------------------------


async def test_all_conditions_met_probes_and_grounds_the_prompt(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(test_service, "get_settings", lambda: _fake_settings(True))

    calls: list[tuple] = []

    async def _fake_probe(db_, endpoint, environment_id, workspace_id):
        calls.append((endpoint.id, environment_id, workspace_id))
        return ProbeResult(status_code=200, body_text='{"message": "otp generated"}')

    monkeypatch.setattr(probe_service, "probe_endpoint", _fake_probe)
    _seed_one_test()
    endpoint_id, environment_id = await _create_curl_endpoint(db)

    tests = await test_service.generate_tests_for_endpoint(
        db, endpoint_id, DEFAULT_WORKSPACE_ID, use_probe=True, environment_id=environment_id
    )

    assert len(tests) == 1
    assert len(calls) == 1
    assert calls[0] == (endpoint_id, environment_id, DEFAULT_WORKSPACE_ID)

    prompt = get_llm_provider().calls[-1]["prompt"]
    assert "observed" in prompt.lower()
    assert "otp generated" in prompt


# ---------------------------------------------------------------------------
# Probe failure falls through silently — generation still succeeds, prompt
# is the plain (no-probe) prompt
# ---------------------------------------------------------------------------


async def test_probe_failure_falls_through_to_ungrounded_generation(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(test_service, "get_settings", lambda: _fake_settings(True))

    async def _failing_probe(*_args, **_kwargs):
        return None  # probe_service's own contract: any failure -> None

    monkeypatch.setattr(probe_service, "probe_endpoint", _failing_probe)
    _seed_one_test()
    endpoint_id, environment_id = await _create_curl_endpoint(db)

    tests = await test_service.generate_tests_for_endpoint(
        db, endpoint_id, DEFAULT_WORKSPACE_ID, use_probe=True, environment_id=environment_id
    )

    assert len(tests) == 1
    assert "observed" not in get_llm_provider().calls[-1]["prompt"].lower()


# ---------------------------------------------------------------------------
# Default parameters (no probing requested at all) behave exactly like
# calling generate_tests_for_endpoint did before Phase B
# ---------------------------------------------------------------------------


async def test_default_call_with_no_probe_args_is_unaffected(db: AsyncSession) -> None:
    _seed_one_test()
    endpoint_id, _environment_id = await _create_curl_endpoint(db)

    tests = await test_service.generate_tests_for_endpoint(db, endpoint_id, DEFAULT_WORKSPACE_ID)

    assert len(tests) == 1
    assert "observed" not in get_llm_provider().calls[-1]["prompt"].lower()
