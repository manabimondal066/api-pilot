# Product Requirements Document (PRD)

## AI-Native API Testing Workspace

**Document Status:** Production-ready MVP PRD
**Product Type:** AI-native API testing SaaS / self-hosted platform
**Primary Users:** QA Engineers, SDETs, API Developers
**MVP Focus:** API import → AI test generation → validation → dependency-aware execution → conversational editing → reusable regression suites

---

# 1. Executive Summary

The AI-Native API Testing Workspace is a workspace-first API testing platform designed to reduce the manual effort required to create, maintain, execute, and analyze API automation.

The platform accepts API definitions through **Swagger/OpenAPI, Postman Collections, and cURL** and transforms them into structured, reusable API test suites. It generates positive, negative, and edge-case tests, creates response validations, understands endpoint dependencies, executes tests against configurable environments, and explains failures using AI.

The product is explicitly positioned as an **AI-native API testing workspace**, rather than another scripting-based automation framework.

The core product loop is:

> **Import → Understand → Generate → Review → Execute → Validate → Explain → Modify → Re-run → Reuse**

The system should keep deterministic API execution and validation separate from AI generation wherever possible. AI produces structured testing artifacts; the execution engine executes those artifacts deterministically. This improves reliability, debuggability, performance, and cost efficiency.

---

# 2. Product Vision

## 2.1 Vision

Build an AI-native API testing workspace that enables QA engineers to create reliable API regression coverage without manually writing large amounts of automation code.

The product should:

* Understand API contracts.
* Generate meaningful API tests.
* Generate validations automatically.
* Understand endpoint relationships.
* Execute APIs against multiple environments.
* Explain failures.
* Allow users to modify tests conversationally.
* Store tests as reusable regression suites.

The underlying product vision and core capabilities are defined in the source PRD.

---

# 3. Problem Statement

Traditional API automation requires QA engineers to manually:

1. Understand API documentation.
2. Create test scenarios.
3. Write request payloads.
4. Write assertions.
5. Handle authentication.
6. Extract and pass variables between APIs.
7. Maintain environment configurations.
8. Debug failures.
9. Update tests when requirements change.
10. Maintain reusable regression suites.

This creates several problems:

* High initial scripting effort.
* Inconsistent API test coverage.
* Repetitive validation logic.
* Complex dependency management.
* High maintenance cost.
* Slow regression execution.
* Difficult failure analysis.
* Significant technical knowledge required for test creation.

The proposed product addresses these problems through an AI-assisted workspace while retaining deterministic execution and validation.

---

# 4. Goals and Success Criteria

## 4.1 Product Goals

### Goal 1 — Reduce test creation effort

A QA engineer should be able to import an API definition and receive generated test cases and validations without manually scripting every scenario.

### Goal 2 — Improve API coverage

Automatically generate:

* Positive scenarios.
* Negative scenarios.
* Edge cases.
* Status-code validations.
* Required-field validations.
* Schema validations.
* Response structure validations.
* Dependency validations.

These validation categories are explicitly required by the source requirements.

### Goal 3 — Simplify dependency handling

The system should identify relationships between APIs and automatically pass values such as IDs and tokens between dependent requests.

### Goal 4 — Make API testing conversational

Users should be able to modify tests using natural-language instructions instead of manually editing every assertion or payload.

### Goal 5 — Create reusable regression suites

Generated tests must persist and be reusable across future executions.

### Goal 6 — Make failures understandable

The system should provide both technical failure information and concise AI-generated explanations.

---

# 5. Target Users

## 5.1 Primary Persona — QA Engineer

Needs to:

* Quickly create API coverage.
* Validate API contracts.
* Execute regression suites.
* Debug failures.
* Modify assertions.
* Manage environments.

## 5.2 Secondary Persona — SDET

Needs:

* Generated test artifacts.
* Advanced validation visibility.
* Dependency configuration.
* Editable assertions.
* Reusable suites.
* Technical execution information.

## 5.3 Secondary Persona — API Developer

Needs:

