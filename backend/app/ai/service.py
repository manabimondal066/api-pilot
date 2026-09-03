"""AI Orchestration Service — the single entry point for any module needing AI.

Per Implementation Plan §11.4: this is a facade over the LLM provider, owning
prompts, output parsing, retries, and (future) provider selection.
"""

import logging
from typing import Any

from app.ai.prompts.test_generation import (
    PROMPT_VERSION,
    SYSTEM_PROMPT,
    build_observed_response_block,
    build_user_prompt,
)
from app.ai.providers.base import LLMProvider, LLMProviderError
from app.ai.providers.factory import get_llm_provider
from app.ai.schemas.test_case import TestCase, TestCaseList
from app.parsers.models import ParsedEndpoint
from app.services.validation_enforcement import (
    BINDING,
    BODY_LEVEL_TYPES,
    classify_enforcement,
)

logger = logging.getLogger(__name__)


class AIOrchestrationError(Exception):
    """Raised when an AI orchestration step fails after retries."""


class AIOrchestrationService:
    """Facade for AI operations. One instance per request/job is fine."""

    def __init__(self, provider: LLMProvider | None = None):
        self._provider = provider or get_llm_provider()

    @property
    def prompt_version(self) -> str:
        return PROMPT_VERSION

    async def generate_tests(
        self,
        endpoint: ParsedEndpoint,
        endpoint_id: str | None = None,
        max_retries: int = 1,
        observed_status: int | None = None,
        observed_body: str | None = None,
    ) -> list[TestCase]:
        """Generate test cases for one endpoint.

        *observed_status*/*observed_body* (Phase B — probe-grounded
        generation): when both are given, a clearly-delimited block
        describing the real observed response is appended to the user
        prompt (app.ai.prompts.test_generation.build_observed_response_block).
        When either is None (the default — no probe, or a probe that
        failed), the prompt is exactly `build_user_prompt(endpoint)`, byte
        for byte, same as before this parameter existed.

        Returns:
            List of TestCase objects with endpoint_id populated.

        Raises:
            AIOrchestrationError: if all retry attempts fail.
        """
        user_prompt = build_user_prompt(endpoint)
        if observed_status is not None and observed_body is not None:
            user_prompt = f"{user_prompt}\n{build_observed_response_block(observed_status, observed_body)}"
        last_error: Exception | None = None

        for attempt in range(max_retries + 1):
            try:
                logger.info(
                    "generate_tests: endpoint=%s %s attempt=%d/%d prompt_version=%s",
                    endpoint.method.value,
                    endpoint.path,
                    attempt + 1,
                    max_retries + 1,
                    PROMPT_VERSION,
                )
                result = await self._provider.generate_structured(
                    prompt=user_prompt,
                    schema=TestCaseList,
                    system=SYSTEM_PROMPT,
                    max_tokens=8192,
                )
                tests = self._post_process(result, endpoint_id)
                if not tests:
                    raise AIOrchestrationError(
                        "AI returned zero tests for endpoint"
                    )
                logger.info(
                    "generate_tests: returned %d tests for %s %s",
                    len(tests),
                    endpoint.method.value,
                    endpoint.path,
                )
                return tests

            except LLMProviderError as e:
                last_error = e
                logger.warning(
                    "generate_tests: LLM error on attempt %d: %s", attempt + 1, e
                )
                continue
            except (AIOrchestrationError, ValueError) as e:
                last_error = e
                logger.warning(
                    "generate_tests: validation error on attempt %d: %s",
                    attempt + 1,
                    e,
                )
                continue

        raise AIOrchestrationError(
            f"generate_tests failed after {max_retries + 1} attempts for "
            f"{endpoint.method.value} {endpoint.path}: {last_error}"
        ) from last_error

    def _post_process(
        self, result: Any, endpoint_id: str | None
    ) -> list[TestCase]:
        """Validate AI output and apply post-generation fixes."""
        if not isinstance(result, TestCaseList):
            raise AIOrchestrationError(
                f"Expected TestCaseList, got {type(result).__name__}"
            )
        tests = result.tests
        for t in tests:
            if endpoint_id is not None:
                t.endpoint_id = endpoint_id
            # Defensive: ensure at least one validation per test
            if not t.validations:
                raise AIOrchestrationError(
                    f"Test {t.name!r} has no validations — AI output is incomplete"
                )
            # A body-level validation with no `grounding` is a guess — that's
            # expected and fine (it's how a suite with no documented schema
            # or observed response gets any body-level coverage at all), so
            # this is a warning, not a generation failure. classify_enforcement
            # already keeps a guessed field from ever failing a test on its
            # own (see app.services.validation_enforcement).
            for v in t.validations:
                if v.type.value in BODY_LEVEL_TYPES and v.grounding is None:
                    logger.warning(
                        "generate_tests: test %r for endpoint=%s validation %r "
                        "inspects the response body with no grounding set — "
                        "treating it as a guess (informational, can't fail the test)",
                        t.name,
                        endpoint_id,
                        v.description,
                    )
            # Diagnostic only: a test whose validations are all informational
            # can never report 'failed' — not wrong, but worth knowing about.
            # Never drops the test or fabricates a validation.
            enforcements = [classify_enforcement(v.model_dump(mode="json")) for v in t.validations]
            if BINDING not in enforcements:
                logger.warning(
                    "generate_tests: test %r for endpoint=%s has zero binding "
                    "validations (all %d are informational) — its verdict can "
                    "never be 'failed'",
                    t.name,
                    endpoint_id,
                    len(t.validations),
                )
        return tests
