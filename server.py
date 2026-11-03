#!/usr/bin/env python3
"""
EchoTwins AI — Backend Server  (Supabase / PostgreSQL edition)
==============================================================
Serves static HTML/JS/CSS from the project directory AND provides a
JSON REST API backed by a Supabase PostgreSQL database.

Run:
    python server.py

Endpoints
─────────
POST /api/register          Register a new student
POST /api/login             Authenticate (returns student profile, no password)
POST /api/questions         Save a solved question (student must be logged in)
GET  /api/history           Paginated question history for the logged-in student
                            ?student_id=<id>&page=<n>&size=<n>
GET  /api/admin/students    Admin: paginated student list with question counts
                            ?page=<n>&size=<n>
GET  /api/admin/stats       Admin: aggregate stats
GET  /api/ping              Health-check / DB connectivity test

All admin endpoints require the header:
    X-Admin-Secret: <value of ADMIN_SECRET in .env>
"""

import json
import os
import time
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import text

load_dotenv()

import db  # noqa: E402

ADMIN_SECRET = os.environ.get("ADMIN_SECRET", "")
PORT         = int(os.environ.get("PORT", 3000))
PAGE_DEFAULT = 20
PAGE_MAX     = 100


# ══════════════════════════════════════════════════════════════════════════════
# Helper utilities
# ══════════════════════════════════════════════════════════════════════════════

def _page_params(params: dict) -> tuple[int, int]:
    """Parse page/size query params; clamp size to PAGE_MAX."""
    try:
        page = max(1, int(params.get("page", ["1"])[0]))
    except (ValueError, TypeError):
        page = 1
    try:
        size = min(PAGE_MAX, max(1, int(params.get("size", [str(PAGE_DEFAULT)])[0])))
    except (ValueError, TypeError):
        size = PAGE_DEFAULT
    return page, size


# ══════════════════════════════════════════════════════════════════════════════
# Request handler
# ══════════════════════════════════════════════════════════════════════════════