* Quick endpoint verification.
* Contract validation.
* Failure visibility.
* Response mismatch analysis.
* Reproducible test execution.

---

# 6. Product Scope

## 6.1 MVP / V1

V1 includes:

* Swagger/OpenAPI support.
* Postman Collection support.
* cURL support.
* AI-generated test cases.
* Positive/negative/edge tests.
* Automatic validations.
* Dependency handling.
* Environment management.
* Single endpoint execution.
* Full suite execution.
* Suite reruns.
* Conversational editing.
* AI failure explanation.
* Approval mode.
* Low-confidence handling.
* Reusable test storage.
* Execution history.

The source explicitly identifies the core V1 scope around Swagger/OpenAPI, generated tests, validations, dependencies, environments, conversational editing, history, and reusable suites.

## 6.2 V1.5

Natural-language requirements layered on top of cURL should be introduced in V1.5 rather than making them a core deterministic V1 import mechanism.

The existing project decision is:

* Swagger/OpenAPI — V1.
* Postman — V1.
* cURL — V1.
* NL over cURL — V1.5.

## 6.3 Explicitly Out of Scope

The following are not part of V1:

* Collaboration.
* CI/CD integration.
* Git integration.
* Autonomous learning.
* Automatic Swagger synchronization.
* Organizational memory.

---

# 7. High-Level User Journey

## Journey A — Create a Test Suite

1. User opens the workspace.
2. User selects **Import API**.
3. User selects:

   * Swagger/OpenAPI.
   * Postman Collection.
   * cURL.
4. System parses the input.
5. System displays discovered endpoints.
6. System identifies request and response structures.
7. AI generates tests.
8. AI generates validations.
9. System detects dependencies.
10. User reviews generated suite.
11. User modifies tests if required.
12. User saves the suite.

---

# 8. Functional Requirements

# 8.1 API Import

The platform must support:

### Swagger/OpenAPI

* Swagger URL import.
* JSON upload.
* YAML upload.

The importer should extract:

* Endpoints.
* HTTP methods.
* Endpoint names.
* Request schemas.
* Response schemas.
* Required fields.
* Headers.
* Authentication information.
* Path parameters.
* Query parameters.
* Body parameters.

### Postman Collection

The system should parse the collection JSON and extract:

* Request method.
* URL.
* Headers.
* Query parameters.
* Path parameters.
* Request body.
* Authentication configuration.
* Collection/folder hierarchy.

For V1, Postman JavaScript test and pre-request scripts should not be treated as executable application logic; the platform should primarily extract the request definition. This keeps the initial implementation deterministic and manageable.

### cURL

The platform should parse common cURL requests into a normalized API request representation:

* HTTP method.
* URL.
* Headers.
* Query parameters.
* Request body.
* Authentication information.

---

# 8.2 Import Validation

Before creating tests, the system must validate the imported source.

Possible import states:

* **Imported successfully**
* **Imported with warnings**
* **Import failed**

Examples of warnings:

* Missing response schema.
* Missing request body schema.
* Unsupported authentication structure.
* Ambiguous endpoint information.
* Invalid OpenAPI definition.

The user should be able to continue when the system can safely create a partial representation.

---

# 8.3 Normalized API Representation

Regardless of input format, imported APIs should be converted into a common internal representation.

Conceptually:

```text
API
 ├── Endpoint
 │    ├── Method
 │    ├── URL
 │    ├── Headers
 │    ├── Authentication
 │    ├── Path Parameters
 │    ├── Query Parameters
 │    ├── Request Body
 │    └── Response Schema
```

This normalized model allows the same generation and execution pipeline to work across Swagger, Postman, and cURL.

---

# 9. AI Test Generation

## 9.1 Test Categories

For each endpoint, the system should generate:

### Positive Tests

Examples:

* Valid required fields.
* Valid authentication.
* Valid request body.
* Valid parameter combinations.

### Negative Tests

Examples:

* Missing required fields.
* Invalid values.
* Invalid authentication.
* Invalid parameters.
* Unsupported input formats.

### Edge Tests

Examples:

