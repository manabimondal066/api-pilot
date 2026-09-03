import pytest

from app.ai.providers.mock_provider import MockProvider
from app.ai.schemas.test_case import (
    Grounding,
    Severity,
    TestCase,
    TestCaseList,
    TestCategory,
    Validation,
    ValidationType,
)
from app.ai.service import AIOrchestrationError, AIOrchestrationService
from app.parsers.enums import HttpMethod, ParamLocation
from app.parsers.models import Param, ParsedEndpoint


def _make_endpoint() -> ParsedEndpoint:
    return ParsedEndpoint(
        method=HttpMethod.POST,
        path="/users",
        name="createUser",
        description="Create a new user",
        path_params=[],
        query_params=[],
        headers=[],
        body_schema={
            "type": "object",
            "required": ["email", "name"],
            "properties": {
                "email": {"type": "string", "format": "email"},
                "name": {"type": "string"},
            },
        },
        response_schemas={
            201: {
                "type": "object",
                "properties": {"id": {"type": "string"}, "email": {"type": "string"}},
            }
        },
        auth=None,
        tags=["users"],
    )


def _make_seeded_response() -> TestCaseList:
    return TestCaseList(
        tests=[
            TestCase(
                name="Create user with valid input returns 201",
                category=TestCategory.POSITIVE,
                description="Happy path",
                method=HttpMethod.POST,
                path="/users",
                body={"email": "test@example.com", "name": "Test User"},
                validations=[
                    Validation(
                        type=ValidationType.STATUS_CODE,
                        description="Status code is 201",
                        expected=201,
                        severity=Severity.CRITICAL,
                    ),
                    Validation(
                        type=ValidationType.FIELD_EXISTS,
                        description="Response has user id",
                        target="$.id",
                        severity=Severity.CRITICAL,
                        grounding=Grounding.SPEC,
                    ),
                ],
                confidence=0.9,
            ),
            TestCase(
                name="Create user with missing email returns 400",
                category=TestCategory.NEGATIVE,
                description="Missing required field",
                method=HttpMethod.POST,
                path="/users",
                body={"name": "Test User"},
                validations=[
                    Validation(
                        type=ValidationType.STATUS_CODE,
                        description="Status code is 400",
                        expected=400,
                        severity=Severity.CRITICAL,
                    ),
                ],
                confidence=0.85,
            ),
        ],
    )


async def test_generate_tests_returns_test_cases():
    provider = MockProvider()
    provider.seed_structured(TestCaseList, _make_seeded_response())
    service = AIOrchestrationService(provider=provider)

    tests = await service.generate_tests(_make_endpoint())

    assert len(tests) == 2
    assert all(isinstance(t, TestCase) for t in tests)
    assert tests[0].category == TestCategory.POSITIVE
    assert tests[1].category == TestCategory.NEGATIVE


async def test_generate_tests_assigns_endpoint_id():
    provider = MockProvider()
    provider.seed_structured(TestCaseList, _make_seeded_response())
    service = AIOrchestrationService(provider=provider)

    endpoint_id = "ep-123"
    tests = await service.generate_tests(_make_endpoint(), endpoint_id=endpoint_id)

    assert all(t.endpoint_id == endpoint_id for t in tests)


async def test_generate_tests_records_call_to_provider():
    provider = MockProvider()
    provider.seed_structured(TestCaseList, _make_seeded_response())
    service = AIOrchestrationService(provider=provider)

    await service.generate_tests(_make_endpoint())

    assert len(provider.calls) == 1
    call = provider.calls[0]
    assert call["method"] == "generate_structured"
    assert call["schema"] == "TestCaseList"
    assert "createUser" in call["prompt"]
    assert "POST" in call["prompt"]
    assert "/users" in call["prompt"]
    assert call["system"] is not None
    assert "POSITIVE" in call["system"]


async def test_generate_tests_raises_on_empty_response():
    provider = MockProvider()
    provider.seed_structured(TestCaseList, TestCaseList(tests=[]))
    service = AIOrchestrationService(provider=provider)

    with pytest.raises(AIOrchestrationError, match="zero tests"):
        await service.generate_tests(_make_endpoint(), max_retries=0)


async def test_generate_tests_raises_on_test_with_no_validations():
    bad_response = TestCaseList(
        tests=[
            TestCase(
                name="Bad test",
                category=TestCategory.POSITIVE,
                description="Has no validations",
                method=HttpMethod.GET,
                path="/users",
                validations=[],
            )
        ]
    )
    provider = MockProvider()
    provider.seed_structured(TestCaseList, bad_response)
    service = AIOrchestrationService(provider=provider)

    with pytest.raises(AIOrchestrationError, match="no validations"):
        await service.generate_tests(_make_endpoint(), max_retries=0)


async def test_generate_tests_treats_missing_grounding_as_a_guess_not_an_error(caplog):
    """A body-level validation (FIELD_EXISTS here) with no `grounding` is a
    guess — that's fine, generation must still succeed (never raise, never
    drop the test), but a warning is logged. The guessed validation is
    persisted as informational so it can't fail the test on its own — see
    app/services/validation_enforcement.py.
    """
    response = TestCaseList(
        tests=[
            TestCase(
                name="Create user with valid input returns 201",
                category=TestCategory.POSITIVE,
                description="Happy path",
                method=HttpMethod.POST,
                path="/users",
                validations=[
                    Validation(
                        type=ValidationType.STATUS_CODE,
                        description="Status code is 201",
                        expected=201,
                    ),
                    Validation(
                        type=ValidationType.FIELD_EXISTS,
                        description="Response has user id",
                        target="$.id",
                        # grounding deliberately omitted
                    ),
                ],
            )
        ]
    )
    provider = MockProvider()
    provider.seed_structured(TestCaseList, response)
    service = AIOrchestrationService(provider=provider)

    with caplog.at_level("WARNING"):
        tests = await service.generate_tests(_make_endpoint(), max_retries=0)

    assert len(tests) == 1
    assert any("no grounding set" in record.message for record in caplog.records)


