"""Unit tests for the deterministic execution engine
(app/services/execution_engine.py). No DB, no AI — httpx calls are mocked
with respx so no real network traffic happens in the test suite.
"""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
import respx

from app.services.execution_engine import build_request, execute, run_validations


def _test(
    method="GET",
    path="/pet/{{petId}}",
    headers=None,
    query_params=None,
    body=None,
    validations=None,
):
    return SimpleNamespace(
        method=method,
        path=path,
        headers=headers or {},
        query_params=query_params or {},
        body=body,
        validations=validations or [],
    )


def _environment(
    base_url="https://api.example.com",
    auth_type="none",
    auth_config=None,
    default_headers=None,
    variables=None,
):
    return SimpleNamespace(
        base_url=base_url,
        auth_type=auth_type,
        auth_config=auth_config or {},
        default_headers=default_headers or {},
        variables=variables or {},
    )


# ---------------------------------------------------------------------------
# build_request — variable substitution, auth, header merging
# ---------------------------------------------------------------------------


def test_build_request_resolves_base_url_and_path():
    plan = build_request(_test(path="/pet"), _environment())
    assert plan.method == "GET"
    assert plan.url == "https://api.example.com/pet"


def test_build_request_substitutes_variables_in_path():
    test = _test(path="/pet/{{petId}}")
    env = _environment(variables={"petId": "42"})
    plan = build_request(test, env)
    assert plan.url == "https://api.example.com/pet/42"


def test_build_request_leaves_unresolved_variable_literal():
    test = _test(path="/pet/{{missing}}")
    env = _environment(variables={})
    plan = build_request(test, env)
    assert plan.url == "https://api.example.com/pet/{{missing}}"


def test_build_request_substitutes_variables_in_headers_body_and_params():
    test = _test(
        path="/pet",
        headers={"X-Tenant": "{{tenantId}}"},
        query_params={"status": "{{status}}"},
        body={"name": "{{petName}}"},
    )
    env = _environment(variables={"tenantId": "acme", "status": "available", "petName": "Fido"})
    plan = build_request(test, env)
    assert plan.headers["X-Tenant"] == "acme"
    assert plan.params == {"status": "available"}
    assert plan.json_body == {"name": "Fido"}


def test_build_request_merges_default_headers_with_test_headers():
    test = _test(path="/pet", headers={"X-Test": "1"})
    env = _environment(default_headers={"X-Env": "qa"})
    plan = build_request(test, env)
    assert plan.headers["X-Env"] == "qa"
    assert plan.headers["X-Test"] == "1"


def test_build_request_bearer_auth():
    env = _environment(auth_type="bearer", auth_config={"token": "secret123"})
    plan = build_request(_test(path="/pet"), env)
    assert plan.headers["Authorization"] == "Bearer secret123"


def test_build_request_api_key_auth():
    env = _environment(
        auth_type="api_key", auth_config={"header": "X-API-Key", "value": "k-1"}
    )
    plan = build_request(_test(path="/pet"), env)
    assert plan.headers["X-API-Key"] == "k-1"


def test_build_request_basic_auth():
    env = _environment(
        auth_type="basic", auth_config={"username": "user", "password": "pass"}
    )
    plan = build_request(_test(path="/pet"), env)
    assert plan.headers["Authorization"].startswith("Basic ")


def test_build_request_no_auth_adds_no_header():
    env = _environment(auth_type="none")
    plan = build_request(_test(path="/pet"), env)
    assert "Authorization" not in plan.headers


def test_build_request_api_key_auth_overrides_case_insensitive_default_header():
    """A stale `default_headers` entry that only differs in case from the
    Auth type header name (e.g. "x-api-key" vs "X-API-Key") must not
    coexist as a silent duplicate — the auth-configured value wins and
    only one header is sent.
    """
    env = _environment(
        auth_type="api_key",
        auth_config={"header": "X-API-Key", "value": "correct-key"},
        default_headers={"x-api-key": "stale-key"},
    )
    plan = build_request(_test(path="/pet"), env)
    assert plan.headers == {"X-API-Key": "correct-key"}


def test_build_request_bearer_auth_overrides_case_insensitive_default_header():
    env = _environment(
        auth_type="bearer",
        auth_config={"token": "correct-token"},
        default_headers={"authorization": "Bearer stale-token"},
    )
    plan = build_request(_test(path="/pet"), env)
    assert plan.headers == {"Authorization": "Bearer correct-token"}


