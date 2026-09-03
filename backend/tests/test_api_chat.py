"""API-level tests for POST /api/chat and the validations sub-routes.

Uses the MockProvider (LLM_PROVIDER=mock, forced in conftest.py) via the
cached factory, since the route wires up ChatAgentService with no provider
override (production path).
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.providers.base import ToolCallRequest, ToolChatResult
from app.ai.providers.factory import get_llm_provider
from app.core.constants import DEFAULT_WORKSPACE_ID
from app.models.chat_message import ChatMessage
from app.models.test import Test
from app.services.import_service import import_from_upload

FIXTURES = Path(__file__).parent / "fixtures"


async def _create_test(db: AsyncSession) -> tuple[UUID, UUID]:
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
    return suite.id, test.id


async def test_chat_endpoint_adds_validation_and_persists_messages(
    client: AsyncClient, db: AsyncSession
):
    suite_id, test_id = await _create_test(db)

    provider = get_llm_provider()
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
        ToolChatResult(content="Added a status code check to Get pet by id."),
    ])

    resp = await client.post(
        "/api/chat", json={"suite_id": str(suite_id), "message": "add a status code check"}
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["reply"] == "Added a status code check to Get pet by id."
    assert len(body["changes"]) == 1
    assert body["changes"][0]["tool"] == "add_validation"

    history = (await db.execute(
        ChatMessage.__table__.select().where(ChatMessage.suite_id == suite_id)
    )).all()
    roles = sorted(r.role for r in history)
    assert roles == ["assistant", "user"]


async def test_add_and_remove_validation_routes(client: AsyncClient, db: AsyncSession):
    _suite_id, test_id = await _create_test(db)

    add_resp = await client.post(
        f"/api/tests/{test_id}/validations",
        json={"validation": {"type": "FIELD_EXISTS", "description": "has id", "target": "$.id"}},
    )
    assert add_resp.status_code == 201
    body = add_resp.json()
    assert len(body["validations"]) == 1
    validation_id = body["validations"][0]["id"]

    remove_resp = await client.delete(f"/api/tests/{test_id}/validations/{validation_id}")
    assert remove_resp.status_code == 200
    assert remove_resp.json()["validations"] == []


async def test_chat_endpoint_404s_for_unknown_suite(client: AsyncClient):
    resp = await client.post(
        "/api/chat",
        json={"suite_id": "00000000-0000-0000-0000-000000000099", "message": "hi"},
    )
    assert resp.status_code == 404


async def test_chat_history_returns_persisted_messages_oldest_first(
    client: AsyncClient, db: AsyncSession
):
    suite_id, test_id = await _create_test(db)

    provider = get_llm_provider()
    provider.seed_tool_turns([ToolChatResult(content="Here's what's in your suite.")])
    await client.post(
        "/api/chat", json={"suite_id": str(suite_id), "message": "what tests do I have?"}
    )

    resp = await client.get(f"/api/chat/{suite_id}/history")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 2
    assert body[0]["role"] == "user"
    assert body[0]["content"] == "what tests do I have?"
    assert body[1]["role"] == "assistant"
    assert body[1]["content"] == "Here's what's in your suite."
    assert body[0]["created_at"] <= body[1]["created_at"]


async def test_chat_history_404s_for_unknown_suite(client: AsyncClient):
    resp = await client.get("/api/chat/00000000-0000-0000-0000-000000000099/history")
    assert resp.status_code == 404
