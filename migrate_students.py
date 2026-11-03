"""
migrate_students.py — One-time import of students.json into Supabase.

Run ONCE after setting DATABASE_URL in .env:
    python migrate_students.py

students.json is left untouched as a backup.
"""

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from werkzeug.security import generate_password_hash
from sqlalchemy import text

load_dotenv()

# Import after load_dotenv so DATABASE_URL is available
import db  # noqa: E402 (must come after load_dotenv)

SRC = Path(__file__).parent / "students.json"


def is_plain_sha256(s: str) -> bool:
    """Return True if the string looks like a raw SHA-256 hex digest (not a werkzeug hash)."""
    return len(s) == 64 and all(c in "0123456789abcdefABCDEF" for c in s)


def migrate():
    if not SRC.exists():
        print(f"[ERROR] {SRC} not found. Nothing to migrate.")
        sys.exit(1)

    with open(SRC, "r", encoding="utf-8") as f:
        data = json.load(f)

    students = data.get("students", [])
    if not students:
        print("[INFO] students.json contains no students. Nothing to migrate.")
        return

    print(f"[INFO] Migrating {len(students)} student(s) from students.json …")

    db.init_db()

    inserted = 0
    skipped  = 0

    with db.get_conn() as conn:
        for s in students:
            email = (s.get("email") or "").strip().lower()
            name  = (s.get("name")  or "").strip()
            raw   = s.get("password", "")

            if not email or not name:
                print(f"  [SKIP] Missing name/email for record id={s.get('id')}")
                skipped += 1
                continue

            # Re-hash legacy SHA-256 passwords with werkzeug PBKDF2
            if is_plain_sha256(raw):
                # We cannot recover the plain-text, so we set a locked account
                # password. The user must reset their password.
                pwd_hash = generate_password_hash("__LOCKED__sha256_migrated__")
                print(f"  [WARN] {email}: legacy SHA-256 hash replaced with locked placeholder.")
            elif raw.startswith("pbkdf2:") or raw.startswith("scrypt:"):
                # Already a werkzeug hash
                pwd_hash = raw
            else:
                # Plain text (shouldn't happen, but handle it)
                pwd_hash = generate_password_hash(raw)

            role       = s.get("role", "student")
            created_at = s.get("joinDate", None)  # will be cast to timestamptz by PG

            try:
                conn.execute(
                    text("""
                        INSERT INTO students (name, email, password_hash, role, created_at)
                        VALUES (:name, :email, :pwd, :role,
                                COALESCE(:created_at, CURRENT_TIMESTAMP))
                        ON CONFLICT (email) DO NOTHING
                    """),
                    {"name": name, "email": email, "pwd": pwd_hash,
                     "role": role, "created_at": created_at},
                )
                inserted += 1
            except Exception as exc:
                print(f"  [ERROR] Failed to insert {email}: {exc}")
                skipped += 1

        conn.commit()

    print(f"\n[DONE] Inserted: {inserted}  Skipped/errors: {skipped}")
    print("students.json has been left in place as a backup.")


if __name__ == "__main__":
    migrate()

