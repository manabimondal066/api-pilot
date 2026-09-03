# API-Pilot

**API-Pilot is an AI-powered tool that tests APIs for you.**

Normally, testing an API (the "backend" that powers an app or website) is manual, slow work: a QA engineer has to read the API's documentation, think up test scenarios (valid input, invalid input, edge cases), write out the checks by hand, and re-do all of it every time something changes.

API-Pilot removes most of that manual effort. You give it an API definition — a Swagger/OpenAPI file, a Postman collection, or even a raw `curl` command copy-pasted from your terminal or browser — and it:

1. **Reads and understands** the API (what endpoints it has, what data they expect, what they return).
2. **Uses AI to generate test cases automatically** — valid ("positive"), invalid ("negative"), and boundary/tricky ("edge case") scenarios.
3. **Runs those tests for real** against a live server and checks whether the responses match what was expected.
4. **Explains failures in plain English** using AI, instead of leaving you to decode raw error logs.
5. **Lets you tweak tests by chatting** ("add a check that the email field must look like an email") instead of hand-editing test code.
6. **Saves everything** so the same test suite can be re-run again and again (regression testing).

A core design rule of this project: **the AI never runs the tests itself.** AI is only used to *write* the tests and *explain* results. The actual running of API calls and checking of pass/fail is done by plain, predictable code — so results are always trustworthy and repeatable. See [docs/PRD.md](docs/PRD.md) for the full product spec behind this project.

---

## What's actually built right now

This is an early-stage / hackathon-style build. Here's the honest status:

