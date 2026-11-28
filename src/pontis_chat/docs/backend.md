# Backend setup

Backend implementation, migrations, deployment files, example configuration, and
integration tests live under `src/pontis_chat/`. Run the commands below from the
repository root. `main.py` is a compatibility entry point that imports the
application from `pontis_chat.application`.

```sh
cp src/pontis_chat/.env.example .env
uv sync
docker compose --env-file .env -f src/pontis_chat/compose.yaml up -d --wait
uv run alembic -c src/pontis_chat/alembic.ini upgrade head
uv run uvicorn main:app --reload
```

Local Compose binds Postgres to localhost and retains its data in a named volume.
The example password is for local development. Set `DATABASE_URL` and
`POSTGRES_PASSWORD` consistently if you change it. Migrations run explicitly, not
at application startup. `GET /health` checks the process, not database readiness.

## API

`POST /chat` still accepts `{question, history}` and returns exactly
`{answer, sources, status, retrieved, mode, flags}`. It now needs Postgres.
Every successful call through the service pipeline writes one `question_log` row
in the same transaction as any session messages. Rate-limited or invalid requests
do not invoke the model and do not create question logs. Infrastructure failures
return 503, and their transaction rolls back.

The database service subclasses `ChatService` outside the agent package and
overrides only `_log`. The inherited `answer` method still handles the agent and
guardrails. API calls no longer append JSONL. Direct uses of the original service
(including evaluation scripts that instantiate it) retain their existing behavior.
This adapter depends on the existing `_log` hook; coordinate changes to that hook
with the agent owner.

1. `POST /sessions` with no body returns `{id, token}` (201). Retain the token;
   only its SHA-256 hash is stored and it cannot be recovered.
2. Send `Authorization: Bearer <token>` for all routes below.
3. `POST /sessions/{id}/messages` with `{question}` returns the same chat response
   as `/chat`. It loads up to the most recent 20 user questions as history.
4. `GET /sessions/{id}/messages?after_id=0&limit=100` returns an ordered array of
   `{id, role, content, response, created_at}`. The user row has a null response;
   the assistant row has the redacted chat response. Paginate using the last id.
5. `DELETE /sessions/{id}` returns 204 and cascades to messages, question logs,
   token usage, and uploads. Unknown ids and invalid tokens both return 404.

Concurrent sends or deletes for the same session return 409 while a write is in
progress. Retry after it finishes. Model calls hold a connection and transaction
for that session; the pool bounds concurrent database work. The current static
frontend still uses `/chat`; session UI is not included.

Incoming API questions/history and stored output strings use the existing PII
redactor, even if guardrails are disabled for evaluation. Its coverage is the
existing email, phone, and ID patterns; it is not a general anonymizer. Raw
questions, bearer tokens and uploaded files are not logged by the new backend.

## Request budgets

`REQUESTS_PER_MINUTE=19` allows 19 requests per IP in a rolling 60-second window,
refusing the 20th. `DAILY_REQUEST_CAP=1000` is a shared UTC-day cap. Both apply
to `/chat`, session creation, and sending session messages. Reservations commit
before work and are not refunded for downstream failures, protecting model spend
on retries. Rejections return 429 with `Retry-After`. Settings must be identical
across replicas. Postgres locks make reservations atomic across workers/restarts.
Expired budget records are cleaned during reservations. IPs are stored as hashes,
not raw addresses; hashes remain pseudonymous data.

Use Uvicorn's `--forwarded-allow-ips` only with the actual trusted ingress proxy
addresses. The application uses the resolved ASGI peer address, not arbitrary
forwarded headers. With no trusted ingress configured, proxy users share one
budget. Never use `*` on a service directly reachable from the internet.

## Deployment preparation

The Dockerfile packages only application and frontend files; `.env`, `data/` and
client material are excluded. Build with `docker build -f src/pontis_chat/Dockerfile -t pontis-backend .`.
The image serves on port 8000 as a non-root user. If the host requires another
port, override the startup command with `uvicorn main:app --host 0.0.0.0 --port
<assigned-port>`. Run `alembic -c src/pontis_chat/alembic.ini upgrade head` as a release command with the same
database secrets before serving traffic.

Configure these in the hosting service's secret/environment settings:

- `DATABASE_URL`: hosted Postgres connection string, with TLS as required by it.
- `CORS_ALLOWED_ORIGINS=https://shanmukh-r.github.io`.
- The chosen model credentials/settings from `src/pontis_chat/.env.example` and the agent docs.
- `KNOWLEDGE_BASE_DIR`: a private read-only directory populated outside Git.
- The request budgets above.

Agree on the private knowledge-base delivery mechanism with the agent owner
before deployment. A host-provided private volume must be readable by UID 10001.
Do not include documents in a public image or Git repository. No host has been
provisioned and no knowledge base has been uploaded by this implementation.

After obtaining a working HTTPS backend URL, set the existing `chat-api-base`
meta tag in `index.html` to that URL and publish the frontend. It remains empty
until then so the backend-served site continues to use its own origin. Verify
a cited answer from GitHub Pages and the rate limit against the deployed host.

## Pending agent integration

- `token_usage` has a schema but is not populated: `ChatReply` does not yet expose
  input/output token counts. Counts must include all model calls in the agent loop;
  do not invent counts or store zero as a placeholder.
- The existing redactor and log-hook argument provide redacted storage now. A
  future explicit redacted-question reply field can replace this adapter coupling.
- `uploads` has a cascading schema only. No upload endpoint is exposed until the
  agent owner supplies safe session-specific indexing/search. The later endpoint
  must validate PDF/TXT/DOCX content, bound bytes/pages/extraction resources, redact
  extracted text, and call that hook without adding content to the shared corpus.
- Conversation compaction is deferred. History is bounded by
  `SESSION_HISTORY_LIMIT` (1–20 user turns); older rows remain available via GET.

## Validation status

Tests were not run for this implementation, as requested. Docker startup,
migrations against a live database, deployment, and a public cited response are
not verified. Backend integration tests can be run later with
`BACKEND_TEST_DATABASE_URL=postgresql://... uv run pytest src/pontis_chat/tests/test_backend.py -q`.
They create and drop their own uniquely named schema, never the public schema.
