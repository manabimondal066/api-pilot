"""Unit tests for the internal enforcement classifier — the safety net that
stops a guessed field name from producing a false "failed" test
(app/services/validation_enforcement.py). Pure functions, no DB, no AI.
"""

from __future__ import annotations

from app.services.validation_enforcement import (
    BINDING,
    INFORMATIONAL,
    classify_enforcement,
    get_enforcement,
    get_grounding,
)

# ---------------------------------------------------------------------------
# classify_enforcement — precedence: unimplemented type > contract-
# independent > grounding
# ---------------------------------------------------------------------------


def test_status_code_is_always_binding():
    assert classify_enforcement({"type": "STATUS_CODE"}) == BINDING


def test_status_code_is_binding_even_with_no_grounding():
    assert classify_enforcement({"type": "STATUS_CODE", "grounding": None}) == BINDING


def test_field_exists_grounded_in_spec_is_binding():
    assert classify_enforcement({"type": "FIELD_EXISTS", "grounding": "spec"}) == BINDING


def test_field_exists_grounded_in_observed_is_binding():
    assert classify_enforcement({"type": "FIELD_EXISTS", "grounding": "observed"}) == BINDING


def test_field_equals_grounded_in_inferred_is_informational():
    assert classify_enforcement({"type": "FIELD_EQUALS", "grounding": "inferred"}) == INFORMATIONAL


def test_field_exists_with_no_grounding_is_informational():
    assert classify_enforcement({"type": "FIELD_EXISTS"}) == INFORMATIONAL


def test_unimplemented_type_is_informational_even_when_grounded_in_spec():
    """Precedence rule: the engine can't evaluate RESPONSE_TIME at all, so
    even a fully-grounded validation of that type can never be binding —
    this overrides both the contract-independent rule and the grounding
    rule.
    """
    assert classify_enforcement({"type": "RESPONSE_TIME", "grounding": "spec"}) == INFORMATIONAL


def test_unimplemented_body_level_type_is_informational():
    for v_type in ("FIELD_TYPE", "FIELD_REGEX", "FIELD_RANGE", "SCHEMA_MATCH", "CUSTOM_JSONPATH"):
        assert classify_enforcement({"type": v_type, "grounding": "spec"}) == INFORMATIONAL


# ---------------------------------------------------------------------------
# get_enforcement / get_grounding — defaulting accessors
# ---------------------------------------------------------------------------


def test_get_enforcement_defaults_to_binding_when_absent():
    """Every validation persisted before this classification existed has no
    `enforcement` key at all — it must read as 'binding'."""
    assert get_enforcement({"type": "STATUS_CODE"}) == BINDING


def test_get_enforcement_defaults_to_binding_on_garbage_value():
    assert get_enforcement({"type": "STATUS_CODE", "enforcement": "nonsense"}) == BINDING


def test_get_enforcement_reads_stored_informational():
    assert get_enforcement({"type": "FIELD_EXISTS", "enforcement": "informational"}) == INFORMATIONAL


def test_get_grounding_defaults_to_none_when_absent():
    assert get_grounding({"type": "FIELD_EXISTS"}) is None


def test_get_grounding_defaults_to_none_on_garbage_value():
    assert get_grounding({"type": "FIELD_EXISTS", "grounding": "nonsense"}) is None


def test_get_grounding_reads_stored_value():
    assert get_grounding({"type": "FIELD_EXISTS", "grounding": "observed"}) == "observed"