| Area | Status |
|---|---|
| Import APIs (Swagger/OpenAPI, cURL) | ✅ Working |
| Postman collection import | ⏳ Not yet implemented |
| AI test generation (positive/negative/edge) | ✅ Working |
| Deterministic test execution engine | ✅ Working |
| Endpoint dependency detection (e.g. pass `userId` from "Create User" into "Get User") | ✅ Working |
| Environments (QA / Staging / Cloud, with variables & tokens) | ✅ Working |
| Execution history | ✅ Working |
| AI chat assistant (edit tests, explain failures, in natural language) | ✅ Working |
| Web UI (React) | ✅ Working — suite list, suite detail, import, environments, history, chat panel |
| Docker / containerized setup | ⏳ Placeholder only — currently runs directly on the machine (see [Setup](#setup--running-it-on-a-new-machine)) |
| Production deployment (Kubernetes/Helm) | ⏳ Not started — future work |

---

## Tech Stack — what's used, and where

Think of the project as two halves that talk to each other over the network: a **backend** (the "engine room" — does the real work, talks to the database and the AI) and a **frontend** (the web page you actually click around in).

| Technology | What it is (plain English) | Where it's used |
|---|---|---|
| **Python 3.12** | The programming language for the backend | All of `backend/` |
| **FastAPI** | A framework for building the backend's web API (the URLs the frontend talks to, like `/api/suites`) | `backend/app/api/` — every route the frontend calls |
| **Pydantic v2** | Validates that data (from users, from the AI, from the database) is shaped correctly before it's trusted | `backend/app/schemas/`, `backend/app/ai/schemas/` |
| **SQLAlchemy 2.x (async)** | Lets Python code read/write the database without writing raw SQL by hand | `backend/app/models/`, `backend/app/db/` |
| **Alembic** | Tracks and applies database schema changes over time (migrations) | `backend/alembic/` |
| **PostgreSQL** | The database that stores workspaces, suites, tests, environments, execution history, etc. | Runs as its own service; connected to via `DATABASE_URL` |
| **Anthropic Claude / NVIDIA NIM / Groq / OpenAI** (pluggable) | The AI ("LLM") that generates test cases, detects dependencies, and explains failures. The project isn't locked into one AI provider — you configure which one to use | `backend/app/ai/providers/` |
| **httpx** | Makes the actual HTTP requests when a test is executed against a real API | `backend/app/services/execution_engine.py` |
| **jsonpath-ng** | Lets a test say "check that this specific field, deep inside the JSON response, has this value" | Used by the validation/execution engine |
| **structlog** | Structured, readable application logging | Throughout the backend |
| **pytest** | Automated test suite for the backend itself (not to be confused with the API tests API-Pilot generates for *your* APIs) | `backend/tests/` |
| **React 19 + TypeScript** | The language/library the web UI (frontend) is built with | All of `frontend/src/` |
| **Vite** | Fast dev server + build tool for the frontend | `frontend/vite.config.ts` |
| **Tailwind CSS + shadcn/ui** | Styling system and pre-built UI components (buttons, cards, etc.) | `frontend/src/components/` |
| **React Router** | Handles page navigation inside the web app without full page reloads | `frontend/src/App.tsx` |
| **arq** *(planned)* | Redis-backed background job runner, for long-running test executions that shouldn't block the web request | Listed as a dependency; not yet wired up in `backend/app/workers/` |
| **Docker Compose** *(planned)* | One-command way to spin up Postgres/Redis/backend/frontend together | `infra/docker-compose.yml` — currently a placeholder |

---

## Project Structure

```
api-pilot/
├── backend/                     ← The "engine room": API server, database, AI logic, test runner
│   ├── app/
│   │   ├── api/                 ← The URLs (routes) the frontend calls — e.g. /api/suites, /api/chat
│   │   ├── services/             ← The actual business logic behind each route (import, generate, execute, chat)
│   │   ├── models/                ← Database table definitions (Suite, Endpoint, Test, Environment, Execution, etc.)
│   │   ├── schemas/               ← Data "shape contracts" — what a valid request/response looks like
│   │   ├── ai/                    ← Everything AI-related: provider connections, prompts, chat tools, structured outputs
│   │   │   ├── providers/         ← Swappable AI backends (Anthropic, NVIDIA NIM, OpenAI-compatible, a "mock" for tests)
│   │   │   ├── prompts/           ← The actual instructions sent to the AI for test generation and chat
│   │   │   ├── tools/             ← Actions the AI chat assistant is allowed to take (add validation, modify test, etc.)
│   │   │   └── schemas/           ← Strict format the AI's output must match before it's trusted
│   │   ├── parsers/               ← Turns Swagger/OpenAPI files or raw curl commands into a common internal format
│   │   ├── engine/                ← (Execution/validation engine internals)
│   │   ├── workers/                ← Background job processing (planned, not yet active)
│   │   ├── db/                    ← Database connection/session setup
│   │   ├── storage/                ← File storage (uploaded specs, large responses) — local disk today
│   │   ├── core/                   ← Shared constants/helpers
│   │   ├── config.py                ← All environment-variable-based settings in one place
│   │   └── main.py                  ← Starts the FastAPI app and wires all the routes together
│   ├── tests/                     ← Automated tests proving the backend itself works correctly
│   ├── alembic/                   ← Database migration history
│   ├── scripts/                   ← Windows setup/run helper scripts (install, run-dev)
│   ├── pyproject.toml              ← Backend dependency list & project metadata
│   └── .env.example                ← Template for backend configuration/secrets
│
├── frontend/                     ← The website / UI you interact with in a browser
│   └── src/
│       ├── pages/                 ← One file per screen (Suite List, Suite Detail, Import, Environments, History)
│       ├── components/             ← Reusable UI pieces (Chat Panel, HTTP Method badge, Layout, buttons)
│       ├── api/ & lib/              ← Code that talks to the backend's API and shared helper functions
│       ├── App.tsx                  ← Defines which page shows at which web address (URL routing)
│       └── main.tsx                  ← Entry point that boots the React app
│
├── infra/                          ← Deployment/infrastructure config
│   └── docker-compose.yml            ← Meant to run Postgres/Redis/backend/frontend together (placeholder today)
│
├── docs/                            ← Project documentation
│   ├── PRD.md                        ← The full Product Requirements Document — the "why" and "what" behind everything
│   └── cURL-Import-Plan.md            ← Step-by-step plan for the cURL import feature
│
├── scripts/                         ← Top-level Windows helper scripts (start dev server, run tests, reset DB)
└── CLAUDE.md                        ← Instructions that guide AI coding assistants working on this repo
```

---

## Setup & Running It (on a new machine)

These instructions are written for **Windows**, since that's how this project is currently developed (PowerShell scripts, local PostgreSQL install). If you're on Mac/Linux, the same steps apply — just use the bash-equivalent commands instead of the `.ps1` scripts.

### 1. Prerequisites — install these first

- **Python 3.12+** — https://www.python.org/downloads/
- **Node.js 20+** (includes `npm`) — https://nodejs.org/
- **PostgreSQL 16+** — https://www.postgresql.org/download/ (the database)
- **Git** — to clone the repository
- An **API key for an AI provider**. The free/easiest option to start with is [NVIDIA NIM](https://build.nvidia.com/) (no credit card needed) or [Groq](https://console.groq.com/). Anthropic (Claude) and OpenAI keys also work.

### 2. Get the code

```powershell
git clone https://github.com/ramiz180/api-pilot.git
cd api-pilot
```

### 3. Set up the database

Create a PostgreSQL user and database matching the values in `backend/.env.example` (or change the values to match your own setup):

```sql
CREATE USER api_pilot WITH PASSWORD 'api_pilot_dev';
CREATE DATABASE api_pilot OWNER api_pilot;
```

### 4. Set up the backend

```powershell
cd backend
copy .env.example .env
```

Now open `backend/.env` and fill in:
- `DATABASE_URL` — if you used the example values above, you can leave this as-is.
- `LLM_PROVIDER` — which AI provider to use (`nvidia_nim`, `groq`, `openai`, or `anthropic`).
- The matching API key for whichever provider you chose (e.g. `NVIDIA_API_KEY=...`).

Then install dependencies and apply the database schema:

```powershell
.\scripts\install.ps1        # creates a Python virtual environment and installs everything
.\.venv\Scripts\Activate.ps1
alembic upgrade head          # creates all the database tables
```

### 5. Set up the frontend

```powershell
cd ..\frontend
copy .env.example .env
npm install
```

`frontend/.env` just needs `VITE_API_BASE_URL=http://localhost:8000`, which is already the default.

### 6. Run it

Open **two terminals** — one for the backend, one for the frontend.

**Terminal 1 — backend** (from the project root):
```powershell
.\scripts\dev-start.ps1
```
This checks PostgreSQL is running and starts the API server at **http://localhost:8000** (interactive API docs at http://localhost:8000/docs).

**Terminal 2 — frontend**:
```powershell
cd frontend
npm run dev
```
This starts the web app, normally at **http://localhost:5173**. Open that address in your browser.

### 7. Running the automated tests (optional, for developers)

```powershell
.\scripts\dev-test.ps1
```

This runs the backend's own automated test suite (currently 23 test files covering parsers, services, the execution engine, and the AI chat agent).

### Resetting the database (if you need a clean slate)

```powershell
.\scripts\db-reset.ps1
```
⚠️ This **deletes all data** in the local `api_pilot` database and re-applies migrations from scratch. It will ask you to type `yes` to confirm.

---

## Where to look next

- [docs/PRD.md](docs/PRD.md) — the full product vision, feature-by-feature, including things not built yet.
- [docs/cURL-Import-Plan.md](docs/cURL-Import-Plan.md) — the implementation plan for the cURL import feature.
- [backend/README.md](backend/README.md) — backend-specific conventions for developers.
- `backend/app/main.py` — see exactly which API routes exist today.
- `frontend/src/App.tsx` — see exactly which pages/screens exist today.

If anything here looks out of date as the project evolves, this file should be the first thing updated alongside the code change.
