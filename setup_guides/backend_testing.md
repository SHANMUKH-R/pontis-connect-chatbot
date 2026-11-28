# Backend setup and testing guide

Follow these steps from database creation through API testing. Choose **one** database option: local Postgres using Docker, or Amazon RDS for PostgreSQL. Both use the same migrations and API code.

All terminal commands below run from the **repository root**, where `pyproject.toml`, `uv.lock`, and `main.py` are located. The commands use macOS/Linux shell syntax.

This is a procedure to run, not a record of successful tests. No tests, database provisioning, or deployment were performed when writing this guide.

## 1. Prerequisites

- [ ] Python 3.12+ and `uv` are installed.
- [ ] For local Postgres: Docker Desktop is installed and running.
- [ ] For RDS: you have AWS access to create or use a PostgreSQL instance and configure its network access.
- [ ] Use a development database for these checks.

Install the project and development dependencies into `.venv`:

```sh
uv sync
```

## 2. Configure the root `.env`

Create or edit `.env` beside `pyproject.toml`. Do not overwrite existing credentials. If your only `.env` is currently inside `src/pontis_chat/`, move it to the repository root first. The application and Alembic resolve `.env` relative to the working directory, not relative to their Python files.

For local Docker, use:

```dotenv
APP_NAME=Pontis Connect
DATABASE_URL=postgresql://pontis:local_password@localhost:5432/pontis
POSTGRES_PASSWORD=local_password
GUARDRAILS=true
HEALTH_STATUS=Ok
KNOWLEDGE_BASE_DIR=data/knowledge_base
REQUESTS_PER_MINUTE=19
DAILY_REQUEST_CAP=1000
SESSION_HISTORY_LIMIT=20
```

For RDS, replace `DATABASE_URL` as explained in section 3B. `POSTGRES_PASSWORD` is a Docker Compose setting; it does not configure RDS credentials.

Keep `.env`, credentials, and client documents out of Git. Do not `source .env`: the Python settings loader reads it directly, and values such as `APP_NAME` can contain spaces. Existing exported environment variables override values in `.env`; check for stale overrides if settings appear wrong.

## 3A. Create the local database using Docker

Skip this section if using RDS.

```sh
docker compose --env-file .env -f src/pontis_chat/compose.yaml up -d --wait
```

This command uses:

| File/component | Purpose |
| --- | --- |
| Root `.env` | Supplies `POSTGRES_PASSWORD` to Compose |
| `src/pontis_chat/compose.yaml` | Defines Postgres, port mapping, health check, and persistent volume |
| Docker Desktop | Runs the Postgres container |

The FastAPI Dockerfile is **not** used by this command. FastAPI will run locally in `.venv`.

On the first start with an empty volume, Postgres creates the `pontis` database and `pontis` user. The default local password is `local_password`. The database is accessible at `localhost:5432`.

Check container status:

```sh
docker compose --env-file .env -f src/pontis_chat/compose.yaml ps
```

Expected: the Postgres service is running and healthy.

**Existing volume:** changing `POSTGRES_PASSWORD` later does not reset the database user's password. Keep the connection string consistent with the password already in the database, or change that password through PostgreSQL. Do not delete a volume containing data you need.

Continue to section 4.

## 3B. Create the database using Amazon RDS

Skip this section if using local Docker. You do not need Docker to connect FastAPI to RDS.

1. In the AWS RDS console, choose **Create database** and the **PostgreSQL** engine.
2. Configure a development instance, its identifier, master username, and password. Review the displayed cost before creation.
3. Set **Initial database name** to `pontis`. The instance identifier and database name are different settings.
4. Create the instance and wait until it is available. Record its endpoint and port from **Connectivity & security**.

See AWS's [PostgreSQL creation walkthrough](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/CHAP_GettingStarted.CreatingConnecting.PostgreSQL.html) and [database settings reference](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/USER_CreateDBInstance.Settings.html).

Configure a network path from the machine running FastAPI. For direct laptop access, the instance needs public accessibility and suitable network routing; allow PostgreSQL TCP port 5432 in its security group from your current public IP (`/32`), not the entire internet. For a private instance, use an approved VPN, tunnel, or compute environment within its network. See [AWS connection instructions](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/USER_ConnectToPostgreSQLInstance.html).

