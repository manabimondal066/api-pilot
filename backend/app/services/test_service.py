"""Test generation & query service.

Public functions
----------------
generate_tests_for_endpoint(db, endpoint_id, workspace_id, use_probe=False, environment_id=None) -> list[Test]
    Calls AIOrchestrationService synchronously and persists the result.
    When ENABLE_PROBE_GENERATION is on, use_probe is True, and the
    endpoint's suite was imported from cURL, replays the endpoint's stored
    example request once first (app.services.probe_service) and grounds
    generation in the real observed response — see Phase B in the project
    brief. Any probe failure or a non-cURL source falls through silently
    to today's ungrounded generation.

get_test(db, test_id, workspace_id) -> Test
    Single test, raises TestNotFoundError if absent.

list_tests_for_endpoint(db, endpoint_id, workspace_id) -> list[Test]
    All tests generated for one endpoint, newest first.

add_validation(db, test_id, workspace_id, validation) -> Test
    Appends one validation to a test's validations list. This is the single
    write path for adding a validation — both PATCH /api/tests/{id}/validations
    and the chat agent's add_validation tool call this, not a shortcut.

remove_validation(db, test_id, workspace_id, validation_id) -> Test
    Removes one validation from a test by its id. Raises ValidationNotFoundError
    if no entry matches.

update_test_body(db, test_id, workspace_id, body) -> Test
    Replaces a test's request body wholesale (e.g. fixing a duplicate id
    or an otherwise invalid payload). Same shared write path as the
    validations functions above — PATCH /api/tests/{id}/body and the chat
    agent's update_test_body tool both call this, not a shortcut.

Synchronous by design
----------------------
generate_tests_for_endpoint calls the LLM provider directly on the request
path and blocks until it responds. Free-tier NIM has ~20s of connection/
queue overhead before generation even starts, so a real call can take
anywhere from ~25s to a minute or two — bounded by the provider's 120s
per-attempt timeout times AIOrchestrationService's own retry count. There
is no job queue here — Redis/arq-backed async generation is deferred to
Sprint 9 per the Implementation Plan (Module 12). Do not add a queue,
background task, or polling endpoint for this; the synchronous call is the
intended V1 behaviour, not a placeholder for one.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.providers.base import LLMProviderError
from app.ai.providers.errors import classify_provider_error, strip_reset_marker
from app.ai.providers.factory import get_llm_provider
from app.ai.schemas.test_case import Validation
from app.ai.service import AIOrchestrationError, AIOrchestrationService
from app.config import get_settings
from app.models.endpoint import Endpoint
from app.models.spec import Spec
from app.models.suite import Suite
from app.models.test import Test
from app.parsers.enums import SpecSource
from app.parsers.models import ParsedEndpoint
from app.services import (
    EndpointNotFoundError,
    TestGenerationError,
    TestNotFoundError,
    ValidationNotFoundError,
)
from app.services import probe_service
from app.services.validation_enforcement import BINDING, classify_enforcement

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _classify_generation_error(exc: Exception) -> str:
    """Map an AI-layer exception to a short reason code.

    The reason code itself is not shown to the user — the frontend shows
    the raw provider error text (TestGenerationError.message, minus the
    internal reset marker — see strip_reset_marker) unmodified. `reason` is
    kept for internal use: logging, and reason == "quota_exhausted" gating
    whether `reset_at`/`provider` are meaningful.

    Thin wrapper around the shared classifier (app.ai.providers.errors) —
    kept as a public, string-returning function since it's the tested
    contract other modules import; use classify_provider_error directly
    when the reset_at is needed too (see generate_tests_for_endpoint below).
    """
    return classify_provider_error(exc).reason


def _dump_generated_validation(validation: Validation) -> dict[str, Any]:
    """Dump one AI-generated Validation to JSON and stamp its deterministic
    `enforcement` (app.services.validation_enforcement.classify_enforcement)
    — the internal safety net that keeps a guessed field name from ever
    failing a test on its own. Only used for AI-generated validations; a
    user/chat-added validation always stamps 'binding' directly (see
    add_validation below) — the classifier never runs on those, because a
    check someone explicitly asked for must always count.
    """
    dumped = validation.model_dump(mode="json")
    dumped["enforcement"] = classify_enforcement(dumped)
    return dumped


async def _load_endpoint(
    db: AsyncSession, endpoint_id: UUID, workspace_id: UUID
) -> Endpoint:
    """Load an Endpoint, scoped to *workspace_id* via its parent Suite."""
    result = await db.execute(
        select(Endpoint)
        .join(Suite, Endpoint.suite_id == Suite.id)
        .where(Endpoint.id == endpoint_id, Suite.workspace_id == workspace_id)
    )
    endpoint = result.scalar_one_or_none()
    if endpoint is None:
        raise EndpointNotFoundError(
            f"Endpoint {endpoint_id} not found in workspace {workspace_id}"
        )
    return endpoint


async def _get_spec_source(db: AsyncSession, suite_id: UUID) -> str | None:
    """The Spec.source ('SWAGGER' | 'POSTMAN' | 'CURL') for *suite_id*'s
    parent spec — used to gate probe-grounded generation (Phase B) to
    cURL-imported suites only, since a Swagger/Postman endpoint's stored
    `body_schema` is a JSON Schema fragment, not real example data;
    replaying it verbatim would send nonsense.
    """
    result = await db.execute(
        select(Spec.source).join(Suite, Suite.spec_id == Spec.id).where(Suite.id == suite_id)
    )
    return result.scalar_one_or_none()


async def _probe_for_generation(
    db: AsyncSession,
    endpoint: Endpoint,
    workspace_id: UUID,
    use_probe: bool,
    environment_id: UUID | None,
) -> tuple[int | None, str | None]:
    """Decide whether to probe (Phase B gating: flag + use_probe + cURL
    source) and, if so, attempt it. Returns (observed_status, observed_body)
    — both None when probing is off, not requested, the source isn't
    cURL, or the probe itself failed. Never raises: a probe is entirely
    best-effort (see app.services.probe_service.probe_endpoint).
    """
    if not (get_settings().enable_probe_generation and use_probe):
        return None, None

    spec_source = await _get_spec_source(db, endpoint.suite_id)
    if spec_source != SpecSource.CURL.value:
        logger.warning(
            "generate_tests_for_endpoint: endpoint=%s use_probe=True but suite spec "
            "source is %r, not CURL — skipping probe",
            endpoint.id,
            spec_source,
        )
        return None, None

    result = await probe_service.probe_endpoint(db, endpoint, environment_id, workspace_id)
    if result is None:
        return None, None
    return result.status_code, result.body_text


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def generate_tests_for_endpoint(
    db: AsyncSession,
    endpoint_id: UUID,
    workspace_id: UUID,
    use_probe: bool = False,
    environment_id: UUID | None = None,
) -> list[Test]:
    """Generate test cases for *endpoint_id* and persist them as Test rows.

    This is a synchronous, request-blocking call to the configured LLM
    provider (see module docstring) — there is no async job queue in V1.

    *use_probe*/*environment_id* (Phase B — probe-grounded generation):
    both default to off/None, matching today's behaviour exactly. Probing
    only happens when settings.enable_probe_generation is also on (default
    False) — see _probe_for_generation.

    Raises:
        EndpointNotFoundError: if the endpoint doesn't exist in the workspace.
        TestGenerationError: if the AI orchestration layer fails after retries.
    """
    endpoint = await _load_endpoint(db, endpoint_id, workspace_id)
    parsed_endpoint = ParsedEndpoint.model_validate(endpoint.endpoint_schema)

    observed_status, observed_body = await _probe_for_generation(
        db, endpoint, workspace_id, use_probe, environment_id
    )

    try:
        service = AIOrchestrationService()
        generated = await service.generate_tests(
            parsed_endpoint,
            endpoint_id=str(endpoint.id),
            observed_status=observed_status,
            observed_body=observed_body,
        )
    except (AIOrchestrationError, LLMProviderError) as exc:
        info = classify_provider_error(exc)
        try:
            # Best-effort — if the provider itself failed to construct (e.g.
            # a missing API key, the failure being handled right now), this
            # raises the same LLMProviderError again; provider name is just
            # not available to report in that case.
            provider_name = get_llm_provider().get_model_info().provider
        except LLMProviderError:
            provider_name = None
        raise TestGenerationError(
            f"Test generation failed for endpoint {endpoint_id}: {strip_reset_marker(str(exc))}",
            reason=info.reason,
            reset_at=info.reset_at,
            provider=provider_name,
        ) from exc

    rows = [
        Test(
            suite_id=endpoint.suite_id,
            endpoint_id=endpoint.id,
            name=t.name,
            category=t.category.value,
            method=t.method.value,
            path=t.path,
            headers=t.headers,
            query_params=t.query_params,
            body=t.body,
            validations=[_dump_generated_validation(v) for v in t.validations],
            extractions=[e.model_dump(mode="json") for e in t.extractions],
            depends_on=t.depends_on,
            confidence=t.confidence,
            ai_notes=t.ai_notes,
            created_by="ai",
        )
        for t in generated
    ]
    db.add_all(rows)
    await db.commit()
    for row in rows:
        await db.refresh(row)
    return rows


async def get_test(db: AsyncSession, test_id: UUID, workspace_id: UUID) -> Test:
    """Return a single test, scoped to *workspace_id* via its parent Suite.

    Raises:
        TestNotFoundError: if no matching test exists in the workspace.
    """
    result = await db.execute(
        select(Test)
        .join(Suite, Test.suite_id == Suite.id)
        .where(Test.id == test_id, Suite.workspace_id == workspace_id)
    )
    test = result.scalar_one_or_none()
    if test is None:
        raise TestNotFoundError(f"Test {test_id} not found in workspace {workspace_id}")
    return test


async def list_tests_for_endpoint(
    db: AsyncSession,
    endpoint_id: UUID,
    workspace_id: UUID,
) -> list[Test]:
    """Return all tests generated for *endpoint_id*, newest first.

    Raises:
        EndpointNotFoundError: if the endpoint doesn't exist in the workspace.
    """
    await _load_endpoint(db, endpoint_id, workspace_id)  # tenant-isolation check

    result = await db.execute(
        select(Test)
        .where(Test.endpoint_id == endpoint_id)
        .order_by(Test.created_at.desc())
    )
    return list(result.scalars().all())


async def add_validation(
    db: AsyncSession,
    test_id: UUID,
    workspace_id: UUID,
    validation: dict,
) -> Test:
    """Append one validation to *test_id*'s validations list.

    *validation* is validated against the Validation schema (app/ai/schemas/
    test_case.py) before being persisted — malformed input from the caller
    (including the chat agent) never reaches the JSONB column as-is.

    Always stamped `enforcement='binding'` — a check the user (or the chat
    assistant on the user's behalf) explicitly asked for must always be
    able to count, regardless of its type or grounding. The classifier
    (app.services.validation_enforcement.classify_enforcement) only runs
    on AI-generated validations, never here.

    Raises:
        TestNotFoundError: if the test doesn't exist in the workspace.
    """
    test = await get_test(db, test_id, workspace_id)
    validated = Validation.model_validate(validation)
    dumped = validated.model_dump(mode="json")
    dumped["enforcement"] = BINDING
    test.validations = [*(test.validations or []), dumped]
    test.version += 1
    await db.commit()
    await db.refresh(test)
    return test


async def remove_validation(
    db: AsyncSession,
    test_id: UUID,
    workspace_id: UUID,
    validation_id: str,
) -> Test:
    """Remove one validation from *test_id* by its id.

    Raises:
        TestNotFoundError: if the test doesn't exist in the workspace.
        ValidationNotFoundError: if no validation with that id exists on the test.
    """
    test = await get_test(db, test_id, workspace_id)
    remaining = [v for v in (test.validations or []) if v.get("id") != validation_id]
    if len(remaining) == len(test.validations or []):
        raise ValidationNotFoundError(
            f"Validation {validation_id} not found on test {test_id}"
        )
    test.validations = remaining
    test.version += 1
    await db.commit()
    await db.refresh(test)
    return test


async def update_test_body(
    db: AsyncSession,
    test_id: UUID,
    workspace_id: UUID,
    body: Any,
) -> Test:
    """Replace *test_id*'s request body wholesale.

    No schema validation is imposed on *body* beyond being JSON-serialisable
    — unlike validations, a test body's shape is endpoint-specific (whatever
    the API under test expects), so there is no fixed Pydantic schema for
    it to conform to, same as the body field on the Test model itself.

    Raises:
        TestNotFoundError: if the test doesn't exist in the workspace.
    """
    test = await get_test(db, test_id, workspace_id)
    test.body = body
    test.version += 1
    await db.commit()
    await db.refresh(test)
    return test
