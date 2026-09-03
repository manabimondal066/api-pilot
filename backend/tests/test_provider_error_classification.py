"""Unit tests for the shared provider-error classifier
(app/ai/providers/errors.py) — the single place test generation and chat
both turn a raw provider failure into a reason code (+ reset time, when a
provider supplied one) and a plain-English message, per the Sprint 2
rate_limited/timeout/connection_error pattern extended with
quota_exhausted.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.ai.providers.errors import (
    ProviderErrorInfo,
    attach_reset_marker,
    classify_provider_error,
    extract_reset_at,
    plain_english_message,
)

# ---------------------------------------------------------------------------
# classify_provider_error — reason codes
# ---------------------------------------------------------------------------


def test_classifies_insufficient_quota_as_quota_exhausted() -> None:
    exc = Exception(
        "Error code: 429 - {'error': {'message': 'You exceeded your current "
        "quota, please check your plan and billing details.', "
        "'type': 'insufficient_quota', 'code': 'insufficient_quota'}}"
    )
    info = classify_provider_error(exc)
    assert info.reason == "quota_exhausted"
    assert info.reset_at is None


def test_classifies_credit_balance_too_low_as_quota_exhausted() -> None:
    exc = Exception("Your credit balance is too low to access the API. Add credits.")
    assert classify_provider_error(exc).reason == "quota_exhausted"


def test_429_without_quota_wording_still_classifies_as_rate_limited() -> None:
    """A plain 429 'too many requests' must not be confused with quota
    exhaustion just because both can carry HTTP 429 — this is the
    distinction the validation checklist calls out explicitly."""
    exc = Exception("Error code: 429 - {'status': 429, 'title': 'Too Many Requests'}")
    assert classify_provider_error(exc).reason == "rate_limited"


def test_classifies_rate_limit_phrase_as_rate_limited() -> None:
    exc = Exception("You have hit the rate limit for this API key")
    assert classify_provider_error(exc).reason == "rate_limited"


# Exact production error shape (Groq, model openai/gpt-oss-120b) that was
# misclassified as quota_exhausted. Root cause: extract_reset_at() finds
# the provider's short Retry-After header (825ms) and attach_reset_marker()
# appends "[quota_reset_at=<time>]" to the message for ANY error with a
# reset hint, not just genuine quota errors — and the literal substring
# "quota" inside "quota_reset_at" was tripping the quota keyword check.
_GROQ_SHORT_RATE_LIMIT_TEXT = (
    "Rate limit reached for model `openai/gpt-oss-120b`... on tokens per "
    "minute (TPM): Limit 8000, Used 4068, Requested 4042. Please try again "
    "in 825ms... code: rate_limit_exceeded"
)


def test_short_term_rate_limit_not_misclassified_as_quota_exhausted() -> None:
    """Regression test for the exact production error shape reported: a
    genuine short-term (sub-second) rate limit must classify as
    rate_limited, never quota_exhausted, whether or not it carries a raw
    message alone."""
    info = classify_provider_error(Exception(_GROQ_SHORT_RATE_LIMIT_TEXT))
    assert info.reason == "rate_limited"
    assert info.reason != "quota_exhausted"


def test_short_term_rate_limit_with_reset_marker_not_misclassified_as_quota() -> None:
    """Same production error, but with the reset-time marker attached the
    way it actually happens in production — extract_reset_at() found the
    provider's 825ms Retry-After header and attach_reset_marker() appended
    it to the message, which is what triggered the original misclassification
    (the marker's own text contains the substring "quota")."""
    with_marker = attach_reset_marker(
        _GROQ_SHORT_RATE_LIMIT_TEXT, "2026-09-02T00:00:00.825000+00:00"
    )
    info = classify_provider_error(Exception(with_marker))
    assert info.reason == "rate_limited"
    assert info.reason != "quota_exhausted"
    # reset_at is quota-specific — a rate_limited result never carries one,
    # even though the marker text was present in the raw exception.
    assert info.reset_at is None


def test_classifies_timeout() -> None:
    assert classify_provider_error(Exception("Request timed out.")).reason == "timeout"


def test_classifies_connection_error() -> None:
    exc = Exception("Connection error: could not connect to host")
    assert classify_provider_error(exc).reason == "connection_error"


def test_classifies_unrecognized_as_unknown() -> None:
    exc = Exception("Something exotic and unmapped happened")
    assert classify_provider_error(exc).reason == "unknown"


def test_classifies_groq_413_request_too_large_correctly() -> None:
    """The exact shape Groq returns in production: HTTP 413, message says
    'Request too large ... Requested X, Limit Y', but the JSON body's own
    `code` field is 'rate_limit_exceeded' — this must not be confused with
    rate_limited (retrying won't help; the request itself must shrink),
    and must not fall through to unknown."""
    exc = Exception(
        "Error code: 413 - {'error': {'message': 'Request too large for model "
        "`llama-3.3-70b-versatile` in organization `org_abc` service tier "
        "`on_demand` on tokens per minute (TPM): Limit 6000, Requested 8000, "
        "please reduce your message size and try again.', 'type': 'tokens', "
        "'code': 'rate_limit_exceeded'}}"
    )
    info = classify_provider_error(exc)
    assert info.reason == "request_too_large"
    assert info.reason != "rate_limited"
    assert info.reason != "unknown"


def test_classifies_payload_too_large_as_request_too_large() -> None:
    assert classify_provider_error(Exception("413 Payload Too Large")).reason == "request_too_large"


def test_request_too_large_distinct_from_quota_exhausted() -> None:
    """A 413 size error contains no quota/billing wording, so it must not
    be swept up by the quota_exhausted keyword check."""
    exc = Exception("Error code: 413 - Request too large: Requested 9000, Limit 6000")
    assert classify_provider_error(exc).reason == "request_too_large"


# ---------------------------------------------------------------------------
# reset_at is only ever surfaced when a provider implementation actually
# attached one — never guessed.
# ---------------------------------------------------------------------------


def test_quota_error_without_marker_has_no_reset_at() -> None:
    exc = Exception("insufficient_quota: You exceeded your current quota.")
    info = classify_provider_error(exc)
    assert info.reason == "quota_exhausted"
    assert info.reset_at is None


def test_quota_error_with_marker_surfaces_reset_at() -> None:
    message = attach_reset_marker(
        "LLM API error (nvidia_nim): quota exceeded", "2026-09-03T00:00:00+00:00"
    )
    info = classify_provider_error(Exception(message))
    assert info.reason == "quota_exhausted"
    assert info.reset_at == "2026-09-03T00:00:00+00:00"


def test_reset_marker_survives_being_wrapped_by_orchestration_error_text() -> None:
    """AIOrchestrationError/ChatAgentError both interpolate the underlying
    provider exception's text into their own message — the marker must
    still be found after that wrapping, since that's how classify_
    provider_error actually receives it in production (see
    app.services.test_service / app.ai.chat_service)."""
    inner = attach_reset_marker("quota exceeded", "2026-09-03T00:00:00+00:00")
    wrapped = Exception(f"generate_tests failed after 2 attempts: {inner}")
    info = classify_provider_error(wrapped)
    assert info.reason == "quota_exhausted"
    assert info.reset_at == "2026-09-03T00:00:00+00:00"


def test_attach_reset_marker_returns_message_unchanged_when_no_reset_at() -> None:
    assert attach_reset_marker("quota exceeded", None) == "quota exceeded"


# ---------------------------------------------------------------------------
# extract_reset_at — never fabricates; only reads what the provider supplied
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, headers: dict[str, str]):
        self.headers = headers


