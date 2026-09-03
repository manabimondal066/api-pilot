"""Chat Agent Service — the AI assistant's tool-calling loop (PRD §17-18,
Implementation Plan Module 9).

Mirrors AIOrchestrationService's shape (app/ai/service.py): a thin facade
over an injected LLMProvider, structured around one job (here, a multi-turn
tool-calling loop instead of one-shot structured generation).

Not using pydantic-ai
----------------------
pydantic-ai's Agent brings its own per-provider Model classes (OpenAIModel,
AnthropicModel, ...) with their own provider-selection and retry logic. That
duplicates app.ai.providers.factory, which already gives this codebase
provider independence (PRD §19.3, §41) across NVIDIA NIM / Groq / OpenAI /
Anthropic / mock via one LLMProvider Protocol. Routing the chat agent
through pydantic-ai would mean either running two separate provider
selection mechanisms side by side, or reimplementing the LLMProvider
Protocol's generate_structured/chat on top of pydantic-ai's Model
abstraction — neither is a clean fit. NVIDIA NIM's OpenAI-compatible
endpoint does support tool calls for the configured model
(meta/llama-3.3-70b-instruct), so instead this module extends LLMProvider
itself with chat_with_tools (app/ai/providers/base.py), implemented natively
per provider (OpenAI-style `tools=` param for OpenAICompatibleProvider,
Anthropic's `tools` param for AnthropicProvider) — the "use the
currently-configured provider's native tool support instead" fallback.
pydantic-ai was not added as a dependency.
"""

from __future__ import annotations

import json
import logging

from app.ai.prompts.chat import SYSTEM_PROMPT, build_suite_summary
from app.ai.providers.base import LLMProvider, LLMProviderError, Message, ToolCallRequest
from app.ai.providers.errors import classify_provider_error, strip_reset_marker
from app.ai.providers.factory import get_llm_provider
from app.ai.schemas.chat import ChatTurnResult, ToolCallRecord
from app.ai.tools.chat_tools import MUTATING_TOOLS, TOOL_IMPLS, TOOL_SPECS, ToolContext, ToolError

logger = logging.getLogger(__name__)

MAX_TOOL_ITERATIONS = 6

# Defense-in-depth against a runaway or manipulated mutation loop (e.g. a
# test's own name/description containing something that reads like an
# instruction — "prompt injection via test data"). There is no bulk-delete
# or bulk-edit tool, so a legitimate single-message request should only
# ever need a handful of mutating calls (one test, maybe a couple of
# validations); this caps the blast radius of anything that tries to chain
# many mutations in one turn, independent of how well the prompt/model
# itself resists doing so.
MAX_MUTATIONS_PER_TURN = 5


class ChatAgentError(Exception):
    """Raised when the chat agent fails to produce a reply after retries/iterations.

    ``reason``/``reset_at`` mirror TestGenerationError's fields (see
    app.services.__init__) — same shared classification
    (app.ai.providers.errors), so the API layer returns the same
    {message, reason, reset_at} shape for both features.
    """

    def __init__(self, message: str, reason: str = "unknown", reset_at: str | None = None):
        super().__init__(message)
        self.reason = reason
        self.reset_at = reset_at


