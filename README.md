# i2ai Team Project — Fall 2026 (95-891)
### Team Pontis · Project: Connect ChatBot

Team-based client engagement applying agentic AI to a real-world problem.

## Team Pontis
| Name | Andrew ID | GitHub | Role |
|------|-----------|--------|------|
| Shanmukh Rachakunta | srachaku | @SHANMUKH-R | PM / client comms / agentic-AI design |
| Jack | _[id]_ | _[@]_ | |
| Premices | _[id]_ | _[@]_ | |
| Akshay Iyer | akshayiy | @aksh-iyer | Backend Developer, Agentic AI Development |
| Alan | _[id]_ | _[@]_ | |

## Client / Problem
- **Project:** Connect ChatBot
- **Client:** to be confirmed (client engagement has not started yet)
- **Problem (as understood):** How can the client's membership website become more
  responsive to its members? A chatbot answers member questions, **tracks what members
  ask**, surfaces membership needs/patterns to the organization, and turns those into
  **actionable changes to the website**.
- **Success by December:** _[to confirm at first client meeting, Oct 2]_

## Project links
- 🌐 **Live demo (student prototype):** https://shanmukh-r.github.io/pontis-connect-chatbot/
- 📋 **Kanban board:** _[paste GitHub Project URL here once created]_
- 📄 Team contract: [`docs/team-contract.md`](docs/team-contract.md)
- 📄 Client meeting prep: [`docs/client-meeting-prep.md`](docs/client-meeting-prep.md)
- 📄 Project scope (PMI): [`docs/project-scope.md`](docs/project-scope.md)
- 🤝 How we work (PR rules): [`CONTRIBUTING.md`](CONTRIBUTING.md)

## Repo structure
```
docs/            team contract, client prep, scope doc, meeting notes
data/            datasets (gitignored — see .gitignore; respect NDA)
notebooks/       exploration
src/             project code
```

## Deliverables (TP1 — due Oct 2, 5pm · Canvas closes Oct 6, 5pm)
- [ ] Signed team contract
- [ ] Client meeting prep (~1 page)
- [ ] Project scope document (sent to client)
- [ ] This kanban board, linked in the scope doc


## Run the API

Requires Python 3.12+ and uv. From the repository root:

```sh
cp src/pontis_chat/.env.example .env
uv sync
docker compose --env-file .env -f src/pontis_chat/compose.yaml up -d --wait
uv run alembic -c src/pontis_chat/alembic.ini upgrade head
uv run uvicorn main:app --reload
```

Visit http://127.0.0.1:8000/docs for interactive API documentation or
http://127.0.0.1:8000/health for process health. Health does not check Postgres.

## Structure

```text
main.py                         # Compatibility ASGI entry point (not installed)
src/pontis_chat/
├── application.py              # App factory, lifespan and router registration
├── backend/                    # Database, logging and request budgets
├── migrations/                 # Alembic migration environment and revisions
├── alembic.ini                 # Migration configuration
├── compose.yaml                # Local Postgres
├── Dockerfile                  # Backend image; build from repository root
├── Dockerfile.dockerignore     # Image build context exclusions
├── .env.example                # Placeholder configuration
├── docs/backend.md             # Setup and deployment instructions
├── tests/test_backend.py       # Opt-in Postgres integration checks
├── dependency_injectors.py      # Startup initializer and AppConfigDep alias
├── appconfig/
│   ├── __init__.py
│   └── app_config.py            # Typed configuration and app.state accessor
└── routes/
    ├── sessions/                # Session creation, messages, history and deletion
    ├── __init__.py
    └── test_app/
        ├── __init__.py          # Exports the feature router
        └── health.py            # GET /health using injected configuration
```

`AppConfig` extends Pydantic's `BaseSettings` (a `BaseModel` subclass). The lifespan
handler loads and validates settings once per application startup, before requests
are served, and stores them on `app.state.app_config`. Importing the app does not
read configuration. Missing `DATABASE_URL` or invalid values prevent startup.

Settings are resolved in this order: explicit constructor values, process environment,
`.env`, then field defaults. `.env` is relative to the working directory; use
`create_app(env_file="/path/to/.env")` for another location. Unrelated `.env` entries
are ignored. Settings stay fixed until restart; they are not copied into `os.environ`.
Keep credentials in the ignored `.env` file or deployment environment.

| Variable | Type | Default |
| --- | --- | --- |
| `APP_NAME` | Nonempty string | `Pontis Connect` |
| `DATABASE_URL` | PostgreSQL DSN | Required |
| `GUARDRAILS` | Boolean | `true` |
| `HEALTH_STATUS` | Nonempty string | `Ok` |

Use the startup-loaded settings in new routes through dependency injection:

```python
from fastapi import APIRouter
from pontis_chat.dependency_injectors import AppConfigDep

router = APIRouter()


@router.get("/example")
async def example(config: AppConfigDep):
    return {"status": config.health_status}
```

`AppConfigDep` is `Annotated[AppConfig, Depends(get_app_config)]`. Its accessor
returns the same config object from `request.app.state.app_config`, without
rereading the environment. FastAPI resolves `Depends` in request handlers, not
lifespan handlers, so lifespan calls `initialize_app_config` directly before
`yield`. All configuration is available before routes receive requests.

`GET /health` returns `{"status": "Ok"}` with the example configuration. Set
`HEALTH_STATUS` to another string to change the response. This is process health,
not a database readiness check.

The application creates a Postgres connection pool during startup and disposes of it
at shutdown. Chat requests require the migrated database. Session routes use bearer
tokens; `/chat` remains public and keeps its existing response fields.

## Checks

```sh
uv run ruff check .
uv run ruff format --check .
uv run pytest -q
```

Backend integration tests use a disposable schema in the Postgres database named by
`BACKEND_TEST_DATABASE_URL`; they skip when it is unset. No pgvector extension is
needed for this schema. See [backend setup and deployment](src/pontis_chat/docs/backend.md).