class _FakeSdkError(Exception):
    """Stands in for anthropic.APIStatusError / openai.APIStatusError —
    both expose `.response` (with `.headers`) and `.body` (parsed JSON
    error body) the same way."""

    def __init__(self, headers: dict[str, str] | None = None, body: dict | None = None):
        super().__init__("fake provider error")
        self.response = _FakeResponse(headers or {})
        self.body = body


def test_extract_reset_at_from_retry_after_seconds() -> None:
    before = datetime.now(timezone.utc)
    reset_at = extract_reset_at(_FakeSdkError(headers={"retry-after": "30"}))
    assert reset_at is not None
    parsed = datetime.fromisoformat(reset_at)
    assert 25 <= (parsed - before).total_seconds() <= 35


def test_extract_reset_at_from_body_field() -> None:
    exc = _FakeSdkError(body={"error": {"reset_at": "2026-09-03T00:00:00Z"}})
    assert extract_reset_at(exc) == "2026-09-03T00:00:00Z"


def test_extract_reset_at_returns_none_when_provider_gives_no_hint() -> None:
    exc = _FakeSdkError(headers={}, body={"error": {"message": "insufficient_quota"}})
    assert extract_reset_at(exc) is None


def test_extract_reset_at_returns_none_for_plain_exception() -> None:
    assert extract_reset_at(Exception("no response/body attributes at all")) is None