# ---------------------------------------------------------------------------
# run_validations — STATUS_CODE, FIELD_EXISTS, FIELD_EQUALS
# ---------------------------------------------------------------------------


def _response(status_code=200, json_body=None):
    return httpx.Response(
        status_code,
        json=json_body,
        request=httpx.Request("GET", "https://api.example.com/pet"),
    )


def test_status_code_validation_pass_and_fail():
    validations = [{"type": "STATUS_CODE", "expected": 200, "description": "is 200"}]
    results = run_validations(validations, _response(status_code=200))
    assert results[0]["passed"] is True

    results = run_validations(validations, _response(status_code=404))
    assert results[0]["passed"] is False
    assert results[0]["actual"] == 404


def test_field_exists_validation():
    validations = [{"type": "FIELD_EXISTS", "target": "$.id", "description": "id exists"}]
    results = run_validations(validations, _response(json_body={"id": 1}))
    assert results[0]["passed"] is True

    results = run_validations(validations, _response(json_body={"name": "Fido"}))
    assert results[0]["passed"] is False


def test_field_equals_validation():
    validations = [
        {"type": "FIELD_EQUALS", "target": "$.status", "expected": "available", "description": "status ok"}
    ]
    results = run_validations(validations, _response(json_body={"status": "available"}))
    assert results[0]["passed"] is True

    results = run_validations(validations, _response(json_body={"status": "sold"}))
    assert results[0]["passed"] is False
    assert results[0]["actual"] == "sold"


def test_field_equals_missing_field_fails_not_errors():
    validations = [
        {"type": "FIELD_EQUALS", "target": "$.missing", "expected": "x", "description": "..."}
    ]
    results = run_validations(validations, _response(json_body={}))
    assert results[0]["passed"] is False
    assert results[0]["actual"] is None


def test_unsupported_validation_type_surfaced_not_dropped():
    validations = [{"type": "FIELD_REGEX", "target": "$.x", "description": "unsupported"}]
    results = run_validations(validations, _response(json_body={"x": "y"}))
    assert len(results) == 1
    assert results[0]["passed"] is False
    assert "error" in results[0]


def test_non_json_response_body_does_not_raise():
    response = httpx.Response(
        200, text="plain text", request=httpx.Request("GET", "https://api.example.com/pet")
    )
    validations = [{"type": "FIELD_EXISTS", "target": "$.id", "description": "..."}]
    results = run_validations(validations, response)
    assert results[0]["passed"] is False


# ---------------------------------------------------------------------------
# execute — full flow against a mocked HTTP transport (respx)
# ---------------------------------------------------------------------------


@respx.mock
async def test_execute_passed_outcome():
    respx.get("https://api.example.com/pet/42").mock(
        return_value=httpx.Response(200, json={"id": 42, "name": "Fido"})
    )
    test = _test(
        method="GET",
        path="/pet/{{petId}}",
        validations=[
            {"type": "STATUS_CODE", "expected": 200, "description": "is 200"},
            {"type": "FIELD_EQUALS", "target": "$.name", "expected": "Fido", "description": "name ok"},
        ],
    )
    env = _environment(variables={"petId": "42"})

    outcome = await execute(test, env)

    assert outcome.status == "passed"
    assert outcome.response_snapshot["status_code"] == 200
    assert outcome.response_snapshot["body"] == {"id": 42, "name": "Fido"}
    assert all(v["passed"] for v in outcome.validation_results)
    assert outcome.duration_ms is not None
    assert outcome.error is None


@respx.mock
async def test_execute_failed_outcome_when_validation_fails():
    respx.get("https://api.example.com/pet/42").mock(
        return_value=httpx.Response(200, json={"id": 42, "name": "Rex"})
    )
    test = _test(
        method="GET",
        path="/pet/{{petId}}",
        validations=[
            {"type": "FIELD_EQUALS", "target": "$.name", "expected": "Fido", "description": "name ok"},
        ],
    )
    env = _environment(variables={"petId": "42"})

    outcome = await execute(test, env)

    assert outcome.status == "failed"
    assert outcome.validation_results[0]["passed"] is False


# ---------------------------------------------------------------------------
# Fix B — grounded validations: enforcement drives the verdict, not a flat
# all()
# ---------------------------------------------------------------------------


