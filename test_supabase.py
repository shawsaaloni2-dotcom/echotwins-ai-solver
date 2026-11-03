"""
test_supabase.py — Integration test suite for EchoTwins AI Supabase backend.
Run: python test_supabase.py
"""
import json
import time
import random
import string
import sys

def rand_email():
    s = ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
    return f"test_{s}@echotwins-test.ai"

# ── 1. Import db and test ping ─────────────────────────────────────────
print("=" * 60)
print("  EchoTwins AI — Supabase Integration Test")
print("=" * 60)

try:
    import db
    info = db.ping()
    print(f"[1/6] DB ping         PASS  db={info['database']}  time={info['server_time'][:19]}")
except Exception as e:
    print(f"[1/6] DB ping         FAIL  {e}")
    print("      Check DATABASE_URL in .env and try again.")
    sys.exit(1)

# ── 2. init_db (idempotent) ────────────────────────────────────────────
try:
    db.init_db()
    print("[2/6] init_db         PASS  (tables created or already exist)")
except Exception as e:
    print(f"[2/6] init_db         FAIL  {e}")
    sys.exit(1)

from sqlalchemy import text
from werkzeug.security import generate_password_hash, check_password_hash

# ── 3. Register a test student ────────────────────────────────────────
test_email = rand_email()
test_pwd   = "TestPass123!"
try:
    with db.get_conn() as conn:
        row = conn.execute(
            text("INSERT INTO students (name, email, password_hash) "
                 "VALUES (:n, :e, :p) RETURNING id, name, email"),
            {"n": "Test Runner", "e": test_email, "p": generate_password_hash(test_pwd)}
        ).fetchone()
        conn.commit()
    student_id = row[0]
    print(f"[3/6] Register        PASS  id={student_id}  email={test_email}")
except Exception as e:
    print(f"[3/6] Register        FAIL  {e}")
    sys.exit(1)

# ── 4. Login (verify password) ────────────────────────────────────────
try:
    with db.get_conn() as conn:
        row = conn.execute(
            text("SELECT id, name, password_hash FROM students WHERE email = :e"),
            {"e": test_email}
        ).fetchone()
    assert row and check_password_hash(row[2], test_pwd), "Password check failed"
    print(f"[4/6] Login           PASS  id={row[0]}  name={row[1]}")
except Exception as e:
    print(f"[4/6] Login           FAIL  {e}")

# ── 5. Bulk insert 10,000 test questions & measure query times ────────
print(f"\n  Inserting 10,000 test rows for student_id={student_id} …")
BATCH = 500
total_rows = 10_000
t0 = time.perf_counter()
try:
    with db.get_conn() as conn:
        for offset in range(0, total_rows, BATCH):
            batch_data = [
                {"sid": student_id, "q": f"Test question #{offset+i}", "ap": "[]", "ans": f"Answer #{offset+i}"}
                for i in range(BATCH)
            ]
            conn.execute(
                text("INSERT INTO questions (student_id, question, approaches, answer) "
                     "VALUES (:sid, :q, :ap, :ans)"),
                batch_data
            )
        conn.commit()
    insert_ms = (time.perf_counter() - t0) * 1000
    print(f"  Insert 10k rows:    {insert_ms:.0f} ms  ({insert_ms/total_rows:.2f} ms/row)")

    # -- Paginated history query (page 1, size 20)
    t1 = time.perf_counter()
    with db.get_conn() as conn:
        rows = conn.execute(
            text("SELECT id, question, answer, created_at FROM questions "
                 "WHERE student_id = :sid ORDER BY created_at DESC LIMIT 20 OFFSET 0"),
            {"sid": student_id}
        ).fetchall()
        total = conn.execute(
            text("SELECT COUNT(*) FROM questions WHERE student_id = :sid"),
            {"sid": student_id}
        ).scalar()
    hist_ms = (time.perf_counter() - t1) * 1000
    print(f"  History query:      {hist_ms:.1f} ms  (returned {len(rows)} rows, total={total})")

    # -- Admin students query (page 1, size 20 with JOIN)
    t2 = time.perf_counter()
    with db.get_conn() as conn:
        admin_rows = conn.execute(
            text("""
                SELECT s.id, s.name, s.email, s.role, s.created_at, COUNT(q.id)
                FROM students s
                LEFT JOIN questions q ON q.student_id = s.id
                GROUP BY s.id, s.name, s.email, s.role, s.created_at
                ORDER BY s.created_at DESC
                LIMIT 20 OFFSET 0
            """)
        ).fetchall()
    admin_ms = (time.perf_counter() - t2) * 1000
    print(f"  Admin query:        {admin_ms:.1f} ms  (returned {len(admin_rows)} rows)")

    result = "PASS"
    print(f"\n[5/6] Perf test       {result}")

except Exception as e:
    print(f"[5/6] Perf test       FAIL  {e}")

# ── 6. Cleanup test data ──────────────────────────────────────────────
try:
    with db.get_conn() as conn:
        deleted_q = conn.execute(
            text("DELETE FROM questions WHERE student_id = :sid"),
            {"sid": student_id}
        ).rowcount
        deleted_s = conn.execute(
            text("DELETE FROM students WHERE id = :sid"),
            {"sid": student_id}
        ).rowcount
        conn.commit()
    print(f"[6/6] Cleanup         PASS  deleted {deleted_q} questions + {deleted_s} student")
except Exception as e:
    print(f"[6/6] Cleanup         FAIL  {e}")

print("\n" + "=" * 60)
print("  All tests complete.")
print("=" * 60)

