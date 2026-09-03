"""Deterministic enforcement classification for validations (Fix B — grounded
validations).

`enforcement` ('enforced' | 'advisory') is orthogonal to the existing
`severity` (CRITICAL | WARNING — app.ai.schemas.test_case.Severity): severity
says how much a check matters to a human reading it; enforcement says
whether the execution engine trusts the check's result enough to let it
decide the test's overall pass/fail verdict
(app.services.execution_engine.execute). The two are never merged and
neither is derived from the other — see app.ai.schemas.test_case.Validation,
which keeps them as two separate fields.

This classification is a pure, deterministic Python decision — never made by
the LLM. The model only supplies `grounding` per validation (at generation
time, via the structured-output schema); this module turns
(type, grounding) into `enforcement`, applied once and stamped onto the
validation dict wherever one is persisted (app.services.test_service).

Precedence (highest first) — see `classify_enforcement`:
1. The execution engine doesn't implement this validation type at all
   -> always advisory, regardless of grounding.
2. Contract-independent type (correct regardless of the response body's
   shape/content) -> always enforced.
3. Contract-dependent type (inspects the response body's content)
   -> enforced only when grounded in real evidence ('spec' or 'observed');
   'inferred' or missing grounding -> advisory.
"""

from __future__ import annotations

from typing import Any

from app.ai.schemas.test_case import ValidationType
from app.services.execution_engine import _SUPPORTED_VALIDATION_TYPES

ENFORCED = "enforced"
ADVISORY = "advisory"
_VALID_ENFORCEMENTS = frozenset({ENFORCED, ADVISORY})

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
    """Read a validation's stored `enforcement`, defaulting to 'enforced'
    for any missing/unrecognized value — including every validation
    persisted before this feature existed. This is what makes existing
    validations behave exactly as they do today.

    Note: this is the *stored* value, not necessarily the value actually
    used to decide a verdict — app.services.execution_engine additionally
    forces 'advisory' for any validation type it doesn't implement,
    regardless of what's stored (see its own local helper, kept
    self-contained there to avoid a circular import with this module).
    """
    value = validation.get("enforcement")
    return value if value in _VALID_ENFORCEMENTS else ENFORCED


def classify_enforcement(validation: dict[str, Any]) -> str:
    """Deterministically decide whether *validation* should be able to fail
    a test's overall verdict. See module docstring for the precedence
    rules. Called once, at the point a validation is first persisted
    (AI-generated or added via chat/PATCH) — see app.services.test_service.
    """
    v_type = validation.get("type")

    if v_type not in _SUPPORTED_VALIDATION_TYPES:
        return ADVISORY

    if v_type in CONTRACT_INDEPENDENT_TYPES:
        return ENFORCED

    return ENFORCED if get_grounding(validation) in _TRUSTED_GROUNDINGS else ADVISORY
