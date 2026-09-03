# Backend — api-pilot

Python 3.12+ FastAPI backend. Async throughout. Pydantic v2 for validation. SQLAlchemy 2.x async ORM.

See [/docs](../docs/README.md) for architecture details.

## Directory Layout

```
backend/
├── app/
│   ├── api/        → FastAPI routers (HTTP route handlers only — no business logic here)
│   ├── services/   → Business logic layer (called by routers, calls models/AI layer)
│   ├── models/     → SQLAlchemy 2.x async ORM models (database table definitions)
│   ├── schemas/    → Pydantic v2 schemas for request validation and response serialization
│   ├── ai/         → AI orchestration layer (Claude API calls, prompt management)
│   ├── parsers/    → Input parsers: OpenAPI/Swagger, Postman collections, raw cURL
│   ├── engine/     → Test execution engine + response validation logic
│   ├── workers/    → arq async background workers (long-running test runs)
│   ├── db/         → Database session factory, Base declarative class
│   ├── config.py   → Settings loaded from environment via Pydantic BaseSettings
│   └── main.py     → FastAPI app factory (create_app)
├── tests/          → pytest test suite
├── alembic/        → Database migration scripts (set up in Sprint 0 Prompt 3)
├── pyproject.toml  → Project metadata and dependencies
└── .env.example    → Environment variable template (never commit real .env)
```

## Key Conventions

- All DB queries use `async with session` — never synchronous ORM calls.
- Routers inject dependencies via `Depends()` — no global state.
- Pydantic schemas are separate from ORM models (no mixing).
- AI calls live exclusively in `app/ai/` — services call the AI layer, not Claude directly.
