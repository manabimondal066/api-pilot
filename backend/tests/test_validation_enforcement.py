"""Unit tests for the deterministic enforcement classifier (Fix B —
app/services/validation_enforcement.py). Pure functions, no DB, no AI.
"""

from __future__ import annotations

from app.services.validation_enforcement import (
    ADVISORY,
    ENFORCED,
    classify_enforcement,
    get_enforcement,
    get_grounding,
)

# ---------------------------------------------------------------------------
# classify_enforcement — precedence: unimplemented type > contract-
# independent > grounding
# ---------------------------------------------------------------------------


def test_status_code_is_always_enforced():
    assert classify_enforcement({"type": "STATUS_CODE"}) == ENFORCED


def test_status_code_is_enforced_even_with_no_grounding():
    assert classify_enforcement({"type": "STATUS_CODE", "grounding": None}) == ENFORCED


def test_field_exists_grounded_in_spec_is_enforced():
    assert classify_enforcement({"type": "FIELD_EXISTS", "grounding": "spec"}) == ENFORCED


def test_field_exists_grounded_in_observed_is_enforced():
    assert classify_enforcement({"type": "FIELD_EXISTS", "grounding": "observed"}) == ENFORCED


def test_field_equals_grounded_in_inferred_is_advisory():
    assert classify_enforcement({"type": "FIELD_EQUALS", "grounding": "inferred"}) == ADVISORY


def test_field_exists_with_no_grounding_is_advisory():
    assert classify_enforcement({"type": "FIELD_EXISTS"}) == ADVISORY


def test_unimplemented_type_is_advisory_even_when_grounded_in_spec():
    """Precedence rule (item 7): the engine can't evaluate RESPONSE_TIME at
    all, so even a fully-grounded validation of that type can never be
    enforced — this overrides both the contract-independent rule and the
    grounding rule.
    """
    assert classify_enforcement({"type": "RESPONSE_TIME", "grounding": "spec"}) == ADVISORY


def test_unimplemented_body_level_type_is_advisory():
    for v_type in ("FIELD_TYPE", "FIELD_REGEX", "FIELD_RANGE", "SCHEMA_MATCH", "CUSTOM_JSONPATH"):
        assert classify_enforcement({"type": v_type, "grounding": "spec"}) == ADVISORY


# ---------------------------------------------------------------------------
# get_enforcement / get_grounding — defaulting accessors
# ---------------------------------------------------------------------------


def test_get_enforcement_defaults_to_enforced_when_absent():
    """Every validation persisted before this feature existed has no
    `enforcement` key at all — it must read as 'enforced'."""
    assert get_enforcement({"type": "STATUS_CODE"}) == ENFORCED


def test_get_enforcement_defaults_to_enforced_on_garbage_value():
    assert get_enforcement({"type": "STATUS_CODE", "enforcement": "nonsense"}) == ENFORCED


def test_get_enforcement_reads_stored_advisory():
    assert get_enforcement({"type": "FIELD_EXISTS", "enforcement": "advisory"}) == ADVISORY


def test_get_grounding_defaults_to_none_when_absent():
    assert get_grounding({"type": "FIELD_EXISTS"}) is None


def test_get_grounding_defaults_to_none_on_garbage_value():
    assert get_grounding({"type": "FIELD_EXISTS", "grounding": "nonsense"}) is None


def test_get_grounding_reads_stored_value():
    assert get_grounding({"type": "FIELD_EXISTS", "grounding": "observed"}) == "observed"