async def test_generate_tests_allows_status_code_only_test_without_grounding():
    """STATUS_CODE doesn't inspect the response body, so it never needs
    `grounding` — only body-level types do."""
    response = TestCaseList(
        tests=[
            TestCase(
                name="Create user with missing email returns 400",
                category=TestCategory.NEGATIVE,
                description="Missing required field",
                method=HttpMethod.POST,
                path="/users",
                validations=[
                    Validation(
                        type=ValidationType.STATUS_CODE,
                        description="Status code is 400",
                        expected=400,
                    ),
                ],
            )
        ]
    )
    provider = MockProvider()
    provider.seed_structured(TestCaseList, response)
    service = AIOrchestrationService(provider=provider)

    tests = await service.generate_tests(_make_endpoint(), max_retries=0)
    assert len(tests) == 1


async def test_generate_tests_warns_on_test_with_zero_binding_validations(caplog):
    """A test whose only validation is an inferred (therefore informational)
    body-level check ends up with no binding validation at all —
    generation must still succeed (never drop the test or fabricate a
    validation), but a warning is logged naming the test.
    """
    response = TestCaseList(
        tests=[
            TestCase(
                name="Create user returns a token",
                category=TestCategory.POSITIVE,
                description="Happy path",
                method=HttpMethod.POST,
                path="/users",
                validations=[
                    Validation(
                        type=ValidationType.FIELD_EXISTS,
                        description="Response has a token",
                        target="$.token",
                        grounding=Grounding.INFERRED,
                    ),
                ],
            )
        ]
    )
    provider = MockProvider()
    provider.seed_structured(TestCaseList, response)
    service = AIOrchestrationService(provider=provider)

    with caplog.at_level("WARNING"):
        tests = await service.generate_tests(_make_endpoint(), max_retries=0)

    assert len(tests) == 1
    assert any(
        "zero binding validations" in record.message
        and "Create user returns a token" in record.message
        for record in caplog.records
    )


async def test_prompt_version_is_exposed():
    service = AIOrchestrationService(provider=MockProvider())
    assert service.prompt_version
    assert "." in service.prompt_version


async def test_user_prompt_includes_required_fields():
    from app.ai.prompts.test_generation import build_user_prompt

    endpoint = _make_endpoint()
    prompt = build_user_prompt(endpoint)

    assert "POST" in prompt
    assert "/users" in prompt
    assert "createUser" in prompt
    assert "email" in prompt
    assert "201" in prompt
    assert "Tags: users" in prompt


async def test_user_prompt_handles_empty_fields():
    """Prompt should be valid even when most fields are empty."""
    from app.ai.prompts.test_generation import build_user_prompt

    minimal = ParsedEndpoint(
        method=HttpMethod.GET,
        path="/ping",
        name="ping",
        description=None,
        auth=None,
    )
    prompt = build_user_prompt(minimal)
    assert "GET" in prompt
    assert "/ping" in prompt
    assert "(none)" in prompt or "(none required)" in prompt or "(no" in prompt


# ---------------------------------------------------------------------------
# Phase B — probe-grounded generation: the observed-response block is
# appended to the prompt only when both observed_status and observed_body
# are supplied; the plain (no-probe) prompt is untouched otherwise.
# ---------------------------------------------------------------------------


async def test_generate_tests_prompt_unchanged_when_no_observed_response():
    """The default call (observed_status/observed_body both None) must
    send exactly build_user_prompt(endpoint), byte for byte — this is the
    "flag off" guarantee for Phase B.
    """
    from app.ai.prompts.test_generation import build_user_prompt

    provider = MockProvider()
    provider.seed_structured(TestCaseList, _make_seeded_response())
    service = AIOrchestrationService(provider=provider)
    endpoint = _make_endpoint()

    await service.generate_tests(endpoint)

    assert provider.calls[0]["prompt"] == build_user_prompt(endpoint)


async def test_generate_tests_appends_observed_response_block_when_given():
    provider = MockProvider()
    provider.seed_structured(TestCaseList, _make_seeded_response())
    service = AIOrchestrationService(provider=provider)
    endpoint = _make_endpoint()

    await service.generate_tests(
        endpoint,
        observed_status=200,
        observed_body='{"message": "otp generated", "otp_provider": "Static"}',
    )

    prompt = provider.calls[0]["prompt"]
    assert "observed" in prompt.lower()
    assert "Status: 200" in prompt
    assert "otp generated" in prompt
    assert "otp_provider" in prompt


async def test_generate_tests_omits_observed_block_when_only_one_of_the_pair_given():
    """Both observed_status and observed_body are required together — a
    partial value (shouldn't happen from probe_service, but defensively)
    must not produce a malformed half-block."""
    provider = MockProvider()
    provider.seed_structured(TestCaseList, _make_seeded_response())
    service = AIOrchestrationService(provider=provider)
    endpoint = _make_endpoint()

    await service.generate_tests(endpoint, observed_status=200, observed_body=None)

    assert "observed" not in provider.calls[0]["prompt"].lower()


def test_build_observed_response_block_contains_status_and_body():
    from app.ai.prompts.test_generation import build_observed_response_block

    block = build_observed_response_block(200, '{"message": "otp generated"}')

    assert "200" in block
    assert "otp generated" in block
    assert "grounding" in block
    assert "observed" in block
    assert "inferred" in block
