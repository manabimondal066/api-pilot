# Project Overview: API-Pilot
An AI-native API testing workspace platform designed to generate, validate, execute, and analyze API automation tests deterministically.

# Primary Reference Documents
- Core PRD: @docs/PRD.md
- Active Plan: @docs/cURL-Import-Plan.md
- Architecture Specs: @docs/architecture/

# System Guiding Principles
1. **Deterministic Execution:** Keep execution and validation logic separate from AI generation. AI creates test artifacts; code executes them.
2. **Provider Independence:** Retain AI provider abstraction (primary: NVIDIA NIM, fallback/dev options available).
3. **Workspace First:** Ensure operations remain visual and structured within the workspace.

# Core Development Workflow & Skills

## Skill: PRD Compliance Check
When asked to check code against PRD or review a feature:
1. Read `@docs/PRD.md`.
2. Verify if the implemented API endpoint or UI component aligns with the MVP scope (Section 6.1).
3. Ensure no out-of-scope features (Section 6.3) are accidentally introduced.
4. Verify strict separation of deterministic runtime and LLM generation.

## Skill: Test Generation Validation
When generating or reviewing test case logic:
1. Ensure coverage includes Positive, Negative, and Edge cases (Section 9.1).
2. Validate output schema using structured models (Pydantic/TypeScript types).
3. Flag any low-confidence cases to require user review.

## Skill: Endpoint Dependency Rules
When handling API dependencies:
1. Verify dynamic value substitution (e.g., passing extracted `userId` or `token` between calls).
2. Ensure variable resolution occurs at execution time rather than hardcoding.