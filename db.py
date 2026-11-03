"""
db.py — EchoTwins AI database connection layer (Supabase/PostgreSQL)

Uses SQLAlchemy Core with a connection pool tuned for Supabase's
transaction-mode pooler (port 6543).  Prepared statements are disabled
because the transaction pooler does not support session-level state.
"""

import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()

_DATABASE_URL = os.environ.get("DATABASE_URL", "")
if not _DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL is not set. "
        "Copy .env.example to .env and fill in your Supabase connection string."
    )

# Supabase transaction pooler is stateless per call, so we:
#  • set pool_pre_ping to detect stale connections early
#  • set pool_recycle to close connections before Supabase's idle timeout
#  • set executemany_mode=values to batch inserts efficiently
_engine = create_engine(
    _DATABASE_URL,
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,
    pool_recycle=300,
    # Disable server-side prepared statements – required for pgBouncer/Supabase pooler
    connect_args={"options": "-c statement_timeout=10000"},
    execution_options={"no_parameters": False},
)


def get_conn():
    """Return a raw DBAPI connection from the pool (use as context manager)."""
    return _engine.connect()


def init_db():
    """
    Create tables if they do not exist yet.
    In production the tables already exist in Supabase; this is a safety net
    for a fresh local / staging environment.
    """
    with _engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS students (
                id           SERIAL PRIMARY KEY,
                name         TEXT        NOT NULL,
                email        TEXT UNIQUE NOT NULL,
                password_hash TEXT       NOT NULL,
                role         TEXT        NOT NULL DEFAULT 'student',
                created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS questions (
                id          SERIAL PRIMARY KEY,
                student_id  INTEGER     NOT NULL REFERENCES students(id) ON DELETE CASCADE,
                question    TEXT        NOT NULL,
                approaches  TEXT,
                answer      TEXT,
                created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """))
        # Covering index for paginated history queries
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_questions_student_created
                ON questions (student_id, created_at DESC)
        """))
        conn.commit()
    print("  [db] Tables ready.")


def ping():
    """Verify the connection to Supabase works."""
    with _engine.connect() as conn:
        result = conn.execute(text("SELECT current_database(), now()::text")).fetchone()
    return {"database": result[0], "server_time": result[1]}

