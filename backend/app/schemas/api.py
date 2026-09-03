"""Public API contract schemas.

These models form the HTTP-level contract between the frontend and the backend.
They are deliberately separate from the internal parser models in
``app.parsers.models`` — callers must not be coupled to internal
implementation details.

Naming conventions
------------------
*In   — request bodies accepted by POST/PUT endpoints
*Out  — response bodies returned to callers
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, computed_field, field_validator


# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------


class ImportFromUrlIn(BaseModel):
    """Request body for POST /api/imports/url."""

    url: HttpUrl


class ImportFromCurlIn(BaseModel):
    """Request body for POST /api/imports/curl."""

    curl_text: str = Field(min_length=1)
    suite_name: str | None = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


class EndpointOut(BaseModel):
    """Endpoint summary — included inside SuiteDetailOut.

    The full ``schema`` JSONB blob is intentionally omitted here; it will be
    surfaced via GET /api/endpoints/{id} (Sprint 1d) when the frontend
    needs schema-heavy views.
    """

    id: UUID
    method: str
    path: str
    name: str
    description: str | None

    model_config = ConfigDict(from_attributes=True)


class EndpointDetailOut(EndpointOut):
    """Full endpoint detail — includes the parsed schema blob.

    Used by GET /api/endpoints/{id} (Sprint 1d).
    ``validation_alias`` maps the ORM attribute ``endpoint_schema`` to the
    Python field ``schema_`` which is serialised as ``"schema"`` in JSON.
    """

    schema_: dict = Field(
        alias="schema",
        validation_alias="endpoint_schema",  # ORM Python attribute name
    )

    model_config = ConfigDict(
        from_attributes=True,
        populate_by_name=True,
    )


# ---------------------------------------------------------------------------
# Suites
# ---------------------------------------------------------------------------


class SuiteSummaryOut(BaseModel):
    """Suite list-view item — no endpoint list, includes a count instead."""

    id: UUID
    name: str
    spec_id: UUID
    generation_status: str
    endpoint_count: int         # dynamically set by suite_service.list_suites
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SuiteDetailOut(BaseModel):
    """Suite detail view — includes endpoint summaries (no full schema)."""

    id: UUID
    name: str
    spec_id: UUID
    generation_status: str
    # Auto-assigned for cURL imports (app/services/import_service.py); null
    # for Swagger/Postman imports, which require manual environment setup.
    environment_id: UUID | None = None
    endpoints: list[EndpointOut]
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Environments
# ---------------------------------------------------------------------------


class EnvironmentIn(BaseModel):
    """Request body for POST /api/environments."""

    name: str = Field(min_length=1)
    base_url: HttpUrl
    auth_type: str = "none"
    auth_config: dict[str, Any] = Field(default_factory=dict)
    default_headers: dict[str, str] = Field(default_factory=dict)
    variables: dict[str, Any] = Field(default_factory=dict)


class EnvironmentUpdateIn(BaseModel):
    """Request body for PATCH /api/environments/{id}. All fields optional."""

    name: str | None = Field(default=None, min_length=1)
    base_url: HttpUrl | None = None
    auth_type: str | None = None
    auth_config: dict[str, Any] | None = None
    default_headers: dict[str, str] | None = None
    variables: dict[str, Any] | None = None


class EnvironmentOut(BaseModel):
    """Environment response body.

    auth_config is returned as-is (plain text in V1 — see
    app/models/environment.py). Callers responsible for the UI layer are
    expected to mask secret-looking values before display (PRD §32.1); the
    API itself does not redact them.

    is_incomplete is computed (not persisted) — currently true whenever
    auth_type is "none", which is the case that matters for cURL-imported
    environments that had no Authorization header to draw from (PRD-adjacent
    UX addition, not stored on the model).
    """

    id: UUID
    workspace_id: UUID
    name: str
    base_url: str
    auth_type: str
    auth_config: dict[str, Any]
    default_headers: dict[str, str]
    variables: dict[str, Any]
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_incomplete(self) -> bool:
        return self.auth_type == "none"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class GenerateTestsIn(BaseModel):
    """Request body for POST /api/endpoints/{id}/generate-tests. Entirely
    optional — a request with no body (today's behaviour) is equivalent to
    every field at its default, i.e. no probing.

    use_probe: opt-in to probe-grounded generation (Phase B) for this call.
    Has no effect unless the server-side ENABLE_PROBE_GENERATION setting is
    also on — both must be true for a probe to happen.
    environment_id: which environment to resolve/send the probe request
    against. Required (functionally) for use_probe to do anything; a probe
    silently skips if this is absent.
    """

    use_probe: bool = False
    environment_id: UUID | None = None


class TestOut(BaseModel):
    """A single AI-generated (or user-authored) test case.

    Mirrors the Test ORM model (app/models/test.py), which in turn mirrors
    the TestCase Pydantic schema in app/ai/schemas/test_case.py (Implementation
    Plan §7.2). validations/extractions/depends_on are passed through as
    plain JSON — callers that need typed access should use the AI-layer
    schemas directly.
    """

    id: UUID
    suite_id: UUID
    endpoint_id: UUID
    name: str
    category: str
    method: str
    path: str
    headers: dict[str, str]
    query_params: dict[str, Any]
    body: Any | None
    validations: list[dict[str, Any]]
    extractions: list[dict[str, Any]]
    depends_on: list[str]
    confidence: float
    ai_notes: str | None
    created_by: str
    version: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Executions
# ---------------------------------------------------------------------------


class AddValidationIn(BaseModel):
    """Request body for POST /api/tests/{id}/validations.

    ``validation`` mirrors app.ai.schemas.test_case.Validation (type,
    description, target, expected, severity) — validated against that
    schema in the service layer, not here, so both the HTTP route and the
    chat agent's add_validation tool share one validation path.
    """

    validation: dict[str, Any]


class UpdateTestBodyIn(BaseModel):
    """Request body for PUT /api/tests/{id}/body."""

    body: Any = None


class ExecuteTestIn(BaseModel):
    """Request body for POST /api/tests/{id}/execute."""

    environment_id: UUID


class ExecuteSuiteIn(BaseModel):
    """Request body for POST /api/suites/{id}/execute."""

    environment_id: UUID


class ExecutionResultOut(BaseModel):
    """A single test run's outcome: request sent, response received, and
    per-validation pass/fail (app/models/execution.py).
    """

    id: UUID
    execution_id: UUID
    test_id: UUID
    status: str
    request_snapshot: dict[str, Any]
    response_snapshot: dict[str, Any] | None
    validation_results: list[dict[str, Any]]
    duration_ms: int | None
    error: str | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ExecutionOut(BaseModel):
    """A test execution against an environment, with its result(s).

    test_name / environment_name are plain Python attributes set
    dynamically by execution_service (not mapped columns on Execution) —
    same pattern as SuiteSummaryOut.endpoint_count in suite_service. Lets
    the history list show human-readable names without the frontend
    fetching the test and environment separately for every row.
    """

    id: UUID
    test_id: UUID
    test_name: str
    environment_id: UUID
    environment_name: str
    status: str
    started_at: datetime
    finished_at: datetime | None
    results: list[ExecutionResultOut] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------


class DependencyOut(BaseModel):
    """A single 'test_id depends on depends_on_test_id' edge
    (app/models/dependency.py)."""

    id: UUID
    test_id: UUID
    depends_on_test_id: UUID
    source: str
    reason: str | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DependencyIn(BaseModel):
    """Request body for POST /api/suites/{id}/dependencies — a manual
    'user'-sourced override (PRD §12.4)."""

    test_id: UUID
    depends_on_test_id: UUID


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------


class ChatIn(BaseModel):
    """Request body for POST /api/chat.

    max_length is a coarse abuse guard (an enormous message burns tokens/cost
    and can blow past a provider's context window) — well above any real
    chat message, so it never gets in a legitimate user's way.
    """

    suite_id: UUID
    message: str = Field(min_length=1, max_length=8000)

    @field_validator("message")
    @classmethod
    def _message_not_blank(cls, v: str) -> str:
        # min_length counts raw characters, so a whitespace-only string
        # (" ") would otherwise pass — strip first so blank input is
        # rejected the same way empty input is.
        stripped = v.strip()
        if not stripped:
            raise ValueError("message must not be blank")
        return v


class ChatToolCallOut(BaseModel):
    """One tool call the agent made, for the frontend to show plainly what
    happened rather than a vague "done" (Implementation Plan Module 9)."""

    tool: str
    arguments: dict[str, Any]
    result: str
    error: str | None = None


class ChatOut(BaseModel):
    """Response body for POST /api/chat."""

    reply: str
    tool_calls: list[ChatToolCallOut]
    changes: list[ChatToolCallOut]


class ChatMessageOut(BaseModel):
    """One persisted message, for GET /api/chat/{suite_id}/history."""

    id: UUID
    role: str
    content: str
    tool_calls: list[dict[str, Any]] | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