def test_evaluate_one_defaults_enforcement_to_enforced_when_absent():
    """A validation with no stored `enforcement` (i.e. persisted before
    this feature existed) must be treated as enforced, same as today."""
    validations = [{"type": "STATUS_CODE", "expected": 200, "description": "is 200"}]
    results = run_validations(validations, _response(status_code=200))
    assert results[0]["enforcement"] == "enforced"


def test_evaluate_one_reads_stored_advisory_enforcement():
    validations = [
        {
            "type": "FIELD_EXISTS",
            "target": "$.missing",
            "description": "guess",
            "enforcement": "advisory",
        }
    ]
    results = run_validations(validations, _response(json_body={}))
    assert results[0]["enforcement"] == "advisory"
    assert results[0]["passed"] is False


def test_evaluate_one_forces_advisory_for_unimplemented_type_even_if_stored_enforced():
    """The unimplemented-type override applies live, regardless of what was
    stored — see execution_engine._effective_enforcement."""
    validations = [
        {
            "type": "FIELD_REGEX",
            "target": "$.x",
            "description": "unsupported",
            "enforcement": "enforced",
        }
    ]
    results = run_validations(validations, _response(json_body={"x": "y"}))
    assert results[0]["enforcement"] == "advisory"


@respx.mock
async def test_execute_inconclusive_when_only_advisory_validation_fails():
    """Enforced STATUS_CODE passes; an advisory FIELD_EXISTS fails (field
    genuinely absent from the real response) — the request behaved
    correctly by every check that's trusted, so the verdict is
    'inconclusive', not 'failed'.
    """
    respx.get("https://api.example.com/pet/42").mock(
        return_value=httpx.Response(200, json={"id": 42, "access": "tok-1"})
    )
    test = _test(
        method="GET",
        path="/pet/{{petId}}",
        validations=[
            {"type": "STATUS_CODE", "expected": 200, "description": "is 200"},
            {
                "type": "FIELD_EXISTS",
                "target": "$.token",
                "description": "has a token",
                "enforcement": "advisory",
            },
        ],
    )
    env = _environment(variables={"petId": "42"})

    outcome = await execute(test, env)

    assert outcome.status == "inconclusive"
    # Individual results are still recorded plainly — nothing hidden.
    assert outcome.validation_results[0]["passed"] is True
    assert outcome.validation_results[1]["passed"] is False


@respx.mock
async def test_execute_failed_when_enforced_validation_fails_even_with_passing_advisory():
    respx.get("https://api.example.com/pet/42").mock(
        return_value=httpx.Response(404, json={"id": 42})
    )
    test = _test(
        method="GET",
        path="/pet/{{petId}}",
        validations=[
            {"type": "STATUS_CODE", "expected": 200, "description": "is 200"},
            {
                "type": "FIELD_EXISTS",
                "target": "$.id",
                "description": "has id",
                "enforcement": "advisory",
            },
        ],
    )
    env = _environment(variables={"petId": "42"})

    outcome = await execute(test, env)

    assert outcome.status == "failed"


@respx.mock
async def test_execute_passed_when_unimplemented_type_would_have_failed_before():
    """Demonstrates the accepted behaviour change (item 7): a test carrying
    only an unimplemented validation type (RESPONSE_TIME — always a
    synthetic 'not yet supported' failure) alongside a passing enforced
    STATUS_CODE now reports 'inconclusive' rather than 'failed'.
    """
    respx.get("https://api.example.com/pet/42").mock(
        return_value=httpx.Response(200, json={"id": 42})
    )
    test = _test(
        method="GET",
        path="/pet/{{petId}}",
        validations=[
            {"type": "STATUS_CODE", "expected": 200, "description": "is 200"},
            {"type": "RESPONSE_TIME", "expected": 500, "description": "responds fast"},
        ],
    )
    env = _environment(variables={"petId": "42"})

    outcome = await execute(test, env)

    assert outcome.status == "inconclusive"
    assert outcome.validation_results[1]["enforcement"] == "advisory"


@respx.mock
async def test_execute_error_outcome_on_connection_failure():
    respx.get("https://api.example.com/pet/42").mock(
        side_effect=httpx.ConnectError("connection refused")
    )
    test = _test(method="GET", path="/pet/{{petId}}", validations=[])
    env = _environment(variables={"petId": "42"})

    outcome = await execute(test, env)

    assert outcome.status == "error"
    assert outcome.response_snapshot is None
    assert "ConnectError" in outcome.error
