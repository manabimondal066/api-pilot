"""Probe-grounded generation — replay a cURL-imported endpoint's stored
example request once, for real, before AI test generation, so body-level
validations can be grounded in an actually-observed response instead of a
guess.

Public entry point
-------------------
probe_endpoint(db, endpoint, environment_id, workspace_id) -> ProbeResult | None
    Best-effort. Returns None on ANY failure — network error, timeout,
    non-JSON body, missing/unresolvable environment, or anything else.
    A probe failure must never fail generation; the caller (test_service)
    falls through to today's ungrounded generation exactly as if this
    function had never been called.

Safety
------
- Exactly one request. No retry, no loop.
- 10 second hard timeout (imposed here via asyncio.wait_for — the
  execution engine's own internal HTTP timeout is untouched, per the
  constraint not to modify its request-sending code).
- Never creates an Execution/ExecutionResult row: this calls
  execution_engine.execute() directly and never touches
  execution_service.record_execution, so a probe cannot appear in History
  or affect its count.
- The observed response is never logged — only its status code and a
  truncated preview are captured for the prompt, kept in memory only for
  the duration of one generate_tests_for_endpoint call, never persisted.

Reuses app/services/execution_engine.py's request builder and HTTP call
as-is (build_request / execute) — this module does not duplicate or modify
that request-sending code.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.endpoint import Endpoint
from app.services import EnvironmentNotFoundError
from app.services import environment_service
from app.services.execution_engine import execute as run_execution

logger = logging.getLogger(__name__)

_PROBE_TIMEOUT_SECONDS = 10.0
_BODY_TRUNCATE_CHARS = 4000


@dataclass
class ProbeResult:
    status_code: int
    body_text: str


def _build_probe_request(endpoint: Endpoint) -> Any:
    """Reconstruct the endpoint's stored cURL example request as a
    duck-typed object matching what execution_engine.build_request expects
    (method/path/headers/query_params/body/validations) — same shape as
    the SimpleNamespace test doubles in tests/test_execution_engine.py.

    For a cURL-imported endpoint, `endpoint.endpoint_schema` (a dumped
    ParsedEndpoint) holds the real example values: `path` is already
    concrete (no {placeholders}), header/query params carry their real
    value in `.example`, and `body_schema` is the literal parsed request
    body (not a JSON Schema — that's only true for cURL sources, which is
    exactly what the caller gates on before calling this).
    """
    schema = endpoint.endpoint_schema or {}
    headers = {
        h["name"]: str(h["example"])
        for h in schema.get("headers", [])
        if h.get("example") is not None
    }
    query_params = {
        q["name"]: q["example"]
        for q in schema.get("query_params", [])
        if q.get("example") is not None
    }
    return SimpleNamespace(
        method=endpoint.method,
        path=endpoint.path,
        headers=headers,
        query_params=query_params,
        body=schema.get("body_schema"),
        validations=[],
    )


def _truncate_body(body: Any) -> str:
    """Render *body* as text for the prompt, capped at roughly 4000
    characters. Prefers preserving JSON key structure over values when the
    body is a JSON object — truncating a raw json.dumps string can cut off
    inside a key name; instead, drop the deepest values first isn't
    practical here, so this keeps it simple and safe: serialize, then
    truncate the text, which is what the brief describes as "about 4000
    characters" (not an exact structural guarantee).
    """
    if body is None:
        text = ""
    elif isinstance(body, str):
        text = body
    else:
        try:
            text = json.dumps(body)
        except (TypeError, ValueError):
            text = str(body)
    if len(text) > _BODY_TRUNCATE_CHARS:
        text = text[:_BODY_TRUNCATE_CHARS] + "...(truncated)"
    return text


async def probe_endpoint(
    db: AsyncSession,
    endpoint: Endpoint,
    environment_id: UUID | None,
    workspace_id: UUID,
) -> ProbeResult | None:
    """Replay *endpoint*'s stored example request once against
    *environment_id* and capture the real response. Returns None on any
    failure — see module docstring. Never raises.
    """
    if environment_id is None:
        logger.warning(
            "probe_endpoint: no environment_id supplied for endpoint %s, skipping probe",
            endpoint.id,
        )
        return None

    try:
        environment = await environment_service.get_environment(
            db, environment_id, workspace_id
        )
    except EnvironmentNotFoundError:
        logger.warning(
            "probe_endpoint: environment %s not found, skipping probe", environment_id
        )
        return None

    probe_request = _build_probe_request(endpoint)

    try:
        outcome = await asyncio.wait_for(
            run_execution(probe_request, environment),
            timeout=_PROBE_TIMEOUT_SECONDS,
        )
    except Exception as exc:  # noqa: BLE001 — any failure must fall through silently
        logger.warning(
            "probe_endpoint: probe failed for endpoint %s (%s), skipping",
            endpoint.id,
            type(exc).__name__,
        )
        return None

    if outcome.response_snapshot is None:
        # outcome.status == "error" — request-level failure (connection
        # refused, DNS, timeout inside the engine's own 30s cap, etc.);
        # outcome.error holds the detail but is intentionally not logged
        # here (may echo back request/response content).
        logger.warning(
            "probe_endpoint: no response captured for endpoint %s, skipping", endpoint.id
        )
        return None

    return ProbeResult(
        status_code=outcome.response_snapshot["status_code"],
        body_text=_truncate_body(outcome.response_snapshot.get("body")),
    )