* Boundary values.
* Empty values.
* Maximum-length values.
* Minimum-length values.
* Null values where applicable.
* Unexpected but structurally valid inputs.

The source explicitly requires positive, negative, and edge test generation.

---

# 10. Validation Generation

Each generated test should contain machine-readable validations.

Supported validation categories:

1. Status code.
2. Required fields.
3. JSON/schema structure.
4. Field existence.
5. Response structure.
6. Dependency values.
7. Expected response characteristics.

Example human-readable validation:

> Validate status code is 201.

Advanced representation may contain:

```json
{
  "type": "status_code",
  "expected": 201
}
```

Another example:

```json
{
  "type": "field_exists",
  "path": "$.userId"
}
```

The product should show human-readable validations by default while allowing advanced users to inspect and edit the underlying assertion representation.

---

# 11. Test Confidence and Review

AI-generated artifacts should not be treated as automatically correct.

The platform should assign an internal confidence assessment based on factors such as:

* Source completeness.
* Schema completeness.
* Validation generation success.
* Dependency certainty.
* Structured-output validation.
* Ambiguity in inferred behavior.

A low-confidence result must be surfaced to the user rather than silently executed.

The existing product requirements specify that low-confidence cases should trigger clarification and block execution until the required answer is received.

---

# 12. Dependency Handling

## 12.1 Purpose

Many APIs cannot be tested independently.

Example:

```text
Create User
     ↓
extract userId
     ↓
Get User
     ↓
Update User
     ↓
Delete User
```

The system must support this workflow.

The source explicitly defines this example and requires automatic dependency detection, manual overrides, and AI-based modifications.

## 12.2 Automatic Dependency Detection

The system should identify likely dependencies using:

* Matching response fields to later request parameters.
* Matching IDs.
* Authentication/token relationships.
* Endpoint semantics.
* Schema relationships.

## 12.3 Dependency Graph

Internally, dependencies should be represented as a directed graph.

Example:

```text
Create User
     |
     | userId
     ↓
Get User
     |
     | userId
     ↓
Update User
     |
     ↓
Delete User
```

## 12.4 Manual Override

Users must be able to:

* Add a dependency.
* Remove a dependency.
* Change an extracted variable.
* Change the destination variable.
* Change execution order.

---

# 13. Variable Extraction and Substitution

The execution engine must support runtime values such as:

* User IDs.
* Tokens.
* Resource IDs.
* Dynamic payload values.
* Environment variables.

Example:

```text
Login API
  response.token
       ↓
Authorization header
       ↓
Create User
```

Variable references should be resolved immediately before execution rather than permanently replacing source definitions.

This allows the same suite to run repeatedly with different runtime values.

---

# 14. Execution Engine

The execution engine must support:

* Single endpoint execution.
* Full suite execution.
* Existing suite reruns.

## 14.1 Execution Lifecycle

```text
Queued
  ↓
Preparing
  ↓
Resolving dependencies
  ↓
Executing
  ↓
Validating
  ↓
Completed
```

Possible final states:

* Passed.
* Failed.
* Blocked.
* Skipped.
* Error.

## 14.2 Execution Isolation

AI should not be required during normal request execution or assertion evaluation.

The execution engine should:

1. Load the suite.
2. Resolve environment variables.
3. Resolve dependencies.
4. Build the request.
5. Execute HTTP request.
6. Capture response.
7. Execute validations.
8. Store results.
9. Publish execution status.

This separation keeps execution deterministic and avoids unnecessary LLM calls.

---

# 15. Environment Management

V1 must support:

* QA.
* Staging.
* Cloud.

Each environment should support:

* Base URL.
* Authentication token.
* Headers.
* Variables.

Example:

```text
Environment: QA

Base URL:
https://qa-api.example.com

Token:
<secret>

Variables:
tenantId = ...
region = ...
```

Sensitive values must not be exposed unnecessarily in the UI or logs.

---

# 16. Approval Modes

The workspace should provide a toggle between two execution behaviors.

## 16.1 Auto Mode

System can:

* Generate tests.
* Validate generated artifacts.
* Execute tests.

