"""Override only the existing log sink; the inherited answer pipeline is unchanged."""

import json
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from pontis_chat.agent.service import ChatReply, ChatService
from pontis_chat.agent.tools import ToolContext
from pontis_chat.guardrails.checks import redact_pii


class PersistentChatService(ChatService):
    def __init__(self, base: ChatService, db: Session, session_id: UUID | None = None):
        super().__init__(base.kb, base.settings, base.client)
        self.db = db
        self.session_id = session_id

    def _log(self, question: str, ctx: ToolContext, reply: ChatReply) -> None:
        # Always redact stored content, including when evaluation disables guardrails.
        self.db.execute(
            text("""
                INSERT INTO question_log
                    (session_id, time, question, topic, answerable, status, mode, flags, sources)
                VALUES (:session_id, :time, :question, :topic, :answerable, :status, :mode,
                        CAST(:flags AS jsonb), CAST(:sources AS jsonb))
            """),
            {
                "session_id": self.session_id,
                "time": datetime.now(UTC),
                "question": redact_pii(question)[0],
                "topic": redact_pii(ctx.topic)[0] if ctx.topic else None,
                "answerable": ctx.answerable,
                "status": reply.status,
                "mode": reply.mode,
                "flags": json.dumps([redact_pii(flag)[0] for flag in reply.flags]),
                "sources": json.dumps(
                    [redact_pii(source["url"])[0] for source in reply.sources]
                ),
            },
        )
