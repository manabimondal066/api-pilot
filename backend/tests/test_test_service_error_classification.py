"""Unit tests for the generation-error → reason-code classifier.

The user-facing message is the raw provider error text itself (see
generate_tests_for_endpoint); `reason` is kept separately for internal
classification/logging and for reason == "quota_exhausted" gating whether
reset_at/provider are meaningful.
"""

from app.services.test_service import _classify_generation_error


def test_classifies_429_as_rate_limited() -> None:
    exc = Exception("Error code: 429 - {'status': 429, 'title': 'Too Many Requests'}")
    assert _classify_generation_error(exc) == "rate_limited"


def test_classifies_rate_limit_phrase_as_rate_limited() -> None:
    exc = Exception("You have hit the rate limit for this API key")
    assert _classify_generation_error(exc) == "rate_limited"


def test_classifies_timeout_as_timeout() -> None:
    exc = Exception("Request timed out.")
    assert _classify_generation_error(exc) == "timeout"


def test_classifies_connection_error_as_connection_error() -> None:
    exc = Exception("Connection error: could not connect to host")
    assert _classify_generation_error(exc) == "connection_error"


def test_classifies_unrecognized_error_as_unknown() -> None:
    exc = Exception("Something exotic and unmapped happened")
    assert _classify_generation_error(exc) == "unknown"


def test_classifies_missing_api_key_as_unknown() -> None:
    exc = Exception("NVIDIA_API_KEY not set. Get a free key at the provider's website.")
    assert _classify_generation_error(exc) == "unknown"


def test_classifies_insufficient_quota_as_quota_exhausted() -> None:
    exc = Exception(
        "Error code: 429 - {'error': {'message': 'You exceeded your current quota, "
        "please check your plan and billing details.', 'type': 'insufficient_quota'}}"
    )
    assert _classify_generation_error(exc) == "quota_exhausted"


def test_classifies_429_too_many_requests_as_rate_limited_not_quota() -> None:
    """A short-term 429 must not be confused with quota exhaustion just
    because both can carry HTTP 429 — see docstring on
    app.ai.providers.errors.classify_provider_error."""
    exc = Exception("Error code: 429 - {'status': 429, 'title': 'Too Many Requests'}")
    assert _classify_generation_error(exc) == "rate_limited"


def test_classifies_short_term_rate_limit_not_as_quota_exhausted() -> None:
    """Regression test for the exact production error shape that was
    misclassified: a short-term (825ms) Groq rate limit, with the
    reset-time marker attached the way it actually happens in production
    (see app.ai.providers.errors.classify_provider_error docstring) —
    must classify as rate_limited, not quota_exhausted."""
    from app.ai.providers.errors import attach_reset_marker

    raw = (
        "Rate limit reached for model `openai/gpt-oss-120b`... on tokens per "
        "minute (TPM): Limit 8000, Used 4068, Requested 4042. Please try "
        "again in 825ms... code: rate_limit_exceeded"
    )
    with_marker = attach_reset_marker(raw, "2026-09-02T00:00:00.825000+00:00")
    exc = Exception(with_marker)
    assert _classify_generation_error(exc) == "rate_limited"


def test_classifies_groq_413_request_too_large_not_unknown() -> None:
    """Previously fell through to 'unknown' — this is the gap the
    validation checklist calls out by name."""
    exc = Exception(
        "Error code: 413 - {'error': {'message': 'Request too large for model "
        "`llama-3.3-70b-versatile`... on tokens per minute (TPM): Limit 6000, "
        "Requested 8000.', 'type': 'tokens', 'code': 'rate_limit_exceeded'}}"
    )
    assert _classify_generation_error(exc) == "request_too_large"