This is intended for trusted, repeatable workflows.

## 16.2 Approval Mode

System must:

* Ask for user approval before execution.
* Ask clarification questions when confidence is low.
* Pause execution until the user responds.

The selected mode should be visible in the workspace so the user always knows whether an action will execute immediately.

---

# 17. AI Assistant

The AI assistant is a core part of the workspace rather than a separate chatbot.

It should understand the currently selected:

* Workspace.
* Suite.
* Endpoint.
* Test.
* Validation.
* Environment.

## 17.1 Supported Commands

Users should be able to say:

> "Ignore timestamp validation."

> "Add email validation."

> "Use token from login API."

The assistant must support:

* Adding validations.
* Removing validations.
* Modifying payloads.
* Regenerating tests.
* Modifying dependencies.
* Explaining failures.
* Editing assertions.

---

# 18. Conversational Change Model

AI modifications should be applied as explicit workspace changes.

Example:

```text
User:
"Add email validation."

AI:
"I'll add an email-format validation to Create User.email."

[Apply change]

Workspace:
Validation added
```

The AI should not silently make unrelated changes.

For consequential actions, especially execution, approval mode should determine whether confirmation is required.

---

# 19. AI Architecture

The AI layer should use different strategies depending on task complexity.

## 19.1 Structured LLM Generation

Use structured LLM calls for:

* Test generation.
* Validation generation.
* Requirement interpretation.
* Failure explanation.

Outputs must conform to a strict schema before being persisted.

## 19.2 AI Agent

Use an agent only where the task requires:

* Reading current suite state.
* Making decisions.
* Calling tools.
* Applying changes.
* Iterating based on results.

The chat assistant is the primary agent use case.

## 19.3 Provider Abstraction

The AI implementation should remain provider-agnostic.

The architecture should expose a provider abstraction capable of supporting:

* NVIDIA NIM.
* OpenAI-compatible providers.
* Claude during development/alternative deployments.
* Local/self-hosted models.

The selected project architecture identifies NVIDIA NIM as the primary GPU inference approach while retaining an abstraction layer for provider flexibility.

---

# 20. Failure Analysis

When a validation fails, the system should distinguish between:

### Assertion Failure

The API responded, but expected behavior did not match.

### Runtime Failure

The request could not be executed successfully.

Examples:

* Timeout.
* Connection failure.
* DNS failure.
* Authentication failure.

### Response Mismatch

The API response does not match the expected schema or structure.

The UI must expose these separately.

---

# 21. Failure UI

A failed endpoint should display:

* Red failure indicator.
* Failure percentage.
* Short AI explanation.

Example:

```text
Get User
FAILED
40% validations failed

AI:
"The endpoint returned 200, but the expected
userId field was missing from the response."
```

Detailed failure information should include:

* Failed validations.
* Runtime errors.
* Response mismatches.
* Logs.

---

# 22. AI Failure Explanation

AI should explain failures using the actual execution context.

The explanation should be based on:

* Request.
* Expected validation.
* Actual response.
* Error information.
* Relevant dependency information.

The AI must not invent an explanation when the execution data is insufficient.

A generated explanation should be clearly presented as an explanation rather than the authoritative execution result.

---

# 23. Test Suite Storage

Generated suites must be persistent.

Users must be able to:

* Reopen suites.
* Edit suites.
* Rerun suites.
* Reuse validations.

A suite should preserve:

* Imported API definition.
* Endpoints.
* Generated tests.
* Validations.
* Dependencies.
* Environment references.
* User modifications.
* Generation metadata.
* Execution history references.

---

# 24. Execution History

Each execution should store:

* Execution date/time.
* Overall pass/fail result.
* Validation summary.
* Response history.
* Logs.
* Errors.

## 24.1 History View

The user should be able to see:

```text
Suite: User APIs

Run #42
Status: FAILED
Passed: 17
Failed: 3
Date: ...
Environment: QA
```

Selecting a run should expose endpoint-level results.

---

# 25. UI/UX Architecture

The product should use a **workspace-first layout**.

