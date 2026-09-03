"""The chat agent's tool belt (PRD §17, Implementation Plan Module 9).

Every tool is scoped to one (workspace_id, suite_id) pair via ToolContext.
None of these functions trust an id handed back by the model — each one
re-derives the owning suite/workspace from the database before acting, the
same way every other service-layer function in this codebase does (see
app/services/test_service.py, app/services/dependency_service.py). A
test_id or endpoint_id belonging to a different workspace, or even a
different suite within the same workspace, is rejected with ToolError
rather than silently acted on.

add_validation / remove_validation call app.services.test_service directly
— the same functions the HTTP routes in app/api/tests.py call — so a tool
call and a manual PATCH go through one write path, never a shortcut.

TOOL_SPECS is OpenAI function-calling JSON schema, consumed as-is by
OpenAICompatibleProvider.chat_with_tools and translated internally by
AnthropicProvider.chat_with_tools (see app/ai/providers/base.py).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.endpoint import Endpoint
from app.models.execution import Execution
from app.models.suite import Suite
from app.models.test import Test
from app.services import TestNotFoundError, ValidationNotFoundError
from app.services import test_service


class ToolError(Exception):
    """Raised by a tool when it refuses or fails to act.

    Caught by the agent loop and fed back to the model as the tool result
    content, so the model can react (e.g. apologize, ask for clarification)
    instead of the whole chat turn crashing.
    """


@dataclass
class ToolContext:
    db: AsyncSession
    workspace_id: UUID
    suite_id: UUID


def _endpoint_summary(endpoint: Endpoint) -> dict[str, Any]:
    return {
        "id": str(endpoint.id),
        "method": endpoint.method,
        "path": endpoint.path,
        "name": endpoint.name,
        "description": endpoint.description,
    }


def _test_summary(test: Test) -> dict[str, Any]:
    return {
        "id": str(test.id),
        "endpoint_id": str(test.endpoint_id),
        "name": test.name,
        "category": test.category,
        "method": test.method,
        "path": test.path,
        "headers": test.headers,
        "query_params": test.query_params,
        "body": test.body,
        "validations": test.validations,
        "extractions": test.extractions,
        "confidence": test.confidence,
        "version": test.version,
    }


async def _require_endpoint_in_suite(ctx: ToolContext, endpoint_id: UUID) -> Endpoint:
    result = await ctx.db.execute(
        select(Endpoint)
        .join(Suite, Endpoint.suite_id == Suite.id)
        .where(
            Endpoint.id == endpoint_id,
            Endpoint.suite_id == ctx.suite_id,
            Suite.workspace_id == ctx.workspace_id,
        )
    )
    endpoint = result.scalar_one_or_none()
    if endpoint is None:
        raise ToolError(f"No endpoint {endpoint_id} in this suite.")
    return endpoint


async def _require_test_in_suite(ctx: ToolContext, test_id: UUID) -> Test:
    try:
        test = await test_service.get_test(ctx.db, test_id, ctx.workspace_id)
    except TestNotFoundError as exc:
        raise ToolError(f"No test {test_id} in this workspace.") from exc
    if test.suite_id != ctx.suite_id:
        # Exists, but in a different suite — never act on it just because
        # the workspace check passed.
        raise ToolError(f"Test {test_id} does not belong to this suite.")
    return test


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


async def get_endpoint(ctx: ToolContext, endpoint_name: str) -> dict[str, Any]:
    result = await ctx.db.execute(
        select(Endpoint).where(
            Endpoint.suite_id == ctx.suite_id, Endpoint.name == endpoint_name
        )
    )
    endpoint = result.scalar_one_or_none()
    if endpoint is None:
        raise ToolError(f"No endpoint named {endpoint_name!r} in this suite.")
    return _endpoint_summary(endpoint)


async def list_tests_for_endpoint(ctx: ToolContext, endpoint_id: str) -> list[dict[str, Any]]:
    try:
        endpoint_uuid = UUID(endpoint_id)
    except ValueError as exc:
        raise ToolError(f"{endpoint_id!r} is not a valid endpoint id.") from exc
    await _require_endpoint_in_suite(ctx, endpoint_uuid)
    tests = await test_service.list_tests_for_endpoint(ctx.db, endpoint_uuid, ctx.workspace_id)
    return [_test_summary(t) for t in tests]


async def get_test(ctx: ToolContext, test_id: str) -> dict[str, Any]:
    try:
        test_uuid = UUID(test_id)
    except ValueError as exc:
        raise ToolError(f"{test_id!r} is not a valid test id.") from exc
    test = await _require_test_in_suite(ctx, test_uuid)
    return _test_summary(test)


async def add_validation(ctx: ToolContext, test_id: str, validation: dict[str, Any]) -> dict[str, Any]:
    try:
        test_uuid = UUID(test_id)
    except ValueError as exc:
        raise ToolError(f"{test_id!r} is not a valid test id.") from exc
    await _require_test_in_suite(ctx, test_uuid)  # tenant/suite check before writing
    try:
        updated = await test_service.add_validation(
            ctx.db, test_uuid, ctx.workspace_id, validation
        )
    except TestNotFoundError as exc:
        raise ToolError(f"No test {test_id} in this workspace.") from exc
    except Exception as exc:  # pydantic ValidationError etc.
        raise ToolError(f"Invalid validation: {exc}") from exc
    return _test_summary(updated)


async def get_last_execution(ctx: ToolContext, test_id: str) -> dict[str, Any]:
    """The most recent execution result for a test, if any — so the agent
    can see WHY a test failed (status, response, validation results,
    runtime error) before proposing a fix, rather than guessing.
    """
    try:
        test_uuid = UUID(test_id)
    except ValueError as exc:
        raise ToolError(f"{test_id!r} is not a valid test id.") from exc
    await _require_test_in_suite(ctx, test_uuid)

    result = await ctx.db.execute(
        select(Execution)
        .where(Execution.test_id == test_uuid)
        .options(selectinload(Execution.results))
        .order_by(Execution.started_at.desc())
        .limit(1)
    )
    execution = result.scalar_one_or_none()
    if execution is None:
        return {"has_execution": False}

    latest_result = execution.results[-1] if execution.results else None
    return {
        "has_execution": True,
        "status": execution.status,
        "started_at": execution.started_at.isoformat(),
        "result": (
            {
                "status": latest_result.status,
                "request_snapshot": latest_result.request_snapshot,
                "response_snapshot": latest_result.response_snapshot,
                "validation_results": latest_result.validation_results,
                "error": latest_result.error,
            }
            if latest_result
            else None
        ),
    }


async def update_test_body(ctx: ToolContext, test_id: str, body: Any) -> dict[str, Any]:
    try:
        test_uuid = UUID(test_id)
    except ValueError as exc:
        raise ToolError(f"{test_id!r} is not a valid test id.") from exc
    await _require_test_in_suite(ctx, test_uuid)  # tenant/suite check before writing
    try:
        updated = await test_service.update_test_body(ctx.db, test_uuid, ctx.workspace_id, body)
    except TestNotFoundError as exc:
        raise ToolError(f"No test {test_id} in this workspace.") from exc
    return _test_summary(updated)


async def remove_validation(ctx: ToolContext, test_id: str, validation_id: str) -> dict[str, Any]:
    try:
        test_uuid = UUID(test_id)
    except ValueError as exc:
        raise ToolError(f"{test_id!r} is not a valid test id.") from exc
    await _require_test_in_suite(ctx, test_uuid)  # tenant/suite check before writing
    try:
        updated = await test_service.remove_validation(
            ctx.db, test_uuid, ctx.workspace_id, validation_id
        )
    except TestNotFoundError as exc:
        raise ToolError(f"No test {test_id} in this workspace.") from exc
    except ValidationNotFoundError as exc:
        raise ToolError(f"No validation {validation_id} on test {test_id}.") from exc
    return _test_summary(updated)


async def ask_user(
    ctx: ToolContext,
    question: str,
    options: list[str],
    allow_free_text: bool = True,
) -> dict[str, Any]:
    """Pose a clarifying question to the user instead of guessing (PRD
    §16.2, §17). Not a mutation — this doesn't touch the database; the
    frontend renders `question`/`options` as clickable buttons on this
    turn's reply, and a click sends that option's text back as the user's
    next chat message, exactly as if they had typed it.
    """
    if not (2 <= len(options) <= 4):
        raise ToolError("options must contain between 2 and 4 choices.")
    return {"question": question, "options": options, "allow_free_text": allow_free_text}


ToolFn = Callable[..., Awaitable[Any]]

TOOL_IMPLS: dict[str, ToolFn] = {
    "get_endpoint": get_endpoint,
    "list_tests_for_endpoint": list_tests_for_endpoint,
    "get_test": get_test,
    "add_validation": add_validation,
    "remove_validation": remove_validation,
    "get_last_execution": get_last_execution,
    "update_test_body": update_test_body,
    "ask_user": ask_user,
}

# Tools that mutate state — the agent loop surfaces their results in the
# "changes" list returned to the frontend (see app/ai/chat_service.py).
MUTATING_TOOLS = {"add_validation", "remove_validation", "update_test_body"}

TOOL_SPECS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_endpoint",
            "description": "Look up an endpoint in the current suite by its name.",
            "parameters": {
                "type": "object",
                "properties": {
                    "endpoint_name": {
                        "type": "string",
                        "description": "The endpoint's name, e.g. 'createUser'.",
                    }
                },
                "required": ["endpoint_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_tests_for_endpoint",
            "description": "List all generated tests for one endpoint in the current suite.",
            "parameters": {
                "type": "object",
                "properties": {
                    "endpoint_id": {
                        "type": "string",
                        "description": "The endpoint's id (UUID), from get_endpoint.",
                    }
                },
                "required": ["endpoint_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_test",
            "description": "Get full detail for one test, including its current validations.",
            "parameters": {
                "type": "object",
                "properties": {
                    "test_id": {"type": "string", "description": "The test's id (UUID)."}
                },
                "required": ["test_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_validation",
            "description": (
                "Add a new validation to a test. `validation` must have "
                "'type' (one of STATUS_CODE, FIELD_EXISTS, FIELD_EQUALS, "
                "FIELD_TYPE, FIELD_REGEX, FIELD_RANGE, SCHEMA_MATCH, "
                "RESPONSE_TIME, CUSTOM_JSONPATH) and 'description' (a short "
                "human-readable sentence). Include 'target' (a JSONPath, "
                "e.g. '$.id') and 'expected' when the validation type needs them."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "test_id": {"type": "string", "description": "The test's id (UUID)."},
                    "validation": {
                        "type": "object",
                        "description": "A Validation object: type, description, target, expected, severity.",
                    },
                },
                "required": ["test_id", "validation"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remove_validation",
            "description": "Remove one validation from a test by its validation id.",
            "parameters": {
                "type": "object",
                "properties": {
                    "test_id": {"type": "string", "description": "The test's id (UUID)."},
                    "validation_id": {
                        "type": "string",
                        "description": "The validation's id, from get_test's validations list.",
                    },
                },
                "required": ["test_id", "validation_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_last_execution",
            "description": (
                "Get the most recent execution result for a test: pass/fail "
                "status, the actual request sent, the response received, "
                "per-validation results, and any runtime error. Call this "
                "before fixing a test the user says is failing, so the fix "
                "addresses the real cause instead of a guess."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "test_id": {"type": "string", "description": "The test's id (UUID)."}
                },
                "required": ["test_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_test_body",
            "description": (
                "Replace a test's request body/payload entirely, e.g. to fix "
                "a duplicate id or another invalid value causing failures. "
                "Prefer calling get_last_execution first when the user "
                "references a failure, so the new body actually addresses "
                "what went wrong."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "test_id": {"type": "string", "description": "The test's id (UUID)."},
                    "body": {
                        "description": "The full replacement request body (any JSON value).",
                    },
                },
                "required": ["test_id", "body"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ask_user",
            "description": (
                "Ask the user a clarifying question instead of guessing, when you're "
                "missing information you can't work out from the suite, the endpoint, "
                "or an observed response. Ground the options in real data where "
                "possible (e.g. actual field names from a response you've seen)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "A short, specific question."},
                    "options": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "2 to 4 short answers the user can pick from.",
                    },
                    "allow_free_text": {
                        "type": "boolean",
                        "description": "Whether the user may type something else instead. Default true.",
                    },
                },
                "required": ["question", "options"],
            },
        },
    },
]
