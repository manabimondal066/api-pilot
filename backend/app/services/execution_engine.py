"""Deterministic test execution engine (PRD §14, Implementation Plan
Module 6/7). No AI involved here — this module only builds an HTTP request
from a Test + Environment, sends it, and evaluates validations against the
real response.

Public functions
----------------
build_request(test, environment) -> RequestPlan
    Resolve method/url/headers/params/body, applying `{{variable}}`
    substitution from the environment's `variables` and environment auth.

run_validations(validations, response) -> list[dict]
    Evaluate each validation against an httpx.Response. Supports
    STATUS_CODE, FIELD_EXISTS, FIELD_EQUALS in V1; any other validation
    type is recorded as a skipped/errored result rather than silently
    dropped, so unsupported validations stay visible.

execute(test, environment) -> ExecutionOutcome
    Runs build_request -> real HTTP call via httpx.AsyncClient (30s
    timeout) -> run_validations, and returns everything needed to persist
    an ExecutionResult. Does not touch the DB — see
    app/services/execution_service.py for persistence.

    Verdict: only a validation's `enforcement` of 'binding' (see
    app/services/validation_enforcement.py) can affect the overall verdict —
    any binding validation failing -> 'failed', otherwise -> 'passed'.
    'informational' validations (an unimplemented type, or a guessed field
    name with no real evidence behind it) still run and their result is
    still recorded, they just can never fail the test on their own.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any

import httpx
from jsonpath_ng.ext import parse as jsonpath_parse
from jsonpath_ng.exceptions import JsonPathParserError

_VARIABLE_RE = re.compile(r"\{\{\s*([a-zA-Z0-9_.]+)\s*\}\}")

_HTTP_TIMEOUT_SECONDS = 30.0


# ---------------------------------------------------------------------------
# {{variable}} substitution
# ---------------------------------------------------------------------------


def _substitute_str(value: str, variables: dict[str, Any]) -> str:
    """Replace every `{{name}}` in *value* with `variables[name]` (stringified).

    A reference to a variable not present in *variables* is left as-is
    (e.g. `{{missing}}` stays literal) rather than raising — an unresolved
    placeholder is far more debuggable in the captured request snapshot
    than a silent empty string or a hard failure.
    """

    def _replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name in variables:
            return str(variables[name])
        return match.group(0)

    return _VARIABLE_RE.sub(_replace, value)


def _substitute(value: Any, variables: dict[str, Any]) -> Any:
    """Recursively apply `{{variable}}` substitution through str/dict/list."""
    if isinstance(value, str):
        return _substitute_str(value, variables)
    if isinstance(value, dict):
        return {k: _substitute(v, variables) for k, v in value.items()}
    if isinstance(value, list):
        return [_substitute(v, variables) for v in value]
    return value


# ---------------------------------------------------------------------------
# Request building
# ---------------------------------------------------------------------------


@dataclass
class RequestPlan:
    method: str
    url: str
    headers: dict[str, str]
    params: dict[str, Any]
    json_body: Any | None


def _set_header(headers: dict[str, str], name: str, value: str) -> None:
    """Set *name* to *value*, replacing any existing entry that matches
    case-insensitively.

    HTTP header names are case-insensitive, but `headers` is a plain
    str-keyed dict — without this, a `default_headers` entry like
    "x-api-key" and an auth-applied "X-API-Key" would coexist as two
    distinct dict keys and both get sent (a stale/duplicate header bug).
    """
    for existing in list(headers):
        if existing.lower() == name.lower():
            del headers[existing]
    headers[name] = value


def _apply_auth(
    headers: dict[str, str], auth_type: str, auth_config: dict[str, Any]
) -> None:
    """Mutate *headers* in place to add the environment's auth.

    Supported auth_type values: 'none', 'bearer', 'api_key', 'basic'.
    Unknown auth_type is treated like 'none' — no header is added, since
    silently guessing at an unrecognized scheme could send credentials in
    the wrong shape.
    """
    if auth_type == "bearer":
        token = auth_config.get("token", "")
        _set_header(headers, "Authorization", f"Bearer {token}")
    elif auth_type == "api_key":
        header_name = auth_config.get("header", "X-API-Key")
        _set_header(headers, header_name, auth_config.get("value", ""))
    elif auth_type == "basic":
        import base64

        username = auth_config.get("username", "")
        password = auth_config.get("password", "")
        raw = f"{username}:{password}".encode()
        _set_header(headers, "Authorization", f"Basic {base64.b64encode(raw).decode()}")


def build_request(
    test: Any, environment: Any, extra_variables: dict[str, Any] | None = None
) -> RequestPlan:
    """Resolve *test* into a concrete HTTP request against *environment*.

    `test` and `environment` are duck-typed (accepts either the ORM model
    or anything with the same attributes) so this stays unit-testable
    without a DB.

    *extra_variables* (e.g. values extracted from an earlier test's
    response during suite execution) take priority over the environment's
    own `variables` on a name collision — see
    app/services/suite_execution_service.py.
    """
    variables = {**(environment.variables or {}), **(extra_variables or {})}

    base_url = environment.base_url.rstrip("/")
    path = _substitute_str(test.path, variables)
    if not path.startswith("/"):
        path = f"/{path}"
    url = f"{base_url}{path}"

    headers: dict[str, str] = dict(environment.default_headers or {})
    headers.update(_substitute(test.headers or {}, variables))
    _apply_auth(headers, environment.auth_type or "none", environment.auth_config or {})

    params = _substitute(test.query_params or {}, variables)
    json_body = _substitute(test.body, variables) if test.body is not None else None

    return RequestPlan(
        method=test.method.upper(),
        url=url,
        headers=headers,
        params=params,
        json_body=json_body,
    )


# ---------------------------------------------------------------------------
# Validations
# ---------------------------------------------------------------------------

_SUPPORTED_VALIDATION_TYPES = {"STATUS_CODE", "FIELD_EXISTS", "FIELD_EQUALS"}


def _effective_enforcement(validation: dict[str, Any]) -> str:
    """The enforcement actually used to decide a test's verdict — the
    internal safety net that stops a guessed field name (or a validation
    type the engine can't even evaluate) from producing a false failure.

    This is the validation's stored `enforcement` (defaulting to 'binding'
    for validations persisted before this classification existed — see
    app.services.validation_enforcement.get_enforcement, kept in sync with
    that same default here rather than imported, to avoid a circular import:
    that module imports _SUPPORTED_VALIDATION_TYPES from this one), UNLESS
    this validation's type isn't implemented below (_SUPPORTED_VALIDATION_TYPES)
    — an unimplemented type's result is a synthetic "not yet supported"
    failure, never a real check, so it can never decide the verdict no
    matter what was stored. This override applies live, to every
    validation regardless of when it was persisted.
    """
    if validation.get("type") not in _SUPPORTED_VALIDATION_TYPES:
        return "informational"
    value = validation.get("enforcement")
    return value if value in ("binding", "informational") else "binding"


def _resolve_jsonpath(response_json: Any, target: str) -> tuple[bool, Any]:
    """Return (found, value) for the first match of JSONPath *target*.

    (found=False, value=None) if the path is malformed, the response body
    isn't JSON, or nothing matched.
    """
    if response_json is None:
        return False, None
    try:
        expr = jsonpath_parse(target)
    except JsonPathParserError:
        return False, None
    matches = expr.find(response_json)
    if not matches:
        return False, None
    return True, matches[0].value


def _evaluate_one(validation: dict[str, Any], response: httpx.Response, response_json: Any) -> dict[str, Any]:
    v_type = validation.get("type")
    result: dict[str, Any] = {
        "id": validation.get("id"),
        "type": v_type,
        "description": validation.get("description"),
        "severity": validation.get("severity", "CRITICAL"),
        "enforcement": _effective_enforcement(validation),
    }

    if v_type == "STATUS_CODE":
        expected = validation.get("expected")
        actual = response.status_code
        result["expected"] = expected
        result["actual"] = actual
        result["passed"] = actual == expected
        return result

    if v_type == "FIELD_EXISTS":
        target = validation.get("target") or ""
        found, value = _resolve_jsonpath(response_json, target)
        result["expected"] = f"field at {target} exists"
        result["actual"] = value if found else None
        result["passed"] = found
        return result

    if v_type == "FIELD_EQUALS":
        target = validation.get("target") or ""
        expected = validation.get("expected")
        found, value = _resolve_jsonpath(response_json, target)
        result["expected"] = expected
        result["actual"] = value if found else None
        result["passed"] = found and value == expected
        return result

    # Unsupported validation type — surfaced, not silently dropped.
    result["expected"] = validation.get("expected")
    result["actual"] = None
    result["passed"] = False
    result["error"] = f"Validation type {v_type!r} is not yet supported by the execution engine"
    return result


def run_validations(
    validations: list[dict[str, Any]], response: httpx.Response
) -> list[dict[str, Any]]:
    """Evaluate every validation against *response*. Never raises — an
    individual validation's own evaluation error is captured in its result
    dict rather than aborting the whole run.
    """
    response_json: Any = None
    try:
        response_json = response.json()
    except ValueError:
        response_json = None

    return [_evaluate_one(v, response, response_json) for v in validations]


# ---------------------------------------------------------------------------
# Extractions
# ---------------------------------------------------------------------------


def extract_variables(
    extractions: list[dict[str, Any]], response_json: Any
) -> dict[str, Any]:
    """Resolve each extraction's JSONPath `source` against *response_json*
    and return the {name: value} map for every one that matched.

    An extraction whose `source` doesn't match anything (malformed path,
    missing field, non-JSON body) is silently omitted rather than raising —
    suite execution treats a missing extraction the same as any other
    unresolved `{{variable}}` reference downstream (left literal).
    """
    extracted: dict[str, Any] = {}
    for item in extractions or []:
        name = item.get("name")
        source = item.get("source")
        if not name or not source:
            continue
        found, value = _resolve_jsonpath(response_json, source)
        if found:
            extracted[name] = value
    return extracted


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


@dataclass
class ExecutionOutcome:
    status: str  # 'passed' | 'failed' | 'error' | 'skipped'
    request_snapshot: dict[str, Any]
    response_snapshot: dict[str, Any] | None = None
    validation_results: list[dict[str, Any]] = field(default_factory=list)
    duration_ms: int | None = None
    error: str | None = None
    extracted_variables: dict[str, Any] = field(default_factory=dict)


def _request_snapshot(plan: RequestPlan) -> dict[str, Any]:
    return {
        "method": plan.method,
        "url": plan.url,
        "headers": plan.headers,
        "params": plan.params,
        "body": plan.json_body,
    }


async def execute(
    test: Any, environment: Any, extra_variables: dict[str, Any] | None = None
) -> ExecutionOutcome:
    """Build the request, send it for real, and evaluate validations.

    Never raises for HTTP-level failures (timeout, connection error, etc.)
    — those become an ExecutionOutcome with status='error' so the caller
    can always persist a result. Only a request-building bug (e.g. an
    exception inside build_request) propagates, since that indicates a
    programming error rather than a runtime condition to record.

    *extra_variables* is forwarded to build_request (see its docstring) —
    used by suite execution to pass values extracted from earlier tests.
    On a successful response, any of *test*'s `extractions` that resolve
    against the response body are returned in `extracted_variables`
    regardless of whether validations passed, so the caller decides
    whether to propagate them.
    """
    plan = build_request(test, environment, extra_variables)
    request_snapshot = _request_snapshot(plan)

    start = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SECONDS) as client:
            response = await client.request(
                plan.method,
                plan.url,
                headers=plan.headers,
                params=plan.params,
                json=plan.json_body,
            )
    except httpx.HTTPError as exc:
        duration_ms = int((time.monotonic() - start) * 1000)
        return ExecutionOutcome(
            status="error",
            request_snapshot=request_snapshot,
            response_snapshot=None,
            validation_results=[],
            duration_ms=duration_ms,
            error=f"{type(exc).__name__}: {exc}",
        )
    duration_ms = int((time.monotonic() - start) * 1000)

    try:
        response_body: Any = response.json()
    except ValueError:
        response_body = response.text

    response_snapshot = {
        "status_code": response.status_code,
        "headers": dict(response.headers),
        "body": response_body,
    }

    validation_results = run_validations(test.validations or [], response)
    binding_results = [v for v in validation_results if v.get("enforcement") == "binding"]
    passed = all(v.get("passed") for v in binding_results)
    status = "passed" if passed else "failed"
    extracted_variables = extract_variables(getattr(test, "extractions", None) or [], response_body)

    return ExecutionOutcome(
        status=status,
        request_snapshot=request_snapshot,
        response_snapshot=response_snapshot,
        validation_results=validation_results,
        duration_ms=duration_ms,
        error=None,
        extracted_variables=extracted_variables,
    )