The source defines three primary areas: left navigation, central workspace, and AI assistant panel.

## 25.1 Left Panel

Contains:

* API groups.
* Endpoint list.
* Test suites.

Recommended hierarchy:

```text
Workspace
 ├── API Groups
 │    ├── Users
 │    ├── Payments
 │    └── Orders
 │
 └── Test Suites
      ├── Regression
      └── Smoke
```

## 25.2 Main Workspace

Contains:

* Generated tests.
* Validations.
* Request preview.
* Response preview.
* Execution controls.
* Status indicators.
* Dependency information.

## 25.3 AI Assistant Panel

Contains:

* Conversation history.
* User message input.
* AI response.
* Proposed changes.
* Clarification questions.
* Change confirmations.

---

# 26. Endpoint Card

Every endpoint should display:

* Endpoint name.
* HTTP method.
* Pass/fail status.
* Validation count.
* Execute button.

Example:

```text
POST  Create User
PASSED
8 validations
[Execute]
```

or:

```text
GET  Get User
FAILED
5 / 8 validations failed
[Execute]
```

The endpoint card requirements are directly defined in the source UI specification.

---

# 27. Validation UX

## Default Mode

Show validations in human-readable language.

Example:

```text
✓ Validate status code is 201
✓ Validate userId exists
✓ Validate response contains email
✓ Validate response matches schema
```

## Advanced Mode

Allow users to inspect:

* Generated assertion.
* Assertion configuration.
* JSON path.
* Expected value.
* Generated code representation.
* Payload.

Users should be able to edit assertions and payloads.

---

# 28. Real-Time Updates

The workspace should update without requiring manual refresh during:

* Test generation.
* Suite generation.
* Execution.
* AI chat.
* AI modifications.

The planned architecture uses Server-Sent Events for live execution updates and streaming AI responses.

---

# 29. Technical Architecture

## 29.1 Frontend

Recommended:

* React.
* TypeScript.
* Vite.
* Tailwind CSS.
* shadcn/ui.

The source architecture specifies React + TypeScript with Vite/Tailwind/shadcn/ui for the workspace experience.

## 29.2 Backend

Recommended:

* Python.
* FastAPI.
* Pydantic.
* SQLAlchemy.
* Alembic.
* PostgreSQL.

The backend should initially remain a modular monolith rather than prematurely introducing microservices.

Core modules:

1. Import Service.
2. Test Generation Service.
3. Execution Service.
4. Validation Service.
5. Dependency Resolver.
6. AI Orchestration Service.
7. Storage Service.

---

# 30. Data Storage

PostgreSQL should store:

* Users.
* Workspaces.
* Environments.
* API definitions.
* Endpoints.
* Test suites.
* Test cases.
* Validations.
* Dependencies.
* Execution records.
* User modifications.

JSONB can be used for flexible test and validation structures while relational fields should be used for entities that require querying and relationships.

The planned architecture uses PostgreSQL with JSONB for flexible test artifacts and relational structures for important entities.

Large artifacts such as uploaded specifications and large response bodies should use object storage when deployed in production. The planned architecture uses S3-compatible storage such as MinIO for this purpose.

---

# 31. Asynchronous Processing

AI generation and potentially large test executions should not block the primary API request.

The planned architecture uses Redis-backed asynchronous workers, with `arq` selected for the V1 implementation.

Example:

```text
Frontend
   |
   | Start generation
   ↓
FastAPI
   |
   ↓
Job Queue
   |
   ↓
Worker
   |
   ↓
AI Generation
   |
   ↓
PostgreSQL
   |
   ↓
SSE
   |
   ↓
Frontend
```

---

# 32. Security Requirements

Because the platform handles authentication tokens, API requests, and potentially sensitive response data, security must be treated as a first-class requirement.

## 32.1 Secrets

Tokens and credentials must:

* Be stored securely.
* Be masked in the UI.
* Never appear in normal logs.
* Never be included in AI prompts unnecessarily.
* Never be exposed in execution history.

## 32.2 AI Data Boundaries

The AI layer should receive only the context required for the requested task.

