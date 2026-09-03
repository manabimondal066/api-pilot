"""Internal enforcement classification for validations — a safety net that
stops a guessed field name from ever producing a false "failed" test.

`enforcement` ('binding' | 'informational') is orthogonal to the existing
`severity` (CRITICAL | WARNING — app.ai.schemas.test_case.Severity): severity
says how much a check matters to a human reading it; enforcement says
whether the execution engine trusts the check's result enough to let it
decide the test's overall pass/fail verdict
(app.services.execution_engine.execute). The two are never merged and
neither is derived from the other — see app.ai.schemas.test_case.Validation,
which keeps them as two separate fields.

This is purely internal/backend bookkeeping — never shown to the user as a
third status (the verdict stays plain passed/failed) and never exposed as
"advisory"/"inconclusive" anywhere. The one user-visible trace of it is a
small note in the test detail panel on a validation that didn't count.

This classification is a pure, deterministic Python decision — never made by
the LLM. The model only supplies `grounding` per validation (at generation
time, via the structured-output schema); this module turns
(type, grounding) into `enforcement` for AI-generated validations, applied
once and stamped on at persistence time
(app.services.test_service.generate_tests_for_endpoint). A validation added
directly by a user or the chat assistant (test_service.add_validation) is
always stamped 'binding' regardless of type/grounding — the classifier is
not run on it, because a check someone explicitly asked for must always
count.

Precedence (highest first) — see `classify_enforcement`:
1. The execution engine doesn't implement this validation type at all
   -> always informational, regardless of grounding.
2. Contract-independent type (correct regardless of the response body's
   shape/content) -> always binding.
3. Contract-dependent type (inspects the response body's content)
   -> binding only when grounded in real evidence ('spec' or 'observed');
   'inferred' or missing grounding -> informational.
"""

from __future__ import annotations

from typing import Any

from app.ai.schemas.test_case import ValidationType
from app.services.execution_engine import _SUPPORTED_VALIDATION_TYPES

BINDING = "binding"
INFORMATIONAL = "informational"
_VALID_ENFORCEMENTS = frozenset({BINDING, INFORMATIONAL})

GROUNDING_SPEC = "spec"
GROUNDING_OBSERVED = "observed"
GROUNDING_INFERRED = "inferred"
_VALID_GROUNDINGS = frozenset({GROUNDING_SPEC, GROUNDING_OBSERVED, GROUNDING_INFERRED})
_TRUSTED_GROUNDINGS = frozenset({GROUNDING_SPEC, GROUNDING_OBSERVED})

# Validation types that are correct regardless of the API's response body
# shape/content — status code and latency don't depend on what a documented
# schema (or an observed response) says the body looks like.
CONTRACT_INDEPENDENT_TYPES = frozenset({"STATUS_CODE", "RESPONSE_TIME"})

# Every other known validation type inspects the response body's content —
# field existence/equality/type/pattern/range, schema match, or a raw
# JSONPath expression — so its correctness depends on the field names/shape
# it references actually being real (i.e. on grounding). Derived from the
# ValidationType enum rather than hard-coded, so a new type added there is
# contract-dependent by default (the safe direction) until explicitly
# classified otherwise.
BODY_LEVEL_TYPES = frozenset(t.value for t in ValidationType) - CONTRACT_INDEPENDENT_TYPES


def get_grounding(validation: dict[str, Any]) -> str | None:
    """Read a validation's stored `grounding`, defaulting to None for any
    missing/unrecognized value — including every validation persisted
    before this feature existed."""
    value = validation.get("grounding")
    return value if value in _VALID_GROUNDINGS else None


def get_enforcement(validation: dict[str, Any]) -> str:
    """Read a validation's stored `enforcement`, defaulting to 'binding'
    for any missing/unrecognized value — including every validation
    persisted before this feature existed. This is what makes existing
    validations behave exactly as they do today.

    Note: this is the *stored* value, not necessarily the value actually
    used to decide a verdict — app.services.execution_engine additionally
    forces 'informational' for any validation type it doesn't implement,
    regardless of what's stored (see its own local helper, kept
    self-contained there to avoid a circular import with this module).
    """
    value = validation.get("enforcement")
    return value if value in _VALID_ENFORCEMENTS else BINDING


def classify_enforcement(validation: dict[str, Any]) -> str:
    """Deterministically decide whether *validation* should be able to fail
    a test's overall verdict. See module docstring for the precedence
    rules. Called only for AI-generated validations, at the point they are
    first persisted — see app.services.test_service.generate_tests_for_endpoint.
    Never called for a user/chat-added validation (test_service.add_validation
    always stamps 'binding' directly).
    """
    v_type = validation.get("type")

    if v_type not in _SUPPORTED_VALIDATION_TYPES:
        return INFORMATIONAL

    if v_type in CONTRACT_INDEPENDENT_TYPES:
        return BINDING

    return BINDING if get_grounding(validation) in _TRUSTED_GROUNDINGS else INFORMATIONAL
