"""
db.py — EchoTwins AI database connection layer (Supabase PostgreSQL + SQLite fallback)

Supports Supabase PostgreSQL via connection pooling (port 6543) and
automatically falls back to local SQLite (echotwins.db) if DATABASE_URL
contains placeholder credentials or if the remote server is unreachable,
ensuring localhost runs immediately out of the box.
"""

import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()

raw_url = os.environ.get("DATABASE_URL", "").strip()

# Check if URL is unconfigured / placeholder
is_placeholder = (
    not raw_url
    or "YOURREF" in raw_url
    or "YOURPASSWORD" in raw_url
    or "YOUR_PASSWORD" in raw_url
    or "xxxxxxxxxxxx" in raw_url
)

def _build_engine(url: str):
    if is_placeholder:
        print("  [db] DATABASE_URL is placeholder/empty. Using local SQLite (echotwins.db).")
        return create_engine("sqlite:///echotwins.db")

    # If postgresql URL without explicit driver, check driver
    if url.startswith("postgresql://") or url.startswith("postgres://"):
        try:
            import psycopg  # noqa: F401
            url = url.replace("postgres://", "postgresql://", 1)
        except ImportError:
            # Fall back to pure-python pg8000 driver
            url = url.replace("postgresql://", "postgresql+pg8000://", 1)
            url = url.replace("postgres://", "postgresql+pg8000://", 1)

    try:
        if "sqlite" in url:
            return create_engine(url)
        return create_engine(
            url,
            pool_size=5,
            max_overflow=10,
            pool_pre_ping=True,
            pool_recycle=300,
            connect_args={"options": "-c statement_timeout=10000"} if "pg8000" not in url else {},
            execution_options={"no_parameters": False},
        )
    except Exception as err:
        print(f"  [db] Error creating Postgres engine: {err}. Falling back to SQLite.")
        return create_engine("sqlite:///echotwins.db")


_engine = _build_engine(raw_url)


def get_conn():
    """Return a connection from the pool (use as context manager)."""
    return _engine.connect()


def init_db():
    """
    Create tables if they do not exist yet.
    Compatible with both PostgreSQL and SQLite.
    """
    is_sqlite = _engine.dialect.name == "sqlite"
    id_col = "INTEGER PRIMARY KEY AUTOINCREMENT" if is_sqlite else "SERIAL PRIMARY KEY"
    time_col = "TIMESTAMP" if is_sqlite else "TIMESTAMPTZ"

    with _engine.connect() as conn:
        conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS students (
                id            {id_col},
                name          TEXT        NOT NULL,
                email         TEXT UNIQUE NOT NULL,
                password_hash TEXT        NOT NULL,
                role          TEXT        NOT NULL DEFAULT 'student',
                created_at    {time_col}  NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """))
        conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS questions (
                id          {id_col},
                student_id  INTEGER     NOT NULL REFERENCES students(id) ON DELETE CASCADE,
                question    TEXT        NOT NULL,
                approaches  TEXT,
                answer      TEXT,
                created_at  {time_col}  NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_questions_student_created
                ON questions (student_id, created_at DESC)
        """))
        conn.commit()
    db_type = "SQLite" if is_sqlite else "Supabase PostgreSQL"
    print(f"  [db] Tables ready ({db_type}).")


def ping():
    """Verify database connection."""
    is_sqlite = _engine.dialect.name == "sqlite"
    query = "SELECT 'echotwins.db', datetime('now')" if is_sqlite else "SELECT current_database(), now()::text"
    with _engine.connect() as conn:
        result = conn.execute(text(query)).fetchone()
    return {"database": result[0], "server_time": str(result[1])}
