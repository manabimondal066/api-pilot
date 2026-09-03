"""Tests for the chat agent's tool-calling loop (Implementation Plan Module 9).

Covers:
- add_validation via a tool call actually persists through the real service
  layer (not a bypass) — same assertion style as test_ai_orchestration.py's
  MockProvider-seeded tests.
- a test_id from a different workspace is rejected by the tool, not
  silently acted on.
- the agent loop stops once the model returns a final answer with no
  tool_calls.
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.chat_service import ChatAgentError, ChatAgentService
from app.ai.providers.base import LLMProviderError, Message, ToolCallRequest, ToolChatResult
from app.ai.providers.errors import attach_reset_marker
from app.ai.providers.mock_provider import MockProvider
from app.ai.tools.chat_tools import ToolContext
from app.core.constants import DEFAULT_WORKSPACE_ID
from app.models.test import Test
from app.services.import_service import import_from_upload

FIXTURES = Path(__file__).parent / "fixtures"

OTHER_WORKSPACE_ID = UUID("22222222-2222-2222-2222-222222222222")


async def _create_test(db: AsyncSession) -> tuple[UUID, UUID, UUID]:
    """Returns (suite_id, endpoint_id, test_id)."""
    content = (FIXTURES / "petstore_v3.json").read_bytes()
    suite = await import_from_upload(db, DEFAULT_WORKSPACE_ID, content, "petstore_v3.json")
    endpoint_id = suite.endpoints[0].id

    test = Test(
        suite_id=suite.id,
        endpoint_id=endpoint_id,
        name="Get pet by id",
        category="POSITIVE",
        method="GET",
        path="/pet/{petId}",
        validations=[],
    )
    db.add(test)
    await db.commit()
    return suite.id, endpoint_id, test.id


async def test_add_validation_tool_call_persists_via_service_layer(db: AsyncSession):
    suite_id, _endpoint_id, test_id = await _create_test(db)

    provider = MockProvider()
    provider.seed_tool_turns([
        ToolChatResult(
            tool_calls=[
                ToolCallRequest(
                    id="call_1",
                    name="add_validation",
                    arguments={
                        "test_id": str(test_id),
                        "validation": {
                            "type": "STATUS_CODE",
                            "description": "Status code is 200",
                            "expected": 200,
                        },
                    },
                )
            ]
        ),
        ToolChatResult(content="Added a status code check."),
    ])
    service = ChatAgentService(provider=provider)
    tool_ctx = ToolContext(db=db, workspace_id=DEFAULT_WORKSPACE_ID, suite_id=suite_id)

    result = await service.send_message(
        tool_ctx=tool_ctx,
        suite_name="Petstore",
        endpoint_summaries=[],
        history=[],
        user_message="add a status code check to my get pet test",
    )

    assert result.reply == "Added a status code check."
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].tool == "add_validation"
    assert result.tool_calls[0].error is None
    assert len(result.changes) == 1

    # Confirm it actually persisted through test_service, not a bypass.
    persisted = await db.get(Test, test_id)
    assert len(persisted.validations) == 1
    assert persisted.validations[0]["type"] == "STATUS_CODE"
    assert persisted.version == 2


async def test_tool_rejects_test_id_from_other_workspace(db: AsyncSession):
    suite_id, _endpoint_id, test_id = await _create_test(db)

    provider = MockProvider()
    provider.seed_tool_turns([
        ToolChatResult(
            tool_calls=[
                ToolCallRequest(
                    id="call_1",
                    name="add_validation",
                    arguments={
                        "test_id": str(test_id),
                        "validation": {"type": "STATUS_CODE", "description": "x", "expected": 200},
                    },
                )
            ]
        ),
        ToolChatResult(content="Could not find that test."),
    ])
    service = ChatAgentService(provider=provider)
    # Tool context scoped to a *different* workspace than the test belongs to.
    tool_ctx = ToolContext(db=db, workspace_id=OTHER_WORKSPACE_ID, suite_id=suite_id)

    result = await service.send_message(
        tool_ctx=tool_ctx,
        suite_name="Petstore",
        endpoint_summaries=[],
        history=[],
        user_message="add a status code check",
    )

    assert result.tool_calls[0].error is not None
    assert result.changes == []  # nothing persisted

    persisted = await db.get(Test, test_id)
    assert persisted.validations == []


async def test_agent_stops_when_no_tool_calls_returned():
    provider = MockProvider()
    provider.seed_tool_turns([ToolChatResult(content="Here's what's in your suite.")])
    service = ChatAgentService(provider=provider)
    tool_ctx = ToolContext(db=None, workspace_id=DEFAULT_WORKSPACE_ID, suite_id=DEFAULT_WORKSPACE_ID)

    result = await service.send_message(
        tool_ctx=tool_ctx,
        suite_name="Petstore",
        endpoint_summaries=[{"method": "GET", "path": "/pet/{id}", "name": "getPet", "test_count": 1}],
        history=[],
        user_message="what tests do I have?",
    )

    assert result.reply == "Here's what's in your suite."
    assert result.tool_calls == []


async def test_fix_failing_test_calls_update_test_body_via_service_layer(db: AsyncSession):
    suite_id, _endpoint_id, test_id = await _create_test(db)

    provider = MockProvider()
    provider.seed_tool_turns([
        ToolChatResult(
            tool_calls=[
                ToolCallRequest(id="call_1", name="get_last_execution", arguments={"test_id": str(test_id)})
            ]
        ),
        ToolChatResult(
            tool_calls=[
                ToolCallRequest(
                    id="call_2",
                    name="update_test_body",
                    arguments={"test_id": str(test_id), "body": {"assetId": "asset-002"}},
                )
            ]
        ),
        ToolChatResult(content="Fixed the duplicate asset id — changed it to asset-002."),
    ])
    service = ChatAgentService(provider=provider)
    tool_ctx = ToolContext(db=db, workspace_id=DEFAULT_WORKSPACE_ID, suite_id=suite_id)

    result = await service.send_message(
        tool_ctx=tool_ctx,
        suite_name="Petstore",
        endpoint_summaries=[],
        history=[],
        user_message="the Create Asset test is failing because the asset ID is a duplicate, please fix it",
    )

    assert result.reply == "Fixed the duplicate asset id — changed it to asset-002."
    tool_names = [tc.tool for tc in result.tool_calls]
    assert tool_names == ["get_last_execution", "update_test_body"]
    assert all(tc.error is None for tc in result.tool_calls)
    assert len(result.changes) == 1
    assert result.changes[0].tool == "update_test_body"

    persisted = await db.get(Test, test_id)
    assert persisted.body == {"assetId": "asset-002"}
    assert persisted.version == 2


async def test_oversized_request_declines_without_tool_calls():
    provider = MockProvider()
    provider.seed_tool_turns([
        ToolChatResult(
            content=(
                "Generating 1000 test cases in one message isn't something I can do — "
                "that's too large for a single reply. I can generate tests for one "
                "endpoint at a time instead — which endpoint would you like to start with?"
            )
        )
    ])
    service = ChatAgentService(provider=provider)
    tool_ctx = ToolContext(db=None, workspace_id=DEFAULT_WORKSPACE_ID, suite_id=DEFAULT_WORKSPACE_ID)

    result = await service.send_message(
        tool_ctx=tool_ctx,
        suite_name="Petstore",
        endpoint_summaries=[{"method": "GET", "path": "/pet/{id}", "name": "getPet", "test_count": 1}],
        history=[],
        user_message="write 1000 test cases for this suite right now",
    )

    assert result.tool_calls == []  # no partial/wrong action attempted
    assert "1000" in result.reply or "too large" in result.reply.lower()
    assert result.changes == []


async def test_out_of_scope_execution_request_declines_without_tool_calls():
    provider = MockProvider()
    provider.seed_tool_turns([
        ToolChatResult(
            content=(
                "I can't execute tests against production — I don't have a tool for "
                "running tests, only for inspecting and editing them. Use the Execute "
                "button on the test once you've selected the right environment."
            )
        )
    ])
    service = ChatAgentService(provider=provider)
    tool_ctx = ToolContext(db=None, workspace_id=DEFAULT_WORKSPACE_ID, suite_id=DEFAULT_WORKSPACE_ID)

    result = await service.send_message(
        tool_ctx=tool_ctx,
        suite_name="Petstore",
        endpoint_summaries=[],
        history=[],
        user_message="execute this suite against production right now",
    )

    assert result.tool_calls == []
    assert "can't" in result.reply.lower() or "cannot" in result.reply.lower()
    assert result.changes == []


async def test_partial_success_reported_when_provider_fails_mid_turn(db: AsyncSession):
    """A mutating tool call that already succeeded must never be silently
    dropped behind a bare error if a later step in the same turn fails."""
    suite_id, _endpoint_id, test_id = await _create_test(db)

    provider = MockProvider()
    provider.seed_tool_turns([
        ToolChatResult(
            tool_calls=[
                ToolCallRequest(
                    id="call_1",
                    name="add_validation",
                    arguments={
                        "test_id": str(test_id),
                        "validation": {
                            "type": "STATUS_CODE",
                            "description": "Status code is 200",
                            "expected": 200,
                        },
                    },
                )
            ]
        ),
        LLMProviderError("rate limit reached"),
    ])
    service = ChatAgentService(provider=provider)
    tool_ctx = ToolContext(db=db, workspace_id=DEFAULT_WORKSPACE_ID, suite_id=suite_id)

    result = await service.send_message(
        tool_ctx=tool_ctx,
        suite_name="Petstore",
        endpoint_summaries=[],
        history=[],
        user_message="add a status code check to my get pet test",
    )

    # The successful change is still reported, not swallowed by the failure.
    assert len(result.changes) == 1
    assert result.changes[0].tool == "add_validation"
    assert "add_validation" in result.reply
    # The raw provider error text is shown as-is, not a paraphrased message.
    assert "rate limit reached" in result.reply
    assert "you may want to check the result" in result.reply.lower()

    persisted = await db.get(Test, test_id)
    assert len(persisted.validations) == 1


async def test_quota_exhausted_without_reset_time_reports_change_with_raw_message(
    db: AsyncSession,
):
    """A quota-exhausted provider failure must surface the raw provider
    error text (not a paraphrased message) in the reply."""
    suite_id, _endpoint_id, test_id = await _create_test(db)

    provider = MockProvider()
    provider.seed_tool_turns([
        ToolChatResult(
            tool_calls=[
                ToolCallRequest(
                    id="call_1",
                    name="add_validation",
                    arguments={
                        "test_id": str(test_id),
                        "validation": {
                            "type": "STATUS_CODE",
                            "description": "Status code is 200",
                            "expected": 200,
                        },
                    },
                )
            ]
        ),
        LLMProviderError(
            "LLM API error (nvidia_nim): insufficient_quota — quota exceeded"
        ),
    ])
    service = ChatAgentService(provider=provider)
    tool_ctx = ToolContext(db=db, workspace_id=DEFAULT_WORKSPACE_ID, suite_id=suite_id)

    result = await service.send_message(
        tool_ctx=tool_ctx,
        suite_name="Petstore",
        endpoint_summaries=[],
        history=[],
        user_message="add a status code check to my get pet test",
    )

    assert len(result.changes) == 1
    # The raw provider error text is shown as-is now, not the paraphrased
    # quota_exhausted message.
    assert "insufficient_quota" in result.reply
    assert "quota exceeded" in result.reply


async def test_quota_exhausted_with_reset_time_surfaces_it_on_chat_agent_error():
    """When nothing succeeded before the failure, ChatAgentError is raised
    with reason='quota_exhausted' and the provider-supplied reset_at — the
    API layer (app/api/chat.py) turns this into the same {message, reason,
    reset_at} shape test generation uses."""
    provider = MockProvider()
    reset_at = "2026-09-03T00:00:00+00:00"
    message = attach_reset_marker(
        "LLM API error (nvidia_nim): insufficient_quota — quota exceeded", reset_at
    )
    provider.seed_tool_turns([LLMProviderError(message)])
    service = ChatAgentService(provider=provider)
    tool_ctx = ToolContext(db=None, workspace_id=DEFAULT_WORKSPACE_ID, suite_id=DEFAULT_WORKSPACE_ID)

    with pytest.raises(ChatAgentError) as exc_info:
        await service.send_message(
            tool_ctx=tool_ctx,
            suite_name="Petstore",
            endpoint_summaries=[],
            history=[],
            user_message="hello",
        )

    exc = exc_info.value
    assert exc.reason == "quota_exhausted"
    assert exc.reset_at == reset_at
    # Raw provider text is shown, with the internal reset marker stripped
    # (reset_at is already surfaced separately above).
    assert "insufficient_quota" in str(exc)
    assert "[quota_reset_at=" not in str(exc)


async def test_rate_limited_chat_failure_not_confused_with_quota_exhausted():
    """A plain 'rate limit reached' failure (no quota/billing wording) must
    classify as rate_limited, not quota_exhausted."""
    provider = MockProvider()
    provider.seed_tool_turns([LLMProviderError("rate limit reached, too many requests")])
    service = ChatAgentService(provider=provider)
    tool_ctx = ToolContext(db=None, workspace_id=DEFAULT_WORKSPACE_ID, suite_id=DEFAULT_WORKSPACE_ID)

    with pytest.raises(ChatAgentError) as exc_info:
        await service.send_message(
            tool_ctx=tool_ctx,
            suite_name="Petstore",
            endpoint_summaries=[],
            history=[],
            user_message="hello",
        )

    assert exc_info.value.reason == "rate_limited"


async def test_request_too_large_chat_failure_gets_its_own_message():
    """The Groq 413 shape must classify as request_too_large in chat too,
    and the raw provider text (not a paraphrased message) reaches the
    user."""
    provider = MockProvider()
    provider.seed_tool_turns([
        LLMProviderError(
            "LLM API error (groq): Error code: 413 - {'error': {'message': "
            "'Request too large for model `llama-3.3-70b-versatile`... on "
            "tokens per minute (TPM): Limit 6000, Requested 8000.', "
            "'type': 'tokens', 'code': 'rate_limit_exceeded'}}"
        )
    ])
    service = ChatAgentService(provider=provider)
    tool_ctx = ToolContext(db=None, workspace_id=DEFAULT_WORKSPACE_ID, suite_id=DEFAULT_WORKSPACE_ID)

    with pytest.raises(ChatAgentError) as exc_info:
        await service.send_message(
            tool_ctx=tool_ctx,
            suite_name="Petstore",
            endpoint_summaries=[],
            history=[],
            user_message="hello",
        )

    exc = exc_info.value
    assert exc.reason == "request_too_large"
    assert "too large" in str(exc).lower()
    assert "requested 8000" in str(exc).lower()


async def test_short_term_rate_limit_not_misclassified_as_quota_in_chat():
    """Regression test for the exact production error shape (Groq,
    openai/gpt-oss-120b, 825ms retry) that was showing users a false
    'quota exhausted' message — must classify as rate_limited end-to-end
    through the chat path too, not just the shared classifier directly."""
    raw = (
        "Rate limit reached for model `openai/gpt-oss-120b`... on tokens per "
        "minute (TPM): Limit 8000, Used 4068, Requested 4042. Please try "
        "again in 825ms... code: rate_limit_exceeded"
    )
    with_marker = attach_reset_marker(raw, "2026-09-02T00:00:00.825000+00:00")
    provider = MockProvider()
    provider.seed_tool_turns([LLMProviderError(with_marker)])
    service = ChatAgentService(provider=provider)
    tool_ctx = ToolContext(db=None, workspace_id=DEFAULT_WORKSPACE_ID, suite_id=DEFAULT_WORKSPACE_ID)

    with pytest.raises(ChatAgentError) as exc_info:
        await service.send_message(
            tool_ctx=tool_ctx,
            suite_name="Petstore",
            endpoint_summaries=[],
            history=[],
            user_message="hello",
        )

    exc = exc_info.value
    assert exc.reason == "rate_limited"
    # Raw provider text, reset marker stripped — no literal "quota" wording
    # despite the marker's own field name containing that substring.
    assert "quota" not in str(exc).lower()
    assert "rate limit reached" in str(exc).lower()


async def test_no_changes_and_no_tool_calls_still_raises_on_provider_failure():
    """When nothing succeeded before the failure, there's nothing to report
    — this should still surface as an error, not a fake empty success."""
    provider = MockProvider()
    provider.seed_tool_turns([LLMProviderError("connection reset")])
    service = ChatAgentService(provider=provider)
    tool_ctx = ToolContext(db=None, workspace_id=DEFAULT_WORKSPACE_ID, suite_id=DEFAULT_WORKSPACE_ID)

    with pytest.raises(ChatAgentError):
        await service.send_message(
            tool_ctx=tool_ctx,
            suite_name="Petstore",
            endpoint_summaries=[],
            history=[],
            user_message="hello",
        )


async def test_agent_replays_history_and_tool_calls_in_messages():
    provider = MockProvider()
    provider.seed_tool_turns([ToolChatResult(content="ok")])
    service = ChatAgentService(provider=provider)
    tool_ctx = ToolContext(db=None, workspace_id=DEFAULT_WORKSPACE_ID, suite_id=DEFAULT_WORKSPACE_ID)

    history = [Message(role="user", content="hi"), Message(role="assistant", content="hello")]
    await service.send_message(
        tool_ctx=tool_ctx,
        suite_name="Petstore",
        endpoint_summaries=[],
        history=history,
        user_message="follow up question",
    )

    call = provider.calls[0]
    assert call["method"] == "chat_with_tools"
    contents = [m["content"] for m in call["messages"]]
    assert "hi" in contents
    assert "hello" in contents
    assert "follow up question" in contents