Download the appropriate RDS CA bundle from AWS's [PostgreSQL TLS documentation](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/PostgreSQL.Concepts.General.SSL.html). Set the root `.env` connection string using your endpoint and local certificate path:

```dotenv
DATABASE_URL=postgresql://YOUR_USER:URL_ENCODED_PASSWORD@YOUR_RDS_ENDPOINT:5432/pontis?sslmode=verify-full&sslrootcert=/absolute/path/to/rds-ca-bundle.pem
```

Replace every placeholder. URL-encode special characters in the username/password; for example, an `@` in a password must be `%40`. Use the RDS hostname for certificate verification. The migration user needs permission to create tables in the target schema.

If you did not create `pontis` during provisioning, connect to the existing `postgres` database with a database client and run the following once using a role allowed to create databases:

```sql
CREATE DATABASE pontis;
```

Then point `DATABASE_URL` at `/pontis`. Alembic creates tables inside an existing database; it does not create the database itself.

## 4. Verify the connection before migrating

This checks the configured database without printing its password:

```sh
uv run python - <<'PY'
from sqlalchemy import text
from pontis_chat.appconfig import AppConfig
from pontis_chat.backend.database import database_engine

engine = database_engine(str(AppConfig().database_url))
try:
    with engine.connect() as connection:
        print(connection.execute(text('SELECT current_database(), current_user')).one())
finally:
    engine.dispose()
PY
```

Expected: the database name `pontis` and the configured user. Resolve connection errors before continuing.

## 5. Create the tables with Alembic

```sh
uv run alembic -c src/pontis_chat/alembic.ini upgrade head
uv run alembic -c src/pontis_chat/alembic.ini current
```

Expected revision: `0001_backend (head)`.

The layout is:

```text
src/pontis_chat/
├── alembic.ini
└── migrations/
    ├── env.py
    ├── script.py.mako
    └── versions/0001_backend.py
```

`alembic.ini` selects the migrations directory. `env.py` reads the database settings and connects. The revision creates these application tables:

- `sessions`
- `messages`
- `question_log`
- `token_usage`
- `uploads`
- `request_budget`

Alembic also maintains `alembic_version`. You can rerun `upgrade head`; already-applied revisions are not applied twice.

## 6. Start FastAPI

```sh
uv run uvicorn main:app --reload
```

Leave this terminal running. Use a second terminal at the repository root for the following checks.

- [ ] Open `http://127.0.0.1:8000/health`: expect `{"status":"Ok"}`.
- [ ] Open `http://127.0.0.1:8000/docs`: confirm the chat and session routes appear.
- [ ] Open `http://127.0.0.1:8000/`: confirm the website loads.

The health endpoint checks the process only. A successful health response does not prove that Postgres is reachable or migrated.

## 7. Test the existing `/chat` endpoint

```sh
curl -i http://127.0.0.1:8000/chat \
  -H 'Content-Type: application/json' \
  -d '{"question":"Which programs are available?","history":[]}'
```

Expected HTTP status: **200**. The JSON object must contain exactly:

```text
answer, sources, status, retrieved, mode, flags
```

An HTTP 200 can contain an application-level `status` of `unavailable` or `error`; inspect the response body too. Without knowledge-base documents, an unavailable answer with no sources is expected. Without model credentials, the service uses retrieval-only mode.

Check PII handling with synthetic data:

```sh
curl -i http://127.0.0.1:8000/chat \
  -H 'Content-Type: application/json' \
  -d '{"question":"Which programs are available? Email me at person@example.org","history":[]}'
```

Inspect recent records using the configured database (works for Docker and RDS):

```sh
uv run python - <<'PY'
from sqlalchemy import text
from pontis_chat.appconfig import AppConfig
from pontis_chat.backend.database import database_engine

engine = database_engine(str(AppConfig().database_url))
try:
    with engine.connect() as connection:
        rows = connection.execute(text(
            'SELECT id, question, status, mode FROM question_log ORDER BY id DESC LIMIT 5'
        ))
        for row in rows:
            print(row)
finally:
    engine.dispose()
PY
```

