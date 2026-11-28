import hashlib
import json
import secrets
from datetime import datetime
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from pydantic import BaseModel, Field, JsonValue
from sqlalchemy import text

from pontis_chat.backend.database import DatabaseDep
from pontis_chat.backend.limits import enforce_limits
from pontis_chat.backend.service import PersistentChatService
from pontis_chat.dependency_injectors import AppConfigDep
from pontis_chat.guardrails.checks import redact_pii
from pontis_chat.routes.chat.chat import ChatResponse, ChatServiceDep

router = APIRouter(prefix="/sessions", tags=["sessions"])
Authorization = Annotated[str | None, Header()]


class SessionCreated(BaseModel):
    id: UUID
    token: str


class MessageRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1500)


class StoredMessage(BaseModel):
    id: int
    role: str
    content: str
    response: ChatResponse | None
    created_at: datetime


def authorize_session(
    db, session_id: UUID, authorization: str | None, *, lock: bool = False
):
    if lock:
        key = int.from_bytes(session_id.bytes[:8], "big", signed=True)
        if not db.scalar(text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": key}):
            raise HTTPException(
                409, "Session is busy. Retry after the current request finishes."
            )
    token = (
        authorization.removeprefix("Bearer ")
        if authorization and authorization.startswith("Bearer ")
        else ""
    )
    row = db.execute(
        text("SELECT token_hash FROM sessions WHERE id = :id"), {"id": session_id}
    ).first()
    if not row or not secrets.compare_digest(
        row.token_hash, hashlib.sha256(token.encode()).hexdigest()
    ):
        raise HTTPException(404, "Session not found.")


@router.post(
    "",
    response_model=SessionCreated,
    status_code=201,
    dependencies=[Depends(enforce_limits)],
)
def create_session(db: DatabaseDep, response: Response):
    session_id, token = uuid4(), secrets.token_urlsafe(32)
    with db.begin():
        db.execute(
            text("INSERT INTO sessions (id, token_hash) VALUES (:id, :token)"),
            {"id": session_id, "token": hashlib.sha256(token.encode()).hexdigest()},
        )
    response.headers["Cache-Control"] = "no-store"
    return SessionCreated(id=session_id, token=token)


@router.delete("/{session_id}", status_code=204)
def delete_session(
    session_id: UUID, db: DatabaseDep, authorization: Authorization = None
):
    with db.begin():
        authorize_session(db, session_id, authorization, lock=True)
        db.execute(text("DELETE FROM sessions WHERE id = :id"), {"id": session_id})
    return Response(status_code=204)


@router.get("/{session_id}/messages", response_model=list[StoredMessage])
def list_messages(
    session_id: UUID,
    db: DatabaseDep,
    response: Response,
    authorization: Authorization = None,
    after_id: int = 0,
    limit: int = 100,
):
    if after_id < 0 or not 1 <= limit <= 100:
        raise HTTPException(422, "Use after_id >= 0 and limit between 1 and 100.")
    authorize_session(db, session_id, authorization)
    response.headers["Cache-Control"] = "no-store"
    return (
        db.execute(
            text("""
        SELECT id, role, content, response, created_at FROM messages
        WHERE session_id = :session_id AND id > :after_id ORDER BY id LIMIT :limit
    """),
            {"session_id": session_id, "after_id": after_id, "limit": limit},
        )
        .mappings()
        .all()
    )


@router.post(
    "/{session_id}/messages",
    response_model=ChatResponse,
    dependencies=[Depends(enforce_limits)],
)
def send_message(
    session_id: UUID,
    body: MessageRequest,
    db: DatabaseDep,
    service: ChatServiceDep,
    config: AppConfigDep,
    response: Response,
    authorization: Authorization = None,
):
    with db.begin():
        authorize_session(db, session_id, authorization, lock=True)
        history = list(
            reversed(
                db.scalars(
                    text("""
            SELECT content FROM messages WHERE session_id = :id AND role = 'user'
            ORDER BY id DESC LIMIT :limit
        """),
                    {"id": session_id, "limit": config.session_history_limit},
                ).all()
            )
        )
        question = redact_pii(body.question)[0]
        reply = PersistentChatService(service, db, session_id).answer(question, history)
        result = ChatResponse(**vars(reply))

        # Redact every string in the stored response, including metadata. Do not
        # redact serialized JSON (doing so can corrupt JSON escape sequences).
        def redact(value: JsonValue) -> JsonValue:
            if isinstance(value, str):
                return redact_pii(value)[0]
            if isinstance(value, list):
                return [redact(item) for item in value]
            if isinstance(value, dict):
                return {key: redact(item) for key, item in value.items()}
            return value

        stored = {key: redact(value) for key, value in result.model_dump().items()}
        db.execute(
            text("""
            INSERT INTO messages (session_id, role, content) VALUES (:id, 'user', :question)
        """),
            {"id": session_id, "question": question},
        )
        db.execute(
            text("""
            INSERT INTO messages (session_id, role, content, response)
            VALUES (:id, 'assistant', :answer, CAST(:response AS jsonb))
        """),
            {
                "id": session_id,
                "answer": stored["answer"],
                "response": json.dumps(stored),
            },
        )
    response.headers["Cache-Control"] = "no-store"
    return result