For example, failure explanation should not require unrelated environment secrets.

## 32.3 Execution Safety

The platform should make the target environment explicit before execution.

A user should clearly see:

> Environment: **STAGING**

before executing a suite.

This reduces the risk of accidentally executing destructive tests against an unintended environment.

---

# 33. Deployment Architecture

The product should support flexible deployment.

The planned architecture targets:

### Docker Compose

For:

* Development.
* Single-node installations.
* Smaller deployments.

### Kubernetes

For:

* Production.
* Enterprise installations.
* Scalable deployments.

The planned architecture explicitly calls for Docker Compose and Helm/Kubernetes packaging.

---

# 34. AI Deployment Model

## GPU Deployment

NVIDIA NIM should be the primary self-hosted inference option for GPU-equipped environments.

The architecture should communicate with NIM through an OpenAI-compatible interface, keeping the application independent of the underlying inference runtime.

## CPU Deployment

A CPU-only fallback remains a product/architecture constraint requiring reduced capability rather than pretending that CPU inference provides equivalent performance.

The source analysis identifies the practical limitations of running large models on CPU and the need for explicit capability differences if CPU support is offered.

Therefore, the product should treat CPU execution as a **degraded mode**, not as feature-equivalent to GPU inference.

---

# 35. API Design Principles

Backend APIs should be REST-oriented for CRUD operations.

Examples:

```text
POST   /api/imports
GET    /api/suites
POST   /api/suites
GET    /api/suites/{suite_id}
PATCH  /api/suites/{suite_id}
POST   /api/suites/{suite_id}/execute
GET    /api/suites/{suite_id}/executions
POST   /api/chat
```

Long-running operations should return an operation/job identifier rather than holding an HTTP request open.

---

# 36. Non-Functional Requirements

## Performance

The UI should remain responsive while:

* Importing APIs.
* Generating tests.
* Running suites.
* Streaming AI responses.

## Reliability

AI output must be validated before becoming executable test configuration.

Structured AI output should pass schema validation before persistence. The planned architecture explicitly recommends strict Pydantic validation and retry handling.

## Determinism

Normal execution and validation should be deterministic.

AI should not be called during every assertion or request execution.

## Scalability

The initial implementation should be a modular monolith, but services should have clear boundaries so expensive workloads can later be separated.

## Observability

The system should maintain:

* Application logs.
* Execution logs.
* AI operation logs.
* Job status.
* Error information.

Sensitive credentials must be redacted.

---

# 37. AI Reliability Requirements

AI-generated output must never directly become executable without validation.

Pipeline:

```text
LLM
 ↓
Structured Output
 ↓
Pydantic Validation
 ↓
Semantic Validation
 ↓
Persist
 ↓
User Review / Approval
 ↓
Execution
```

If structured generation fails:

1. Retry with validation feedback.
2. If retry fails, mark the artifact as requiring review.
3. Do not silently persist malformed output.

The source architecture explicitly recommends retrying once and marking failed generation as requiring review.

---

# 38. MVP Acceptance Criteria

## Import

* User can import a valid Swagger/OpenAPI file.
* User can import a Swagger URL.
* User can import a Postman collection.
* User can import cURL.
* Endpoints are correctly displayed.
* Request/response information is preserved.

## Generation

* Positive tests are generated.
* Negative tests are generated.
* Edge tests are generated.
* Validations are generated.
* Generated artifacts pass structural validation.

## Dependencies

* Dependencies are detected where possible.
* Variables can be extracted.
* Variables can be passed to subsequent requests.
* Users can manually override dependencies.

## Execution

* User can run one endpoint.
* User can run an entire suite.
* User can rerun a suite.
* Environment variables are resolved.
* Authentication headers are applied.
* Responses are captured.
* Validations are executed.

## AI Assistant

* User can add a validation through chat.
* User can remove a validation.
* User can modify a payload.
* User can modify a dependency.
* User can regenerate tests.
* User can ask for failure explanation.

## History

* Every execution has a timestamp.
* Pass/fail result is stored.
* Validation results are stored.
* Response history is available.
* Errors/logs are available.

