"""Sessions, redacted conversation records, upload metadata and shared budgets."""

from alembic import op

revision = "0001_backend"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE sessions (
            id uuid PRIMARY KEY,
            token_hash text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE TABLE messages (
            id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            session_id uuid NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
            role text NOT NULL CHECK (role IN ('user', 'assistant')),
            content text NOT NULL,
            response jsonb,
            created_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX messages_session_id ON messages (session_id, id)")
    op.execute("""
        CREATE TABLE question_log (
            id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            session_id uuid REFERENCES sessions(id) ON DELETE CASCADE,
            time timestamptz NOT NULL,
            question text NOT NULL,
            topic text,
            answerable boolean,
            status text NOT NULL,
            mode text NOT NULL,
            flags jsonb NOT NULL,
            sources jsonb NOT NULL
        )
    """)
    op.execute("CREATE INDEX question_log_session_id ON question_log (session_id)")
    op.execute("CREATE INDEX question_log_time ON question_log (time)")
    op.execute("""
        CREATE TABLE token_usage (
            id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            question_log_id bigint NOT NULL REFERENCES question_log(id) ON DELETE CASCADE,
            input_tokens bigint NOT NULL CHECK (input_tokens >= 0),
            output_tokens bigint NOT NULL CHECK (output_tokens >= 0),
            model text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute(
        "CREATE INDEX token_usage_question_log_id ON token_usage (question_log_id)"
    )
    op.execute("""
        CREATE TABLE uploads (
            id uuid PRIMARY KEY,
            session_id uuid NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
            filename text NOT NULL,
            media_type text NOT NULL,
            size_bytes bigint NOT NULL CHECK (size_bytes >= 0),
            page_count integer CHECK (page_count >= 0),
            redacted_text text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX uploads_session_id ON uploads (session_id)")
    op.execute("""
        CREATE TABLE request_budget (
            id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            ip_hash text NOT NULL,
            time timestamptz NOT NULL
        )
    """)
    op.execute("CREATE INDEX request_budget_ip_time ON request_budget (ip_hash, time)")
    op.execute("CREATE INDEX request_budget_time ON request_budget (time)")


def downgrade():
    for table in (
        "request_budget",
        "uploads",
        "token_usage",
        "question_log",
        "messages",
        "sessions",
    ):
        op.execute(f"DROP TABLE {table}")