# ---------------------------------------------------------------------------
# plain_english_message — the standard sentence, per provider/reset_at
# ---------------------------------------------------------------------------


def test_quota_message_with_known_reset_time() -> None:
    info = ProviderErrorInfo(reason="quota_exhausted", reset_at="2026-09-03T00:00:00Z")
    msg = plain_english_message(info, "nvidia_nim")
    assert msg == (
        "You've used up the free AI quota for NVIDIA NIM. "
        "It resets at 2026-09-03T00:00:00Z."
    )


def test_quota_message_without_known_reset_time() -> None:
    info = ProviderErrorInfo(reason="quota_exhausted", reset_at=None)
    msg = plain_english_message(info, "anthropic")
    assert msg == (
        "You've used up the free AI quota for Anthropic. "
        "Try again later, or ask about switching to a different AI provider."
    )


def test_rate_limited_message_unaffected_by_quota_wording() -> None:
    info = ProviderErrorInfo(reason="rate_limited")
    msg = plain_english_message(info, "groq")
    assert "too many requests" in msg.lower()
    assert "quota" not in msg.lower()


def test_request_too_large_message() -> None:
    info = ProviderErrorInfo(reason="request_too_large")
    msg = plain_english_message(info, "groq")
    assert msg == (
        "This endpoint's definition is too large for the AI to process in one "
        "request. Try a smaller/simpler endpoint, or contact support if this "
        "keeps happening."
    )


def test_all_three_reasons_still_classify_correctly_together() -> None:
    """Fixing the marker-substring collision for rate_limited must not
    regress the other two reasons — each real-world example, with a reset
    marker attached where realistic, still lands on its own reason."""
    quota = classify_provider_error(
        Exception(
            attach_reset_marker(
                "insufficient_quota: You exceeded your current quota, please "
                "check your plan and billing details.",
                "2026-10-01T00:00:00Z",
            )
        )
    )
    rate_limited = classify_provider_error(
        Exception(attach_reset_marker(_GROQ_SHORT_RATE_LIMIT_TEXT, "2026-09-02T00:00:00.825000+00:00"))
    )
    request_too_large = classify_provider_error(
        Exception(
            "Error code: 413 - {'error': {'message': 'Request too large for model "
            "`llama-3.3-70b-versatile`... Limit 6000, Requested 8000.', "
            "'code': 'rate_limit_exceeded'}}"
        )
    )

    assert quota.reason == "quota_exhausted"
    assert quota.reset_at == "2026-10-01T00:00:00Z"
    assert rate_limited.reason == "rate_limited"
    assert rate_limited.reset_at is None
    assert request_too_large.reason == "request_too_large"

    assert len({quota.reason, rate_limited.reason, request_too_large.reason}) == 3


def test_three_reason_codes_produce_three_distinct_messages() -> None:
    """quota_exhausted, rate_limited, and request_too_large must never
    collapse to the same user-facing sentence."""
    quota_msg = plain_english_message(ProviderErrorInfo(reason="quota_exhausted"), "groq")
    rate_msg = plain_english_message(ProviderErrorInfo(reason="rate_limited"), "groq")
    size_msg = plain_english_message(ProviderErrorInfo(reason="request_too_large"), "groq")
    assert len({quota_msg, rate_msg, size_msg}) == 3
