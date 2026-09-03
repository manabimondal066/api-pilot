"""AI chat assistant route (PRD §17-18, Implementation Plan Module 9).

POST /api/chat                       — send a message to the assistant, scoped to one suite.
GET  /api/chat/{suite_id}/history    — past messages for a suite, oldest first.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID

from app.ai.chat_service import ChatAgentError
from app.api.deps import get_current_workspace_id, get_db
from app.schemas.api import ChatIn, ChatMessageOut, ChatOut, ChatToolCallOut
from app.services import SuiteNotFoundError
from app.services import chat_service

router = APIRouter()


@router.post(
    "/chat",
    response_model=ChatOut,
    summary="Send a message to the AI assistant for a suite",
)
async def send_chat_message(
    payload: ChatIn,
    workspace_id: UUID = Depends(get_current_workspace_id),
    db: AsyncSession = Depends(get_db),
) -> ChatOut:
    """Synchronous, request-blocking call to the configured LLM provider —
    same rationale as test generation (see app/services/test_service.py):
    no job queue in V1.
    """
    try:
        result = await chat_service.send_message(
            db=db,
            workspace_id=workspace_id,
            suite_id=payload.suite_id,
            user_message=payload.message,
        )
    except SuiteNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Suite not found") from exc
    except ChatAgentError as exc:
        # Structured detail (not a plain string): `message` carries the raw
        # provider error text, shown to the user as-is — same shape as
        # test generation, see app/api/endpoints.py and TestGenerationError.
        raise HTTPException(
            status_code=502,
            detail={"message": str(exc), "reason": exc.reason, "reset_at": exc.reset_at},
        ) from exc

    tool_calls = [ChatToolCallOut(**tc.model_dump()) for tc in result.tool_calls]
    changes = [ChatToolCallOut(**tc.model_dump()) for tc in result.changes]
    return ChatOut(reply=result.reply, tool_calls=tool_calls, changes=changes)


@router.get(
    "/chat/{suite_id}/history",
    response_model=list[ChatMessageOut],
    summary="Get chat history for a suite",
)
async def get_chat_history(
    suite_id: UUID,
    workspace_id: UUID = Depends(get_current_workspace_id),
    db: AsyncSession = Depends(get_db),
) -> list[ChatMessageOut]:
    try:
        messages = await chat_service.get_history(
            db=db, workspace_id=workspace_id, suite_id=suite_id
        )
    except SuiteNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Suite not found") from exc

    return [ChatMessageOut.model_validate(m) for m in messages]
