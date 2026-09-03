"""Prompt templates for test case generation.

These prompts are the *most important* code in V1. Treat them like product code.
Versioned via PROMPT_VERSION constant — bump when materially changed.
"""

import json

from app.parsers.models import ParsedEndpoint

PROMPT_VERSION = "2b.3"


SYSTEM_PROMPT = """You are an expert API test designer. Your job is to generate \
comprehensive, high-quality test cases for a single HTTP API endpoint, given its \
OpenAPI/Swagger specification.

You MUST produce a JSON object matching the requested schema exactly. Do not include \
any prose outside the JSON.

Coverage requirements:
- At least 1 POSITIVE test (happy path, valid input)
- At least 1 NEGATIVE test (missing required fields, wrong types, invalid values, \
unauthorized when auth required, malformed inputs)
- At least 1 EDGE test (boundary values, empty strings/arrays, maximum lengths, \
special characters, null where allowed)

Validation requirements for EACH test (no exceptions):
- Always include exactly one STATUS_CODE validation
- For POSITIVE tests with a documented success response schema: include at least \
one SCHEMA_MATCH and at least one FIELD_EXISTS on a known response field
- For NEGATIVE and EDGE tests: include at least 2 validations total. The second \
validation should check the error response body — use FIELD_EXISTS on a likely error \
field (e.g. $.message, $.error, $.detail, $.errors) with severity=WARNING since the \
exact error shape may not be documented
- For tests touching numeric fields: add a FIELD_TYPE or FIELD_RANGE validation when \
the schema defines bounds
- Use Severity=CRITICAL for status code and schema validations
- Use Severity=WARNING for field checks where the spec doesn't guarantee shape

If the spec only documents 2xx responses, your NEGATIVE tests should still use \
plausible error codes (400 for malformed input, 401/403 for auth failures, 404 for \
missing resources, 409 for conflicts). State this assumption in `ai_notes` for that \
test.

Use JSONPath syntax for `target` fields: $.user.id, $.items[0].name, etc.

For path parameters, use {paramName} placeholders in `path`. For values you cannot \
know in advance (IDs from other endpoints), use {{variableName}} double-brace syntax.

Differentiate POSITIVE tests from each other. Don't generate two tests with the same \
validations and only minor input differences — vary what you're verifying across \
tests (different fields, different success conditions, different valid combinations).

Rate confidence honestly and with spread:
- 0.90+ only when the spec is unambiguous AND the test reflects documented behavior \
exactly
- 0.70-0.85 for plausible tests where you inferred details (e.g. error codes not in \
the spec, validation thresholds not specified)
- 0.50-0.70 for tests where you're making educated guesses
Do not return the same confidence value for every test. If you find yourself doing \
that, you are not calibrating — go back and adjust.

Generate between 3 and 5 tests total, prioritizing coverage (at least one \
POSITIVE, one NEGATIVE, and one EDGE test) over quantity."""


USER_PROMPT_TEMPLATE = """Generate test cases for this endpoint.

Endpoint:
  Method:      {method}
  Path:        {path}
  Name:        {name}
  Description: {description}

Path parameters:
{path_params}

Query parameters:
{query_params}

Headers:
{headers}

Request body schema (JSON Schema):
{body_schema}

Response schemas (by status code, JSON Schema):
{response_schemas}

Authentication:
{auth}

Tags: {tags}

Return a JSON object with a "tests" array. Each test must conform to the TestCase \
schema you have been instructed to use."""


def _format_param_list(params: list) -> str:
    if not params:
        return "  (none)"
    lines = []
    for p in params:
        required = "required" if p.required else "optional"
        schema_snippet = json.dumps(p.schema_) if p.schema_ else "no schema"
        desc = f" — {p.description}" if p.description else ""
        lines.append(f"  - {p.name} ({required}): {schema_snippet}{desc}")
    return "\n".join(lines)


def _format_headers(headers: list) -> str:
    if not headers:
        return "  (none required)"
    return _format_param_list(headers)


def _format_body_schema(schema: dict | None) -> str:
    if not schema:
        return "  (no request body)"
    return json.dumps(schema, indent=2)


def _format_response_schemas(schemas: dict[int, dict]) -> str:
    if not schemas:
        return "  (no response schemas documented)"
    parts = []
    for status, schema in sorted(schemas.items()):
        parts.append(f"  {status}: {json.dumps(schema, indent=2)}")
    return "\n".join(parts)


def _format_auth(auth) -> str:
    if not auth:
        return "  (none)"
    return f"  type={auth.type.value} name={auth.name or ''} scheme={auth.scheme or ''}"


def build_user_prompt(endpoint: ParsedEndpoint) -> str:
    """Render the user-side prompt for a single endpoint."""
    return USER_PROMPT_TEMPLATE.format(
        method=endpoint.method.value,
        path=endpoint.path,
        name=endpoint.name,
        description=endpoint.description or "(no description)",
        path_params=_format_param_list(endpoint.path_params),
        query_params=_format_param_list(endpoint.query_params),
        headers=_format_headers(endpoint.headers),
        body_schema=_format_body_schema(endpoint.body_schema),
        response_schemas=_format_response_schemas(endpoint.response_schemas),
        auth=_format_auth(endpoint.auth),
        tags=", ".join(endpoint.tags) if endpoint.tags else "(none)",
    )
