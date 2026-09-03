# Infrastructure

## Local Development (Current Setup)

PostgreSQL 18 is installed locally on Windows.

| Setting | Value |
|---|---|
| Host | localhost |
| Port | 5432 |
| Database | api_pilot |
| User | api_pilot |
| Password | api_pilot_dev *(dev only — never commit to production)* |
| PostgreSQL bin | `C:\Program Files\PostgreSQL\18\bin` |

### Starting the dev server
```powershell
.\scripts\dev-start.ps1
```
Checks that PostgreSQL is running, activates the venv, and starts uvicorn with `--reload`.

### Running tests
```powershell
.\scripts\dev-test.ps1
```

### Resetting the database
```powershell
.\scripts\db-reset.ps1
```
⚠️ Destructive — drops and recreates `api_pilot`, then re-runs all Alembic migrations.

---

## Docker (Future — when Docker Desktop becomes available)

Docker Compose setup will be added for:

| Service | Purpose | Sprint |
|---|---|---|
| PostgreSQL | Containerised alternative to local install | When Docker available |
| Redis | Task queue + caching | Sprint 4+ |
| MinIO | Object storage (test artefacts) | Sprint 6+ |
| Backend container | Production-like local testing | When Docker available |

`infra/docker-compose.yml` is a placeholder — it will be populated once Docker Desktop is installed.

---

## Production Deployment

Three deployment modes are planned (see architecture docs):

- **Cloud** — managed Kubernetes (EKS or GKE) + managed Postgres (RDS/CloudSQL)
- **GPU On-Prem** — bare-metal with Kubernetes + local GPU for model inference
- **CPU On-Prem** — lighter footprint, CPU-only inference

Helm charts will live in `infra/helm/` (added in a later sprint).