- [ ] Each completed chat call created one question-log row.
- [ ] The stored question does not contain `person@example.org`.
- [ ] API calls use the database log; direct agent/evaluation calls can still use JSONL.

## 8. Test session creation, history, access control, and deletion

Create a session:

```sh
curl -i -X POST http://127.0.0.1:8000/sessions
```

Expected: **201**, with `id` and `token`. Copy them into variables in your second terminal:

```sh
SESSION_ID='paste-returned-id'
SESSION_TOKEN='paste-returned-token'
```

Send a question and a follow-up:

```sh
curl -i "http://127.0.0.1:8000/sessions/$SESSION_ID/messages" \
  -H "Authorization: Bearer $SESSION_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"question":"Which programs are available?"}'

curl -i "http://127.0.0.1:8000/sessions/$SESSION_ID/messages" \
  -H "Authorization: Bearer $SESSION_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"question":"How do I join those programs?"}'
```

Expected: **200** and the same response shape as `/chat`. The second call loads earlier user questions as history. A meaningful follow-up answer also requires relevant knowledge-base content; the automated test below checks history delivery directly.

Retrieve the history:

```sh
curl -i "http://127.0.0.1:8000/sessions/$SESSION_ID/messages?after_id=0&limit=100" \
  -H "Authorization: Bearer $SESSION_TOKEN"
```

Expected: **200**, with four rows ordered as user, assistant, user, assistant. User rows have `response: null`; assistant rows include the redacted response. For pagination, use the last returned message ID as `after_id`.

Check unauthorized access:

```sh
curl -i "http://127.0.0.1:8000/sessions/$SESSION_ID/messages"

curl -i "http://127.0.0.1:8000/sessions/$SESSION_ID/messages" \
  -H 'Authorization: Bearer incorrect-token'
```

Expected: **404** for both. The token is required even when the session ID is known.

Check validation:

```sh
curl -i "http://127.0.0.1:8000/sessions/$SESSION_ID/messages" \
  -H "Authorization: Bearer $SESSION_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"question":""}'
```

Expected: **422**.

Delete the session:

```sh
curl -i -X DELETE "http://127.0.0.1:8000/sessions/$SESSION_ID" \
  -H "Authorization: Bearer $SESSION_TOKEN"

curl -i "http://127.0.0.1:8000/sessions/$SESSION_ID/messages" \
  -H "Authorization: Bearer $SESSION_TOKEN"
```

Expected: **204** for deletion, followed by **404** for retrieval. Session deletion cascades to its messages, question logs, token-usage records, and upload records. The automated integration test checks message and log deletion.

## 9. Test the per-IP limit without model calls

Wait at least **60 seconds** after prior API writes. Ensure `REQUESTS_PER_MINUTE=19`, sufficient daily budget remains, and no other client is sending requests from your IP. Then run:

```sh
uv run python - <<'PY'
import httpx

created = []
with httpx.Client(base_url='http://127.0.0.1:8000', timeout=30) as client:
    try:
        for number in range(1, 21):
            response = client.post('/sessions')
            print(number, response.status_code, response.headers.get('Retry-After', ''))
            if response.status_code == 201:
                created.append(response.json())
    finally:
        for session in created:
            response = client.delete(
                '/sessions/' + session['id'],
                headers={'Authorization': 'Bearer ' + session['token']},
            )
            if response.status_code != 204:
                print('Cleanup failed for session', session['id'], response.status_code)
PY
```

Expected: requests 1–19 return **201**; request 20 returns **429** with `Retry-After`. The script removes the sessions it creates. The same limiter protects chat and session messages. Session creation also counts against the daily budget.

Reservations persist in Postgres across API restarts. They are not refunded for failed downstream work. Daily limits reset at midnight UTC. Use the isolated automated daily-budget test in the next section instead of exhausting your shared development budget.

## 10. Run automated checks

Use a development database whose user can create and drop schemas. The integration tests create a unique schema per test and drop that schema afterward; they do not drop the public schema.

For local Docker:

```sh
BACKEND_TEST_DATABASE_URL=postgresql://pontis:local_password@localhost:5432/pontis \
  uv run pytest src/pontis_chat/tests/test_backend.py -q
```

For either database option, the following reads the existing `.env` settings and passes the DSN to pytest without placing the password directly in a shell command:

