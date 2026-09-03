"""Shared classification of AI-provider failures into short reason codes
and the standard plain-English message shown to the user.

Test generation (app.services.test_service) and chat
(app.ai.chat_service) each wrap a raw LLMProviderError differently
(AIOrchestrationError retries then wraps it; ChatAgentService interrupts a
tool-calling turn), but both ultimately need the same answer: "why did the
AI call fail, in one word, and what should the user be told?" This module
is that one shared place, so the mapping isn't reinvented per feature.

Reason codes
------------
"quota_exhausted"    — the free tier's daily/monthly allowance is fully
                        used up. Distinct from "rate_limited": retrying in
                        a few seconds will not help — the quota resets on
                        the provider's own schedule, or not until billing
                        info is added.
"rate_limited"        — too many requests happening too quickly; usually
                        resolves within seconds (HTTP 429, "too many
                        requests").
"request_too_large"   — a SINGLE request exceeds the provider's
                        per-request/per-minute token limit on its own
                        (HTTP 413, e.g. Groq's "Request too large ...
                        Requested X, Limit Y"). Distinct from
                        "rate_limited": retrying won't help — the request
                        itself has to shrink. Some providers (Groq
                        included) label this error internally as a
                        "rate_limit_exceeded" code despite returning 413,
                        which is exactly why this is classified before the
                        rate_limited check below, not folded into it.
"timeout"             — the provider took too long to respond.
"connection_error"    — couldn't reach the provider at all.
"unknown"             — anything else (bad API key, malformed output, ...).

Reset-time handling
--------------------
Some providers include a quota/rate-limit reset time in their error
response (a header or a body field); many don't. `reset_at` on
ProviderErrorInfo is None unless a provider implementation actually found
one in the raw SDK exception (see extract_reset_at / attach_reset_marker
and app.ai.providers.{anthropic,openai_compatible}_provider) — this module
never computes or guesses a reset time itself, except for converting a
provider-supplied `Retry-After: <seconds>` header into an absolute UTC
timestamp, which is arithmetic on a value the provider did supply, not a
guess.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

# Machine-parseable marker a provider implementation appends to an
# LLMProviderError's message when it found a real reset time in the SDK
# exception's headers/body. AIOrchestrationError and ChatAgentService's
# interrupted-turn message both interpolate the underlying exception's text
# into their own message, so this marker survives being wrapped and is
# still findable by classify_provider_error however deep the wrapping goes.
_RESET_MARKER_RE = re.compile(r"\[quota_reset_at=([^\]]+)\]")

# Broad but not overeager: "quota" alone catches "insufficient_quota",
# "quota exceeded", "exceeded your current quota", "monthly quota", etc.
# Deliberately does NOT include a bare "limit" — "rate limit" would
# otherwise misclassify as quota_exhausted.
_QUOTA_KEYWORDS = (
    "quota",
    "credit balance",
    "out of credits",
    "billing hard limit",
    "free tier limit",
    "usage limit exceeded",
    "exceeded your plan",
)

# HTTP 413 is the reliable signal here — some providers (Groq included)
# still stamp an internal "rate_limit_exceeded"-style code on this error
# even though it's fundamentally about one request's size, not pacing, so
# this check must run before the rate_limited check, not rely on the code
# field to disambiguate.
_REQUEST_TOO_LARGE_KEYWORDS = (
    "413",
    "request too large",
    "payload too large",
)

PROVIDER_DISPLAY_NAMES: dict[str, str] = {
    "nvidia_nim": "NVIDIA NIM",
    "groq": "Groq",
    "gemini": "Gemini",
    "openai": "OpenAI",
    "anthropic": "Anthropic",
    "mock": "the AI provider",
}


def display_provider_name(provider: str) -> str:
    """Human-friendly name for a provider code, e.g. "nvidia_nim" -> "NVIDIA NIM"."""
    return PROVIDER_DISPLAY_NAMES.get(provider, provider)


@dataclass(frozen=True)
class ProviderErrorInfo:
    reason: str
    reset_at: str | None = None


def attach_reset_marker(message: str, reset_at: str | None) -> str:
    """Append a machine-parseable reset-time marker to *message*.

    *reset_at* must be a value the provider's own error response actually
    supplied (a header or body field, or arithmetic on one) — never a
    computed/guessed value with no basis in the response. If None,
    *message* is returned unchanged.
    """
    if not reset_at:
        return message
    return f"{message} [quota_reset_at={reset_at}]"


def _header_get(headers: Any, key: str) -> str | None:
    getter = getattr(headers, "get", None)
    if callable(getter):
        value = getter(key)
        return value if value else None
    try:
        return headers[key]
    except (KeyError, TypeError):
        return None


def extract_reset_at(sdk_exc: Exception) -> str | None:
    """Best-effort extraction of a provider-supplied quota/rate-limit reset
    time from a raw SDK exception's response headers or error body.

    Returns None unless the provider's own response actually included one.
    The only computation performed is converting a `Retry-After: <seconds>`
    header into an absolute UTC timestamp — the provider did supply that
    number, this just makes it absolute. Nothing here invents a reset time
    when the provider gave no indication of one.
    """
    response = getattr(sdk_exc, "response", None)
    headers = getattr(response, "headers", None)
    if headers:
        retry_after = _header_get(headers, "retry-after")
        if retry_after is not None:
            try:
                seconds = float(retry_after)
            except (TypeError, ValueError):
                seconds = None
            if seconds is not None:
                reset_dt = datetime.now(timezone.utc) + timedelta(seconds=seconds)
                return reset_dt.isoformat()

        for header_name in ("x-ratelimit-reset-at", "x-quota-reset-at"):
            value = _header_get(headers, header_name)
            if value:
                return value

    body = getattr(sdk_exc, "body", None)
    if isinstance(body, dict):
        candidates = [body]
        error = body.get("error")
        if isinstance(error, dict):
            candidates.append(error)
        for candidate in candidates:
            for key in ("reset_at", "quota_reset_at", "resets_at", "reset_time"):
                value = candidate.get(key)
                if value:
                    return str(value)

    return None


def strip_reset_marker(message: str) -> str:
    """Remove the machine-readable reset-time marker (see
    attach_reset_marker) from a raw provider error message before showing
    it to the user.

    The marker is metadata this codebase appends to the exception text so
    classify_provider_error can recover a reset time later — it is not
    something the provider itself said, so it has no place in a "show the
    real message, unmodified" user-facing string. reset_at is already
    surfaced separately (ProviderErrorInfo.reset_at / TestGenerationError.
    reset_at / ChatAgentError.reset_at) for anything that needs it.
    """
    return _RESET_MARKER_RE.sub("", message).strip()


def classify_provider_error(exc: Exception) -> ProviderErrorInfo:
    """Classify a provider/orchestration exception into a reason code
    (+ reset time, if a provider implementation found and attached one).

    Operates on str(exc) — AIOrchestrationError and ChatAgentService's
    interrupted-turn message both interpolate the underlying provider
    exception's text into their own message, so this works whether *exc*
    is the raw LLMProviderError or something that wraps it.
    """
    text = str(exc)

    reset_match = _RESET_MARKER_RE.search(text)
    reset_at = reset_match.group(1) if reset_match else None

    # The reset marker is machine-appended by attach_reset_marker() for ANY
    # provider error that carries a reset/retry-after hint — including a
    # perfectly ordinary short-term rate limit with a `Retry-After: 0.8`
    # header, not just genuine quota exhaustion. Its own literal text
    # ("quota_reset_at") contains the substring "quota", which would
    # otherwise trip the quota keyword check below on any rate-limited
    # error that happened to get a reset time attached. Strip it before
    # reason-keyword matching; reset_at itself was already captured above.
    classification_text = _RESET_MARKER_RE.sub("", text)
    lower = classification_text.lower()

    if any(keyword in lower for keyword in _QUOTA_KEYWORDS):
        return ProviderErrorInfo(reason="quota_exhausted", reset_at=reset_at)
    if any(keyword in lower for keyword in _REQUEST_TOO_LARGE_KEYWORDS):
        return ProviderErrorInfo(reason="request_too_large")
    if "429" in lower or "too many requests" in lower or "rate limit" in lower:
        return ProviderErrorInfo(reason="rate_limited")
    if "timed out" in lower or "timeout" in lower:
        return ProviderErrorInfo(reason="timeout")
    if "connection" in lower or "connect error" in lower or "network" in lower:
        return ProviderErrorInfo(reason="connection_error")
    return ProviderErrorInfo(reason="unknown")


def plain_english_message(info: ProviderErrorInfo, provider: str) -> str:
    """The standard, user-facing sentence for one classified failure.

    Both test generation (surfaced via reason/reset_at/provider to the
    frontend, which mirrors this wording — see
    frontend/src/components/EndpointTests.tsx) and chat (which embeds this
    text directly into its reply — see app.ai.chat_service) show the same
    message for the same reason code, so it isn't reinvented per feature.
    """
    name = display_provider_name(provider)
    if info.reason == "quota_exhausted":
        base = f"You've used up the free AI quota for {name}."
        if info.reset_at:
            return f"{base} It resets at {info.reset_at}."
        return f"{base} Try again later, or ask about switching to a different AI provider."
    if info.reason == "rate_limited":
        return (
            "The AI service says you've made too many requests. "
            "Wait a few minutes and try again."
        )
    if info.reason == "request_too_large":
        return (
            "This endpoint's definition is too large for the AI to process in one "
            "request. Try a smaller/simpler endpoint, or contact support if this "
            "keeps happening."
        )
    if info.reason == "timeout":
        return "The AI took too long to respond. Try again."
    if info.reason == "connection_error":
        return "Couldn't reach the AI service. Check your internet connection and try again."
    return "Something went wrong talking to the AI. Try again, or ask for help if it keeps happening."
