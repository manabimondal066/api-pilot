"""Chat persistence + orchestration glue (PRD §17-18, Implementation Plan
Module 9).

send_message(db, workspace_id, suite_id, user_message) -> ChatTurnResult
    Loads suite context and prior history, runs the agent's tool-calling
    loop (app.ai.chat_service.ChatAgentService), and persists both the
    user's message and the assistant's reply as ChatMessage rows.

get_history(db, workspace_id, suite_id) -> list[ChatMessage]
    All persisted messages for a suite, oldest first, so the chat panel
    isn't empty on page reload.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.chat_service import ChatAgentError, ChatAgentService
from app.ai.providers.base import Message
from app.ai.schemas.chat import ChatTurnResult
from app.ai.tools.chat_tools import ToolContext
from app.models.chat_message import ChatMessage
from app.models.endpoint import Endpoint
from app.models.test import Test
from app.services.suite_service import get_suite


async def _endpoint_summaries(db: AsyncSession, suite_id: UUID) -> list[dict]:
    stmt = (
        select(
            Endpoint.method,
            Endpoint.path,
            Endpoint.name,
            func.count(Test.id).label("test_count"),
        )
        .outerjoin(Test, Test.endpoint_id == Endpoint.id)
        .where(Endpoint.suite_id == suite_id)
        .group_by(Endpoint.id)
        .order_by(Endpoint.path)
    )
    rows = (await db.execute(stmt)).all()
    return [
        {"method": r.method, "path": r.path, "name": r.name, "test_count": r.test_count}
        for r in rows
    ]


async def _load_history(db: AsyncSession, suite_id: UUID, limit: int = 20) -> list[Message]:
    """Prior turns for *suite_id*, oldest first, capped at *limit* messages.

    Only role/content is replayed — intermediate tool-call messages aren't
    persisted per-turn (see ChatMessage.tool_calls docstring), so there's
    nothing else to reconstruct here.
    """
    result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.suite_id == suite_id)
        .order_by(ChatMessage.created_at.desc())
        .limit(limit)
    )
    rows = list(result.scalars().all())
    rows.reverse()
    return [Message(role=row.role, content=row.content) for row in rows]


async def send_message(
    db: AsyncSession,
    workspace_id: UUID,
    suite_id: UUID,
    user_message: str,
) -> ChatTurnResult:
    """Run one chat turn against *suite_id* and persist it.

    Raises:
        SuiteNotFoundError: if the suite doesn't exist in the workspace.
        ChatAgentError: if the AI layer fails to produce a reply.
    """
    suite = await get_suite(db, suite_id, workspace_id)  # tenant-isolation check
    endpoints = await _endpoint_summaries(db, suite_id)
    history = await _load_history(db, suite_id)

    db.add(ChatMessage(workspace_id=workspace_id, suite_id=suite_id, role="user", content=user_message))
    await db.commit()

    tool_ctx = ToolContext(db=db, workspace_id=workspace_id, suite_id=suite_id)
    service = ChatAgentService()
    try:
        result = await service.send_message(
            tool_ctx=tool_ctx,
            suite_name=suite.name,
            endpoint_summaries=endpoints,
            history=history,
            user_message=user_message,
        )
    except ChatAgentError:
        raise

    db.add(
        ChatMessage(
            workspace_id=workspace_id,
            suite_id=suite_id,
            role="assistant",
            content=result.reply,
            tool_calls=[tc.model_dump() for tc in result.tool_calls] or None,
        )
    )
    await db.commit()

    return result


async def get_history(
    db: AsyncSession,
    workspace_id: UUID,
    suite_id: UUID,
) -> list[ChatMessage]:
    """All persisted messages for *suite_id*, oldest first.

    Raises:
        SuiteNotFoundError: if the suite doesn't exist in the workspace.
    """
    await get_suite(db, suite_id, workspace_id)  # tenant-isolation check
    result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.suite_id == suite_id)
        .order_by(ChatMessage.created_at.asc())
    )
    return list(result.scalars().all())
