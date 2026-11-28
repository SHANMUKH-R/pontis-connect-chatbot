"""Opt-in Postgres integration checks; each test owns a disposable schema."""

import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import make_url

from main import create_app
from pontis_chat.agent.service import ChatService, ChatSettings, get_chat_service
from pontis_chat.appconfig import AppConfig
from pontis_chat.backend.database import database_engine
from pontis_chat.rag import KnowledgeBase


@pytest.fixture
def backend(monkeypatch, tmp_path):
    database_url = os.environ.get("BACKEND_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip(
            "Set BACKEND_TEST_DATABASE_URL for isolated-schema integration checks"
        )
    schema = "backend_test_" + uuid4().hex
    admin = database_engine(database_url)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    isolated_url = make_url(database_url).update_query_dict(
        {"options": f"-csearch_path={schema}"}
    )
    isolated_url = isolated_url.render_as_string(hide_password=False)
    monkeypatch.setenv("DATABASE_URL", isolated_url)
    try:
        command.upgrade(
            Config(str(Path(__file__).resolve().parents[1] / "alembic.ini")), "head"
        )
        app = create_app(AppConfig(_env_file=None, database_url=isolated_url))
        base = ChatService(
            KnowledgeBase.from_directory(tmp_path),
            ChatSettings(
                _env_file=None,
                anthropic_api_key=None,
                question_log_path=str(tmp_path / "questions.jsonl"),
            ),
        )
        app.dependency_overrides[get_chat_service] = lambda: base
        with TestClient(app) as client:
            yield client, app, tmp_path
    finally:
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def test_session_history_redaction_and_delete(backend, monkeypatch):
    client, app, directory = backend
    histories = []
    original = ChatService._retrieval_only_reply

    def capture(self, ctx, query, history):
        histories.append(list(history))
        return original(self, ctx, query, history)

    monkeypatch.setattr(ChatService, "_retrieval_only_reply", capture)
    created = client.post("/sessions")
    assert created.status_code == 201
    session_id = created.json()["id"]
    headers = {"Authorization": "Bearer " + created.json()["token"]}
    path = f"/sessions/{session_id}"
    assert client.get(path + "/messages").status_code == 404
    assert (
        client.post(
            path + "/messages",
            headers=headers,
            json={
                "question": "Which programs are available? Email me at person@example.org"
            },
        ).status_code
        == 200
    )
    assert (
        client.post(
            path + "/messages",
            headers=headers,
            json={"question": "How do I join those programs?"},
        ).status_code
        == 200
    )
    assert len(histories[-1]) == 1
    assert "programs" in histories[-1][0]
    assert "person@example.org" not in histories[-1][0]
    messages = client.get(path + "/messages", headers=headers)
    assert [row["role"] for row in messages.json()] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]
    assert "person@example.org" not in messages.text
    with app.state.database_engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM question_log")) == 2
        assert "person@example.org" not in str(
            connection.execute(text("SELECT question FROM question_log")).all()
        )
    assert not (directory / "questions.jsonl").exists()
    assert client.delete(path, headers=headers).status_code == 204
    assert client.get(path + "/messages", headers=headers).status_code == 404
    with app.state.database_engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM messages")) == 0
        assert connection.scalar(text("SELECT count(*) FROM question_log")) == 0


def test_chat_shape_and_twentieth_request_refused(backend):
    client, app, _ = backend
    for _ in range(19):
        response = client.post(
            "/chat", json={"question": "Which programs are available?", "history": []}
        )
        assert response.status_code == 200
        assert set(response.json()) == {
            "answer",
            "sources",
            "status",
            "retrieved",
            "mode",
            "flags",
        }
    refused = client.post("/chat", json={"question": "Which programs are available?"})
    assert refused.status_code == 429
    assert int(refused.headers["Retry-After"]) > 0
    with app.state.database_engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM question_log")) == 19


def test_daily_budget_is_shared_across_ips(backend):
    client, app, _ = backend
    app.state.app_config = app.state.app_config.model_copy(
        update={"daily_request_cap": 1}
    )
    with app.state.database_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO request_budget (ip_hash, time) VALUES ('another-ip', now())"
            )
        )
    response = client.post("/chat", json={"question": "Which programs are available?"})
    assert response.status_code == 429
    assert "Daily" in response.json()["detail"]