class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=os.path.dirname(__file__), **kwargs)

    def log_message(self, fmt, *args):  # quiet file-serving noise, keep API logs
        path = self.path.split("?")[0]
        if path.startswith("/api"):
            print(f"  {self.address_string()} -> {fmt % args}")

    # ── CORS ──────────────────────────────────────────────────────────────────
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin",  "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Admin-Secret")

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors()
        self.end_headers()

    # ── JSON helpers ──────────────────────────────────────────────────────────
    def _json(self, code: int, payload: dict):
        body = json.dumps(payload, default=str).encode()
        self.send_response(code)
        self.send_header("Content-Type",   "application/json")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length)) if length else {}

    def _is_admin(self) -> bool:
        secret = self.headers.get("X-Admin-Secret", "")
        return bool(ADMIN_SECRET) and secret == ADMIN_SECRET

    # ── POST /api/register ────────────────────────────────────────────────────
    def _register(self):
        body  = self._body()
        name  = (body.get("name",     "") or "").strip()
        email = (body.get("email",    "") or "").strip().lower()
        pwd   = (body.get("password", "") or "")
        if not name or not email or not pwd:
            return self._json(400, {"error": "name, email and password are required"})
        if len(pwd) < 6:
            return self._json(400, {"error": "Password must be at least 6 characters"})

        pwd_hash = generate_password_hash(pwd)
        try:
            with db.get_conn() as conn:
                row = conn.execute(
                    text("""
                        INSERT INTO students (name, email, password_hash)
                        VALUES (:name, :email, :pwd)
                        RETURNING id, name, email, role, created_at
                    """),
                    {"name": name, "email": email, "pwd": pwd_hash},
                ).fetchone()
                conn.commit()
        except Exception as exc:
            msg = str(exc)
            if "unique" in msg.lower() or "duplicate" in msg.lower():
                return self._json(409, {"error": "Email already registered"})
            print(f"  [ERROR] register: {exc}")
            return self._json(500, {"error": "Database error"})

        student = {"id": row[0], "name": row[1], "email": row[2],
                   "role": row[3], "created_at": str(row[4])}
        print(f"  [OK] Registered: {name} <{email}>")
        return self._json(201, {"ok": True, "student": student})

    # ── POST /api/login ───────────────────────────────────────────────────────
    def _login(self):
        body  = self._body()
        email = (body.get("email",    "") or "").strip().lower()
        pwd   = (body.get("password", "") or "")
        if not email or not pwd:
            return self._json(400, {"error": "email and password are required"})

        with db.get_conn() as conn:
            row = conn.execute(
                text("""
                    SELECT id, name, email, password_hash, role, created_at
                    FROM students WHERE email = :email
                """),
                {"email": email},
            ).fetchone()

        if not row:
            return self._json(401, {"error": "Email not found"})
        if not check_password_hash(row[3], pwd):
            return self._json(401, {"error": "Incorrect password"})

        student = {"id": row[0], "name": row[1], "email": row[2],
                   "role": row[4], "created_at": str(row[5])}
        print(f"  [OK] Login: {row[1]} <{email}>")
        return self._json(200, {"ok": True, "student": student})

    # ── POST /api/questions ───────────────────────────────────────────────────
    def _save_question(self):
        body       = self._body()
        student_id = body.get("student_id")
        question   = (body.get("question",   "") or "").strip()
        approaches = json.dumps(body.get("approaches") or [])
        answer     = (body.get("answer",     "") or "").strip()

        if not student_id or not question:
            return self._json(400, {"error": "student_id and question are required"})

        try:
            student_id = int(student_id)
        except (ValueError, TypeError):
            return self._json(400, {"error": "student_id must be an integer"})

        try:
            with db.get_conn() as conn:
                row = conn.execute(
                    text("""
                        INSERT INTO questions (student_id, question, approaches, answer)
                        VALUES (:sid, :q, :ap, :ans)
                        RETURNING id, created_at
                    """),
                    {"sid": student_id, "q": question, "ap": approaches, "ans": answer},
                ).fetchone()
                conn.commit()
        except Exception as exc:
            print(f"  [ERROR] save_question: {exc}")
            return self._json(500, {"error": "Database error"})

        return self._json(201, {"ok": True, "id": row[0], "created_at": str(row[1])})

    # ── GET /api/history ──────────────────────────────────────────────────────
    def _history(self, params: dict):
        try:
            student_id = int(params.get("student_id", ["0"])[0])
        except (ValueError, TypeError):
            return self._json(400, {"error": "student_id required"})
        if not student_id:
            return self._json(400, {"error": "student_id required"})

        page, size = _page_params(params)
        offset = (page - 1) * size

        with db.get_conn() as conn:
            rows = conn.execute(
                text("""
                    SELECT id, question, approaches, answer, created_at
                    FROM questions
                    WHERE student_id = :sid
                    ORDER BY created_at DESC
                    LIMIT :lim OFFSET :off
                """),
                {"sid": student_id, "lim": size, "off": offset},
            ).fetchall()
            total = conn.execute(
                text("SELECT COUNT(*) FROM questions WHERE student_id = :sid"),
                {"sid": student_id},
            ).scalar()

        questions = [
            {
                "id":         r[0],
                "question":   r[1],
                "approaches": json.loads(r[2]) if r[2] else [],
                "answer":     r[3],
                "created_at": str(r[4]),
            }
            for r in rows
        ]
        return self._json(200, {
            "ok": True, "questions": questions,
            "page": page, "size": size, "total": total,
            "pages": max(1, (total + size - 1) // size),
        })

    # ── GET /api/admin/students ───────────────────────────────────────────────
    def _admin_students(self, params: dict):
        if not self._is_admin():
            return self._json(403, {"error": "Forbidden: admin access required"})

        page, size = _page_params(params)
        offset = (page - 1) * size

        with db.get_conn() as conn:
            rows = conn.execute(
                text("""
                    SELECT s.id, s.name, s.email, s.role, s.created_at,
                           COUNT(q.id) AS question_count
                    FROM students s
                    LEFT JOIN questions q ON q.student_id = s.id
                    GROUP BY s.id, s.name, s.email, s.role, s.created_at
                    ORDER BY s.created_at DESC
                    LIMIT :lim OFFSET :off
                """),
                {"lim": size, "off": offset},
            ).fetchall()
            total = conn.execute(text("SELECT COUNT(*) FROM students")).scalar()

        students = [
            {
                "id":             r[0],
                "name":           r[1],
                "email":          r[2],
                "role":           r[3],
                "created_at":     str(r[4]),
                "question_count": r[5],
            }
            for r in rows
        ]
        return self._json(200, {
            "ok": True, "students": students,
            "page": page, "size": size, "total": total,
            "pages": max(1, (total + size - 1) // size),
        })

    # ── GET /api/admin/stats ──────────────────────────────────────────────────
    def _admin_stats(self):
        if not self._is_admin():
            return self._json(403, {"error": "Forbidden: admin access required"})

        with db.get_conn() as conn:
            row = conn.execute(text("""
                SELECT
                    (SELECT COUNT(*)              FROM students)                        AS total_students,
                    (SELECT COUNT(*)              FROM students
                     WHERE date(created_at) = CURRENT_DATE)                            AS new_today,
                    (SELECT COUNT(*)              FROM questions)                       AS total_questions,
                    (SELECT COUNT(DISTINCT student_id) FROM questions
                     WHERE date(created_at) = CURRENT_DATE)                            AS active_today
            """)).fetchone()

        return self._json(200, {
            "ok": True,
            "total_students":  row[0],
            "new_today":       row[1],
            "total_questions": row[2],
            "active_today":    row[3],
        })

    # ── GET /api/ping ─────────────────────────────────────────────────────────
    def _ping(self):
        try:
            info = db.ping()
            return self._json(200, {"ok": True, **info})
        except Exception as exc:
            return self._json(503, {"ok": False, "error": str(exc)})

    # ── Route dispatcher ──────────────────────────────────────────────────────
    def do_POST(self):
        parsed = urlparse(self.path)
        path   = parsed.path
        routes = {
            "/api/register":  self._register,
            "/api/login":     self._login,
            "/api/questions": self._save_question,
        }
        handler = routes.get(path)
        if handler:
            handler()
        else:
            self._json(404, {"error": "Not found"})

    def do_GET(self):
        parsed = urlparse(self.path)
        path   = parsed.path
        params = parse_qs(parsed.query)

        if path == "/api/ping":
            self._ping()
        elif path == "/api/history":
            self._history(params)
        elif path == "/api/admin/students":
            self._admin_students(params)
        elif path == "/api/admin/stats":
            self._admin_stats()
        else:
            super().do_GET()


# ══════════════════════════════════════════════════════════════════════════════
# Entry point
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 56)
    print("  EchoTwins AI — Supabase Edition")
    print(f"  http://localhost:{PORT}")
    print("=" * 56)
    print("  Initialising database …")
    db.init_db()
    print("  Verifying database connection …")
    try:
        info = db.ping()
        print(f"  ✅  Connected → database: {info['database']}, time: {info['server_time']}")
    except Exception as exc:
        print(f"  ⚠️  Could not ping database: {exc}")
    print("=" * 56)
    print("  API endpoints:")
    print("    POST /api/register         Register student")
    print("    POST /api/login            Login")
    print("    POST /api/questions        Save solved question")
    print("    GET  /api/history          Paginated question history")
    print("    GET  /api/admin/students   Admin: all students")
    print("    GET  /api/admin/stats      Admin: aggregate stats")
    print("    GET  /api/ping             Health / DB check")
    print(f"  Admin secret:  {'SET ✅' if ADMIN_SECRET else 'NOT SET ❌  (add ADMIN_SECRET to .env)'}")
    print("=" * 56)
    httpd = HTTPServer(("", PORT), Handler)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n  Server stopped.")