---

# 39. Example End-to-End Scenario

## Input

User imports a Swagger definition containing:

```text
POST /users
GET /users/{id}
PUT /users/{id}
DELETE /users/{id}
```

## AI Generation

The system generates:

```text
Create User
 ├── Valid user
 ├── Missing email
 ├── Invalid email
 ├── Empty name
 └── Boundary values
```

## Dependency Detection

The system recognizes:

```text
Create User
    ↓
userId
    ↓
Get User
    ↓
Update User
    ↓
Delete User
```

## Execution

The system executes in dependency order.

## Validation

For Create User:

```text
✓ Status code = 201
✓ userId exists
✓ email exists
✓ Response matches schema
```

## Failure

If `userId` is missing:

```text
Create User
FAILED
1 / 4 validations failed
```

AI explanation:

> The endpoint returned a successful response, but the required `userId` field was missing from the response body.

The user can then ask:

> "Add a validation that userId must be a UUID."

The assistant updates the validation configuration and the workspace reflects the change immediately.

---

# 40. Product Principles

### Principle 1 — AI assists; execution remains deterministic

The LLM should not be the runtime test engine.

### Principle 2 — Never hide AI uncertainty

When the system is unsure, ask the user.

### Principle 3 — Human-readable by default

QA engineers should not need to understand generated code to understand what a test validates.

### Principle 4 — Advanced users retain control

Every important generated artifact should be inspectable and editable.

### Principle 5 — Reuse over regeneration

Tests should be stored and maintained as reusable assets.

### Principle 6 — Provider independence

The product should not become architecturally dependent on one AI provider.

### Principle 7 — Workspace first

The chatbot is a powerful interaction layer, but the actual tests, validations, executions, and results remain visible in the workspace.

---

# 41. Risks and Mitigations

| Risk                                            | Impact      | Mitigation                                                |
| ----------------------------------------------- | ----------- | --------------------------------------------------------- |
| Incorrect AI-generated tests                    | High        | Structured output + validation + approval mode            |
| Incorrect dependency inference                  | High        | Show inferred dependencies + manual override              |
| AI hallucinated assertions                      | High        | Validate assertions before execution                      |
| Large AI generation cost                        | Medium/High | Batch generation and smaller models for lightweight tasks |
| Slow self-hosted inference                      | Medium      | GPU inference + degraded CPU mode                         |
| Sensitive API data exposure                     | High        | Secret masking + controlled AI context                    |
| Ambiguous imported API                          | Medium      | Import warnings + clarification                           |
| Destructive execution against wrong environment | High        | Explicit environment selection + approval mode            |
| Large response storage                          | Medium      | Object storage for large payloads                         |
| Growing suite size                              | Medium      | Modular storage and later retrieval optimization          |

The source architecture also identifies LLM cost, determinism, confidence scoring, runtime authentication, and input-format complexity as important risks.

---

# 42. Future Roadmap

## V1

Core AI-native API testing workspace.

## V1.5

* Natural-language requirements over cURL.
* Improved clarification flows.
* Improved AI dependency inference.

## V2

Potential expansion into:

* CI/CD integration.
* Git integration.
* Collaboration.
* External AI client integration through MCP.
* RAG for very large suites.
* Advanced organizational knowledge.
* Automatic API synchronization.
* Broader autonomous testing workflows.

MCP and RAG are intentionally better suited to later versions rather than the initial product.

---

# 43. Final Product Definition

The MVP is an **AI-native API testing workspace** that transforms API definitions into reusable, executable regression suites.

Its core value proposition is:

> **Import your APIs, let AI create meaningful tests and validations, execute them against your environments, understand failures, and modify everything conversationally.**

The product is not intended to replace the deterministic API execution engine with AI. Instead, AI is used where reasoning provides value—test generation, validation generation, dependency interpretation, conversational modification, and failure explanation—while deterministic software handles execution, validation, persistence, and orchestration.

This architecture provides the foundation for a scalable commercial SaaS product while preserving the flexibility required for self-hosted and enterprise deployments.
