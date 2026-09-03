"""Services package — business-logic layer.

Public exception
----------------
SpecImportError
    Raised by the import service when a spec cannot be fetched, parsed,
    or persisted.  Named ``SpecImportError`` (not ``ImportError``) to avoid
    shadowing Python's built-in ``ImportError`` for module imports.
"""


class SpecImportError(Exception):
    """Raised when a spec import fails for any reason.

    Possible causes:
    - Workspace does not exist
    - HTTP fetch failure (for URL imports)
    - Spec content cannot be parsed as Swagger / OpenAPI
    - Database write failure
    """


class SuiteNotFoundError(Exception):
    """Raised by the suite service when a requested suite cannot be found.

    Possible causes:
    - Suite ID does not exist
    - Suite belongs to a different workspace (tenant isolation)
    """


class EndpointNotFoundError(Exception):
    """Raised when a requested endpoint cannot be found.

    Possible causes:
    - Endpoint ID does not exist
    - Endpoint's suite belongs to a different workspace (tenant isolation)
    """


class TestNotFoundError(Exception):
    """Raised when a requested test cannot be found.

    Possible causes:
    - Test ID does not exist
    - Test's suite belongs to a different workspace (tenant isolation)
    """


class EnvironmentNotFoundError(Exception):
    """Raised when a requested environment cannot be found.

    Possible causes:
    - Environment ID does not exist
    - Environment belongs to a different workspace (tenant isolation)
    """


class ExecutionNotFoundError(Exception):
    """Raised when a requested execution cannot be found.

    Possible causes:
    - Execution ID does not exist
    - Execution's test/environment belongs to a different workspace
      (tenant isolation)
    """


class TestGenerationError(Exception):
    """Raised when AI test generation fails for an endpoint.

    Wraps AIOrchestrationError so API routers only need to know about
    service-layer exceptions, not the AI layer's internals.

    ``reason`` is a short machine-readable classification the frontend uses
    to pick a plain-English message, since the underlying LLM/instructor
    error text is not something an end user should ever see:
    "quota_exhausted" | "rate_limited" | "request_too_large" | "timeout" |
    "connection_error" | "unknown"

    ``reset_at`` is only set for "quota_exhausted", and only when the
    provider's own error response actually included a reset time (see
    app.ai.providers.errors) — never a guessed value.

    ``provider`` is the configured provider's short name (e.g.
    "nvidia_nim"), so the frontend can name it in the "quota_exhausted"
    message without hardcoding it.
    """

    def __init__(
        self,
        message: str,
        reason: str = "unknown",
        reset_at: str | None = None,
        provider: str | None = None,
    ):
        super().__init__(message)
        self.reason = reason
        self.reset_at = reset_at
        self.provider = provider


class DependencyCycleError(Exception):
    """Raised when detected dependency edges form a cycle.

    Re-exported from app.services.dependency_detector so API routers only
    need to import from app.services. ``test_ids`` lists the tests involved,
    in cycle order (raw ids — stable for tooling/tests).

    ``message``, when given, overrides the generic id-based message with a
    more specific one (e.g. suite execution names the actual tests by name
    rather than id — see app/services/suite_execution_service.py) — API
    routers should prefer ``str(exc)`` over re-deriving a message from
    ``test_ids`` so that override is surfaced.
    """

    def __init__(self, test_ids: list[str], message: str | None = None):
        super().__init__(message or f"Dependency cycle detected among tests: {test_ids}")
        self.test_ids = test_ids


class DependencyNotFoundError(Exception):
    """Raised when a requested dependency edge cannot be found.

    Possible causes:
    - Dependency ID does not exist
    - Dependency's test belongs to a different suite/workspace
    """


class InvalidDependencyError(Exception):
    """Raised when a manually-added dependency edge is not allowed.

    Possible causes:
    - test_id == depends_on_test_id (a test can't depend on itself)
    - Either test doesn't belong to the suite being edited
    - The edge already exists
    """


class ValidationNotFoundError(Exception):
    """Raised when a requested validation entry cannot be found on a test.

    Possible causes:
    - validation_id does not match any entry in the test's validations list
    - Test's suite belongs to a different workspace (tenant isolation)
    """