```sh
uv run python - <<'PY'
import os
import subprocess
from pontis_chat.appconfig import AppConfig

env = dict(os.environ)
env['BACKEND_TEST_DATABASE_URL'] = str(AppConfig().database_url)
raise SystemExit(subprocess.call(
    ['.venv/bin/python', '-m', 'pytest', '-q'], env=env,
))
PY
```

The second command runs the **full suite**, including the backend integration tests. The backend tests cover:

- Session creation and authorized access.
- Earlier user questions passed as follow-up history.
- Redacted stored content and database question logging.
- Session deletion removing messages and question logs.
- The unchanged `/chat` response fields.
- Refusal of the 20th request in a minute.
- A daily budget shared across IPs.

If `BACKEND_TEST_DATABASE_URL` is not provided, the backend integration tests skip. A skipped test is not evidence that the database integration works.

Run lint separately:

```sh
uv run ruff check .
```

## 11. Test cited answers and the website

- [ ] Place approved documents in the private directory named by `KNOWLEDGE_BASE_DIR`. Do not commit them.
- [ ] Restart the API after changing the knowledge base; the service is cached per process.
- [ ] Ask a question whose answer appears in the documents and verify the cited sources.
- [ ] Repeat from the website at `http://127.0.0.1:8000/`.
- [ ] To test model-backed answers, configure the provider credentials/model settings in `.env`, restart, and inspect the response `mode`. Model requests may incur charges.

The local site uses the same origin as FastAPI when the `chat-api-base` meta tag is empty. GitHub Pages additionally needs a reachable deployed backend URL in that tag and `CORS_ALLOWED_ORIGINS=https://shanmukh-r.github.io` exported in the backend process environment before startup. A locally running API alone does not connect the public site.

To inspect CORS locally, restart the API with:

```sh
CORS_ALLOWED_ORIGINS=https://shanmukh-r.github.io uv run uvicorn main:app --reload
```

Then send a preflight request:

```sh
curl -i -X OPTIONS http://127.0.0.1:8000/chat \
  -H 'Origin: https://shanmukh-r.github.io' \
  -H 'Access-Control-Request-Method: POST' \
  -H 'Access-Control-Request-Headers: content-type'
```

Expected: `Access-Control-Allow-Origin: https://shanmukh-r.github.io`. This verifies CORS configuration, not public deployment or browser connectivity to a hosted backend.

## 12. Troubleshooting and shutdown

| Symptom | Check |
| --- | --- |
| Missing `DATABASE_URL` | Run from the repository root and place `.env` there. |
| Connection refused locally | Start Docker, check the container health, and check for another service using port 5432. |
| RDS connection times out | Check endpoint, network path, public/private accessibility, and security-group source rules. |
| Password authentication fails | Check credentials, URL encoding, stale environment overrides, and the password in an existing Docker volume. |
| TLS verification fails | Check the CA bundle path and use the actual RDS endpoint hostname. |
| Database `pontis` does not exist | Create the database first; migrations only create its tables. |
| Missing relation/table or HTTP 503 | Verify connectivity and apply migrations to the same database the API uses. |
| HTTP 429 | Wait for the rolling minute limit or UTC-day reset; restarting the API does not clear reservations. |
| HTTP 409 on session writes | Another message/delete is in progress for that session; retry afterward. |
| HTTP 404 for a session | Check both the session ID and bearer token, and whether it was deleted. |
| Answer unavailable/no sources | Check knowledge-base contents and restart after changes. |
| Backend tests skip | Set `BACKEND_TEST_DATABASE_URL` in the test process environment. |

Stop FastAPI with **Ctrl+C**. For local Postgres:

```sh
docker compose --env-file .env -f src/pontis_chat/compose.yaml down
```

This retains the named database volume. Do not add `-v` unless you intentionally want to delete its stored data.

## What is not available to test yet

- File uploads: the schema exists, but no upload endpoint is exposed until safe session-specific indexing is integrated.
- Token counts: the schema exists, but replies do not yet provide counts for recording.
- Conversation compaction: not implemented; history is limited to the configured number of user turns.
- Hosted public chat: requires backend deployment, private knowledge-base delivery, and frontend configuration.