class ChatAgentService:
    """Facade for the AI chat assistant. One instance per request is fine."""

    def __init__(self, provider: LLMProvider | None = None):
        self._provider = provider or get_llm_provider()

    async def send_message(
        self,
        tool_ctx: ToolContext,
        suite_name: str,
        endpoint_summaries: list[dict],
        history: list[Message],
        user_message: str,
    ) -> ChatTurnResult:
        """Run one chat turn: send *user_message* plus prior *history*,
        letting the model call tools as needed, and return its final reply.

        *endpoint_summaries* is [{"method","path","name","test_count"}, ...]
        for the suite — see app.ai.prompts.chat.build_suite_summary. Only a
        summary is embedded in the system prompt; tools fetch endpoint/test
        detail on demand.

        If a mutating tool (add_validation, remove_validation,
        update_test_body) already succeeded earlier in this turn and a
        *later* step then fails (provider error, rate limit, or running out
        of tool-calling rounds), that success is never silently dropped —
        this returns a ChatTurnResult reporting the change plus a plain
        explanation of the interruption, instead of raising. ChatAgentError
        is only raised when nothing was accomplished at all, since there is
        nothing to report to the user in that case.

        Raises:
            ChatAgentError: if the provider errors out or the model doesn't
                produce a final answer, and no tool call had succeeded yet
                in this turn.
        """
        system = f"{SYSTEM_PROMPT}\n\n{build_suite_summary(suite_name, endpoint_summaries)}"
        messages = [*history, Message(role="user", content=user_message)]
        tool_calls_made: list[ToolCallRecord] = []

        for iteration in range(MAX_TOOL_ITERATIONS):
            try:
                result = await self._provider.chat_with_tools(
                    messages=messages,
                    tools=TOOL_SPECS,
                    system=system,
                    # Groq's TPM rate limit budgets against max_tokens (the
                    # reservation), not actual completion length — live probe
                    # against the real Groq endpoint (2026-09-02) showed two
                    # plain "hi" turns at max_tokens=2048 consuming 6243 of an
                    # 8000 TPM budget while only generating ~77 completion
                    # tokens each, exhausting the budget by turn 3. Chat
                    # replies here are short explanations/confirmations, not
                    # generated code, so 800 tokens is ample headroom while
                    # roughly halving the reservation per turn.
                    max_tokens=800,
                )
            except LLMProviderError as exc:
                # reason/reset_at are the shared classification (kept for
                # logging and for the {message, reason, reset_at} shape the
                # API layer returns) — the text shown to the user is the raw
                # provider error itself, not a paraphrased message.
                info = classify_provider_error(exc)
                return self._interrupted_result(
                    tool_calls_made,
                    reason=f"hit a problem: {strip_reset_marker(str(exc))}",
                    reason_code=info.reason,
                    reset_at=info.reset_at,
                )

            if not result.tool_calls:
                return ChatTurnResult(
                    reply=result.content or "",
                    tool_calls=tool_calls_made,
                )

            # Model wants to call tools before answering — run each, append
            # its result as a tool message, and loop back for the model's
            # next turn. Anthropic returns partial content alongside tool
            # calls sometimes; we only keep it if it's the final turn's
            # content (see the no-tool_calls branch above), so it's fine to
            # drop it here.
            messages.append(
                Message(
                    role="assistant",
                    content=result.content or "",
                    tool_calls=result.tool_calls,
                )
            )
            for call in result.tool_calls:
                if call.name in MUTATING_TOOLS and self._mutation_count(tool_calls_made) >= MAX_MUTATIONS_PER_TURN:
                    record = ToolCallRecord(
                        tool=call.name,
                        arguments=call.arguments,
                        result="",
                        error=(
                            f"Reached the limit of {MAX_MUTATIONS_PER_TURN} changes in one "
                            "message. Ask about the remaining tests separately, or confirm "
                            "you want this many changes made at once."
                        ),
                    )
                else:
                    record = await self._execute_tool(tool_ctx, call)
                tool_calls_made.append(record)
                messages.append(
                    Message(
                        role="tool",
                        content=record.result if record.error is None else f"Error: {record.error}",
                        tool_call_id=call.id,
                    )
                )

        return self._interrupted_result(
            tool_calls_made,
            f"ran out of tool-calling attempts after {MAX_TOOL_ITERATIONS} rounds without finishing",
        )

    @staticmethod
    def _mutation_count(tool_calls_made: list[ToolCallRecord]) -> int:
        return sum(1 for tc in tool_calls_made if tc.tool in MUTATING_TOOLS and tc.error is None)

    def _interrupted_result(
        self,
        tool_calls_made: list[ToolCallRecord],
        reason: str,
        reason_code: str = "unknown",
        reset_at: str | None = None,
    ) -> ChatTurnResult:
        """Build the reply for a turn that didn't reach a final answer.

        If any mutating tool succeeded before the interruption, that change
        is reported plainly instead of being lost behind a bare error —
        never silently drop a real, already-persisted change (see class
        docstring on send_message). Raises ChatAgentError only when nothing
        succeeded, since there is nothing to tell the user about.

        *reason_code*/*reset_at* are the shared classification (see
        app.ai.providers.errors) — threaded through to ChatAgentError so
        the API layer can return the same {message, reason, reset_at}
        shape test generation does, distinct from *reason*, the free-text
        clause embedded in the reply/exception message itself.
        """
        changes = [
            tc for tc in tool_calls_made if tc.tool in MUTATING_TOOLS and tc.error is None
        ]
        if not changes:
            raise ChatAgentError(f"Chat agent {reason}", reason=reason_code, reset_at=reset_at)

        change_descriptions = "; ".join(f"{tc.tool}({tc.arguments})" for tc in changes)
        reply = (
            f"I made this change: {change_descriptions}, but then {reason}. "
            f"You may want to check the result."
        )
        return ChatTurnResult(reply=reply, tool_calls=tool_calls_made)

    async def _execute_tool(self, tool_ctx: ToolContext, call: ToolCallRequest) -> ToolCallRecord:
        impl = TOOL_IMPLS.get(call.name)
        if impl is None:
            return ToolCallRecord(
                tool=call.name,
                arguments=call.arguments,
                result="",
                error=f"Unknown tool {call.name!r}",
            )
        try:
            output = await impl(tool_ctx, **call.arguments)
            return ToolCallRecord(
                tool=call.name,
                arguments=call.arguments,
                result=json.dumps(output, default=str),
            )
        except ToolError as exc:
            logger.info("chat tool %s rejected: %s", call.name, exc)
            return ToolCallRecord(
                tool=call.name, arguments=call.arguments, result="", error=str(exc)
            )
        except TypeError as exc:
            # Model called the tool with the wrong argument shape.
            logger.warning("chat tool %s called with bad arguments: %s", call.name, exc)
            return ToolCallRecord(
                tool=call.name, arguments=call.arguments, result="", error=f"Bad arguments: {exc}"
            )
