"""Unit tests for the Swagger / OpenAPI parser.

Fixture-based tests load the real Petstore specs downloaded from
petstore.swagger.io.  Inline-spec tests use small Python dicts serialised
to JSON bytes — no extra fixture files required.
"""

import json
from pathlib import Path

import pytest

from app.parsers.enums import HttpMethod, ParamLocation, SpecSource
from app.parsers.errors import ParserError
from app.parsers.swagger_parser import parse_swagger

FIXTURES = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Fixture-based tests — Petstore v2 (Swagger 2.0)
# ---------------------------------------------------------------------------


async def test_parses_petstore_v2() -> None:
    """Petstore v2 parses without error and returns sane top-level fields."""
    content = (FIXTURES / "petstore_v2.json").read_bytes()
    spec = await parse_swagger(content, "test/petstore_v2.json", "petstore_v2.json")

    assert spec.source == SpecSource.SWAGGER
    assert "petstore" in spec.title.lower()
    assert len(spec.endpoints) > 0
    assert spec.base_url is not None and len(spec.base_url) > 0

    # At least one endpoint should carry path parameters (e.g. /pet/{petId})
    assert any(len(e.path_params) > 0 for e in spec.endpoints), (
        "Expected at least one endpoint with path params"
    )
    # At least one endpoint should have a body schema (e.g. POST /pet)
    assert any(e.body_schema is not None for e in spec.endpoints), (
        "Expected at least one endpoint with a body schema"
    )


# ---------------------------------------------------------------------------
# Fixture-based tests — Petstore v3 (OpenAPI 3.0)
# ---------------------------------------------------------------------------


async def test_parses_petstore_v3() -> None:
    """Petstore v3 parses without error and returns sane top-level fields."""
    content = (FIXTURES / "petstore_v3.json").read_bytes()
    spec = await parse_swagger(content, "test/petstore_v3.json", "petstore_v3.json")

    assert spec.source == SpecSource.SWAGGER
    assert spec.title  # non-empty string
    assert len(spec.endpoints) > 0
    assert spec.base_url is not None

    assert any(len(e.path_params) > 0 for e in spec.endpoints), (
        "Expected at least one endpoint with path params"
    )
    assert any(e.body_schema is not None for e in spec.endpoints), (
        "Expected at least one endpoint with a body schema"
    )


# ---------------------------------------------------------------------------
# Parameter bucketing
# ---------------------------------------------------------------------------


async def test_extracts_query_and_path_params_separately() -> None:
    """Parameters must be bucketed by their 'in' field, not mixed together."""
    content = (FIXTURES / "petstore_v2.json").read_bytes()
    spec = await parse_swagger(content, "test/petstore_v2.json")

    # GET /pet/findByStatus — should have query params, no path params
    find_status = next(
        (
            e
            for e in spec.endpoints
            if e.path == "/pet/findByStatus" and e.method == HttpMethod.GET
        ),
        None,
    )
    assert find_status is not None, "GET /pet/findByStatus not found in parsed endpoints"
    assert len(find_status.query_params) > 0, "Expected query params on findByStatus"
    assert all(
        p.location == ParamLocation.QUERY for p in find_status.query_params
    ), "All query_params must have location=QUERY"

    # GET /pet/{petId} — should have path params
    get_by_id = next(
        (
            e
            for e in spec.endpoints
            if e.path == "/pet/{petId}" and e.method == HttpMethod.GET
        ),
        None,
    )
    assert get_by_id is not None, "GET /pet/{petId} not found in parsed endpoints"
    assert len(get_by_id.path_params) > 0, "Expected path params on /pet/{petId}"
    assert all(
        p.location == ParamLocation.PATH for p in get_by_id.path_params
    ), "All path_params must have location=PATH"


# ---------------------------------------------------------------------------
# Method normalisation
# ---------------------------------------------------------------------------


async def test_method_is_uppercase() -> None:
    """Every parsed endpoint must carry an HttpMethod enum with an uppercase value."""
    content = (FIXTURES / "petstore_v2.json").read_bytes()
    spec = await parse_swagger(content, "test/petstore_v2.json")

    for endpoint in spec.endpoints:
        assert isinstance(endpoint.method, HttpMethod), (
            f"Expected HttpMethod, got {type(endpoint.method)}"
        )
        assert endpoint.method.value == endpoint.method.value.upper(), (
            f"Method value not uppercase: {endpoint.method.value!r}"
        )


# ---------------------------------------------------------------------------
# Response schema keys
# ---------------------------------------------------------------------------


async def test_response_schemas_keyed_by_int() -> None:
    """Response schema dict keys must be Python ints, not strings."""
    content = (FIXTURES / "petstore_v2.json").read_bytes()
    spec = await parse_swagger(content, "test/petstore_v2.json")

    endpoints_with_responses = [e for e in spec.endpoints if e.response_schemas]
    assert len(endpoints_with_responses) > 0, "Expected endpoints with response schemas"

    for ep in endpoints_with_responses:
        for key in ep.response_schemas:
            assert isinstance(key, int), (
                f"Response schema key {key!r} on {ep.method} {ep.path} is not int"
            )


# ---------------------------------------------------------------------------
# Inline-spec tests (no additional fixture files)
# ---------------------------------------------------------------------------


async def test_invalid_json_yaml_raises() -> None:
    """Unparseable bytes must raise ParserError."""
    with pytest.raises(ParserError):
        await parse_swagger(b"not valid {{{}", "fake/key.json")


async def test_empty_paths_succeeds() -> None:
    """A valid spec with an empty paths object should parse to 0 endpoints."""
    spec_dict = {
        "openapi": "3.0.0",
        "info": {"title": "Empty Spec", "version": "0.0.1"},
        "paths": {},
    }
    content = json.dumps(spec_dict).encode()
    spec = await parse_swagger(content, "test/empty.json")

    assert spec.title == "Empty Spec"
    assert spec.endpoints == []


async def test_unknown_method_skipped() -> None:
    """Operations with unsupported HTTP methods (TRACE, OPTIONS…) are silently skipped."""
    spec_dict = {
        "openapi": "3.0.0",
        "info": {"title": "Method Test", "version": "1.0.0"},
        "paths": {
            "/test": {
                "get": {
                    "operationId": "getTest",
                    "responses": {"200": {"description": "OK"}},
                },
                "trace": {
                    "operationId": "traceTest",
                    "responses": {"200": {"description": "OK"}},
                },
            }
        },
    }
    content = json.dumps(spec_dict).encode()
    spec = await parse_swagger(content, "test/method_test.json")

    names = [e.name for e in spec.endpoints]
    assert "getTest" in names, "GET operation should be present"
    assert "traceTest" not in names, "TRACE operation should be silently skipped"
