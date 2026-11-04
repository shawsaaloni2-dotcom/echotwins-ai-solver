#!/usr/bin/env python3
"""
EchoTwins AI — Backend Server (Supabase / PostgreSQL edition)
==============================================================
Serves static HTML/JS/CSS from the project directory AND provides a
secure JSON REST API with session tokens, multi-provider AI solver (Groq/Gemini/OpenRouter),
and database persistence.

Run:
    python server.py
"""

import base64
import hashlib
import hmac
from http.cookies import SimpleCookie
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
import os
import sys
import threading
import time
from urllib.parse import parse_qs, urlparse

try:
    if sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from dotenv import load_dotenv
from openai import APIConnectionError, APIError, OpenAI, RateLimitError
from sqlalchemy import text
from werkzeug.security import check_password_hash, generate_password_hash

load_dotenv()

import db  # noqa: E402

SECRET_KEY = os.environ.get("SECRET_KEY", "echotwins_default_secret_key_change_me_12345")
ADMIN_SECRET = os.environ.get("ADMIN_SECRET", "")
PORT = int(os.environ.get("PORT", 3000))
PAGE_DEFAULT = 20
PAGE_MAX = 100
QUESTION_MAX_LEN = 2000
RATE_LIMIT_PER_MINUTE = 10

# In-memory rate limiting: user_key -> list of timestamp floats
_rate_limits = {}
_rate_limits_lock = threading.Lock()


def _check_rate_limit(user_key: str) -> bool:
    """Returns True if request is allowed, False if rate limited (10 req/min)."""
    now = time.time()
    with _rate_limits_lock:
        records = _rate_limits.get(user_key, [])
        records = [t for t in records if now - t < 60]
        if len(records) >= RATE_LIMIT_PER_MINUTE:
            _rate_limits[user_key] = records
            return False
        records.append(now)
        _rate_limits[user_key] = records
        return True


# ══════════════════════════════════════════════════════════════════════════════
# Session Token Handling (HMAC-SHA256)
# ══════════════════════════════════════════════════════════════════════════════

def _sign_session(payload: dict) -> str:
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    b64_payload = base64.urlsafe_b64encode(raw).decode("utf-8").rstrip("=")
    sig = hmac.new(SECRET_KEY.encode("utf-8"), b64_payload.encode("utf-8"), hashlib.sha256).digest()
    b64_sig = base64.urlsafe_b64encode(sig).decode("utf-8").rstrip("=")
    return f"{b64_payload}.{b64_sig}"


def _verify_session(token: str) -> dict | None:
    if not token or "." not in token:
        return None
    try:
        parts = token.split(".")
        if len(parts) != 2:
            return None
        b64_payload, b64_sig = parts
        expected_sig = hmac.new(SECRET_KEY.encode("utf-8"), b64_payload.encode("utf-8"), hashlib.sha256).digest()

        pad_sig = len(b64_sig) % 4
        if pad_sig:
            b64_sig += "=" * (4 - pad_sig)
        actual_sig = base64.urlsafe_b64decode(b64_sig)

        if not hmac.compare_digest(expected_sig, actual_sig):
            return None

        pad_p = len(b64_payload) % 4
        if pad_p:
            b64_payload += "=" * (4 - pad_p)
        payload = json.loads(base64.urlsafe_b64decode(b64_payload).decode("utf-8"))

        if payload.get("exp", 0) < time.time():
            return None
        return payload
    except Exception:
        return None


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


def _get_ai_client_and_model():
    """Build OpenAI client for selected PROVIDER (groq, gemini, openrouter)."""
    provider = os.environ.get("PROVIDER", "groq").strip().lower() or "groq"
    configured_model = os.environ.get("MODEL", "").strip()

    if provider == "groq":
        api_key = os.environ.get("GROQ_API_KEY", "").strip()
        base_url = "https://api.groq.com/openai/v1"
        model = configured_model or "openai/gpt-oss-120b"
    elif provider == "gemini":
        api_key = os.environ.get("GEMINI_API_KEY", "").strip()
        base_url = "https://generativelanguage.googleapis.com/v1beta/openai/"
        model = configured_model or "gemini-2.0-flash"
    elif provider == "openrouter":
        api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
        base_url = "https://openrouter.ai/api/v1"
        model = configured_model or "meta-llama/llama-3.3-70b-instruct"
    else:
        api_key = ""
        base_url = ""
        model = configured_model

    if not api_key:
        return None, None, provider

    client = OpenAI(base_url=base_url, api_key=api_key, timeout=35.0)
    return client, model, provider


# ══════════════════════════════════════════════════════════════════════════════
# Request Handler
# ══════════════════════════════════════════════════════════════════════════════

ALLOWED_STATIC_FILES = {
    "index.html",
    "login.html",
    "app.html",
    "dashboard.html",
    "admin.html",
    "echotwins_solver.html",
}

BLOCKED_PATTERNS = [
    ".env",
    "config.js",
    "students.json",
    "test_supabase.py",
    "requirements.txt",
    "migrate_students.py",
    "server.py",
    "db.py",
    ".git",
]


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=os.path.dirname(__file__), **kwargs)

    def log_message(self, fmt, *args):
        path = self.path.split("?")[0]
        if path.startswith("/api"):
            print(f"  {self.address_string()} -> {fmt % args}")

    # ── CORS ──────────────────────────────────────────────────────────────────
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Admin-Secret")
        self.send_header("Access-Control-Allow-Credentials", "true")

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors()
        self.end_headers()

    # ── JSON helpers ──────────────────────────────────────────────────────────
    def _json(self, code: int, payload: dict, extra_headers: list[tuple[str, str]] | None = None):
        body = json.dumps(payload, default=str).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        if extra_headers:
            for k, v in extra_headers:
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            return {}

    # ── Auth & Session verification ───────────────────────────────────────────
    def _get_auth_session(self) -> dict | None:
        """Extract and verify session token from Cookie or Authorization header."""
        # 1. Check Cookie
        cookie_header = self.headers.get("Cookie", "")
        if cookie_header:
            try:
                cookie = SimpleCookie(cookie_header)
                if "session_token" in cookie:
                    sess = _verify_session(cookie["session_token"].value)
                    if sess:
                        return sess
            except Exception:
                pass

        # 2. Check Authorization header
        auth_header = self.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:].strip()
            sess = _verify_session(token)
            if sess:
                return sess

        return None

    def _is_admin(self, session: dict | None) -> bool:
        """Verify admin rights either via session role='admin' or X-Admin-Secret."""
        if session and session.get("role") == "admin":
            return True
        secret = self.headers.get("X-Admin-Secret", "").strip()
        if ADMIN_SECRET and secret == ADMIN_SECRET:
            return True
        return False

    # ── Static File Handler (Safety whitelist) ────────────────────────────────
    def do_GET_static(self):
        parsed = urlparse(self.path)
        raw_path = parsed.path.lstrip("/")

        # Default root
        if not raw_path:
            raw_path = "index.html"

        # Normalize path
        normalized = os.path.normpath(raw_path).replace("\\", "/")

        # Check for traversal, dotfiles, or explicit blocked files
        lower_path = normalized.lower()
        if (
            ".." in normalized
            or lower_path.startswith(".")
            or "/." in lower_path
            or any(b in lower_path for b in BLOCKED_PATTERNS)
            or lower_path.endswith(".py")
            or lower_path.endswith(".db")
            or lower_path.endswith(".env")
            or lower_path.endswith(".json")
        ):
            self.send_response(404)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"404 Not Found")
            return

        # Check allowed files / extensions
        ext = os.path.splitext(normalized)[1].lower()
        allowed_extensions = {
            ".html", ".css", ".js", ".png", ".jpg", ".jpeg",
            ".gif", ".svg", ".ico", ".webp", ".mp3", ".wav",
            ".mp4", ".webm", ".woff", ".woff2", ".ttf"
        }

        if normalized not in ALLOWED_STATIC_FILES and ext not in allowed_extensions:
            self.send_response(404)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"404 Not Found")
            return

        disk_path = os.path.join(os.path.dirname(__file__), normalized)
        if not os.path.isfile(disk_path):
            self.send_response(404)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"404 Not Found")
            return

        mime_type, _ = mimetypes.guess_type(disk_path)
        if not mime_type:
            mime_type = "application/octet-stream"

        try:
            with open(disk_path, "rb") as f:
                content = f.read()
            self.send_response(200)
            self.send_header("Content-Type", mime_type)
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        except Exception:
            self.send_response(500)
            self.end_headers()

    # ── POST /api/register ────────────────────────────────────────────────────
    def _register(self):
        body = self._body()
        name = (body.get("name", "") or "").strip()
        email = (body.get("email", "") or "").strip().lower()
        pwd = (body.get("password", "") or "")
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

        student_id, s_name, s_email, s_role, s_created = row[0], row[1], row[2], row[3], row[4]
        exp = int(time.time()) + (7 * 86400)
        token = _sign_session({"sub": student_id, "email": s_email, "role": s_role, "exp": exp})

        student = {
            "id": student_id,
            "name": s_name,
            "email": s_email,
            "role": s_role,
            "created_at": str(s_created)
        }
        cookie_val = f"session_token={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age=604800"
        return self._json(201, {"ok": True, "student": student, "token": token}, [("Set-Cookie", cookie_val)])

    # ── POST /api/login ───────────────────────────────────────────────────────
    def _login(self):
        body = self._body()
        email = (body.get("email", "") or "").strip().lower()
        pwd = (body.get("password", "") or "")
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

        student_id, s_name, s_email, s_role, s_created = row[0], row[1], row[2], row[4], row[5]
        exp = int(time.time()) + (7 * 86400)
        token = _sign_session({"sub": student_id, "email": s_email, "role": s_role, "exp": exp})

        student = {
            "id": student_id,
            "name": s_name,
            "email": s_email,
            "role": s_role,
            "created_at": str(s_created)
        }
        cookie_val = f"session_token={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age=604800"
        return self._json(200, {"ok": True, "student": student, "token": token}, [("Set-Cookie", cookie_val)])

    # ── POST /api/logout ──────────────────────────────────────────────────────
    def _logout(self):
        cookie_val = "session_token=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0"
        return self._json(200, {"ok": True}, [("Set-Cookie", cookie_val)])

    # ── GET /api/auth/me ──────────────────────────────────────────────────────
    def _auth_me(self):
        session = self._get_auth_session()
        if not session:
            return self._json(200, {"authenticated": False})
        return self._json(200, {
            "authenticated": True,
            "student": {
                "id": session.get("sub"),
                "email": session.get("email"),
                "role": session.get("role", "student")
            }
        })

    # ── POST /api/solve ───────────────────────────────────────────────────────
    def _solve(self):
        session = self._get_auth_session()
        if not session:
            return self._json(401, {"error": "Authentication required. Please log in."})

        student_id = session.get("sub")
        if not student_id:
            return self._json(401, {"error": "Invalid session"})

        # Rate limit check (10 req/min per student)
        if not _check_rate_limit(f"user_{student_id}"):
            return self._json(429, {"error": "Too many requests, try again in a minute"})

        body = self._body()
        question = (body.get("question", "") or "").strip()
        if not question:
            return self._json(400, {"error": "Question is required"})
        if len(question) > QUESTION_MAX_LEN:
            return self._json(400, {"error": f"Question exceeds maximum length of {QUESTION_MAX_LEN} characters"})

        client, model, provider = _get_ai_client_and_model()
        if not client:
            return self._json(503, {"error": f"AI key not configured for provider '{provider}'"})

        system_prompt = (
            "You are EchoTwins AI, an expert educational question solver.\n"
            "Analyze the given question and output a valid raw JSON object with EXACTLY these keys:\n"
            "- approaches: an array of 3 distinct solving approaches (e.g. ['Approach 1 description', 'Approach 2 description', 'Approach 3 description'])\n"
            "- answer: the exact final answer in one clear, precise sentence or formula\n\n"
            "Return ONLY the valid raw JSON object. Do not include markdown fences (```), commentary, or extra prose."
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": question}
        ]

        # Call AI provider with retry on 429
        response_text = ""
        for attempt in range(2):
            try:
                resp = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=0.2,
                    max_tokens=1200,
                    response_format={"type": "json_object"}
                )
                response_text = resp.choices[0].message.content or ""
                break
            except RateLimitError:
                if attempt == 0:
                    time.sleep(1.5)
                    continue
                return self._json(429, {"error": "Too many requests, try again in a minute"})
            except APIConnectionError:
                return self._json(504, {"error": "AI provider connection timed out. Please try again."})
            except APIError as api_err:
                return self._json(502, {"error": f"AI provider error: {str(api_err)}"})
            except Exception as err:
                return self._json(500, {"error": f"Unexpected error: {str(err)}"})

        # Safe parsing with 1 retry if JSON is invalid
        parsed = None
        for attempt in range(2):
            cleaned = response_text.strip()
            if cleaned.startswith("```json"):
                cleaned = cleaned[7:]
            elif cleaned.startswith("```"):
                cleaned = cleaned[3:]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
            cleaned = cleaned.strip()

            try:
                parsed = json.loads(cleaned)
                if isinstance(parsed, dict) and "approaches" in parsed and "answer" in parsed:
                    break
            except Exception:
                pass

            if attempt == 0:
                # Retry prompt once
                try:
                    retry_resp = client.chat.completions.create(
                        model=model,
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": f"Your previous response was not valid JSON. Provide ONLY the valid JSON object for this question:\n{question}"}
                        ],
                        temperature=0.1,
                        max_tokens=1000,
                        response_format={"type": "json_object"}
                    )
                    response_text = retry_resp.choices[0].message.content or ""
                except Exception:
                    break

        if not parsed or not isinstance(parsed, dict) or "answer" not in parsed:
            return self._json(502, {"error": "Failed to generate structured answer. Please retry."})

        approaches = parsed.get("approaches", [])
        if not isinstance(approaches, list):
            approaches = [str(approaches)]
        approaches = [str(a) for a in approaches]

        answer = str(parsed.get("answer", "")).strip()

        # Save to database for logged-in student
        try:
            with db.get_conn() as conn:
                row = conn.execute(
                    text("""
                        INSERT INTO questions (student_id, question, approaches, answer)
                        VALUES (:sid, :q, :ap, :ans)
                        RETURNING id, created_at
                    """),
                    {
                        "sid": student_id,
                        "q": question,
                        "ap": json.dumps(approaches),
                        "ans": answer
                    }
                ).fetchone()
                conn.commit()
            q_id = row[0]
            created_at = str(row[1])
        except Exception as exc:
            print(f"  [ERROR] save question on solve: {exc}")
            q_id = None
            created_at = str(time.time())

        return self._json(200, {
            "ok": True,
            "id": q_id,
            "question": question,
            "approaches": approaches,
            "answer": answer,
            "provider": provider,
            "model": model,
            "created_at": created_at
        })

    # ── GET /api/history ──────────────────────────────────────────────────────
    def _history(self, params: dict):
        session = self._get_auth_session()
        if not session:
            return self._json(401, {"error": "Authentication required. Please log in."})

        # Never trust student_id sent by browser; take it from the verified session
        student_id = session.get("sub")
        if not student_id:
            return self._json(401, {"error": "Invalid session"})

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
                "id": r[0],
                "question": r[1],
                "approaches": json.loads(r[2]) if r[2] else [],
                "answer": r[3],
                "created_at": str(r[4]),
            }
            for r in rows
        ]
        return self._json(200, {
            "ok": True,
            "questions": questions,
            "page": page,
            "size": size,
            "total": total,
            "pages": max(1, (total + size - 1) // size),
        })

    # ── GET /api/admin/students ───────────────────────────────────────────────
    def _admin_students(self, params: dict):
        session = self._get_auth_session()
        if not self._is_admin(session):
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
                "id": r[0],
                "name": r[1],
                "email": r[2],
                "role": r[3],
                "created_at": str(r[4]),
                "question_count": r[5],
            }
            for r in rows
        ]
        return self._json(200, {
            "ok": True,
            "students": students,
            "page": page,
            "size": size,
            "total": total,
            "pages": max(1, (total + size - 1) // size),
        })

    # ── GET /api/admin/stats ──────────────────────────────────────────────────
    def _admin_stats(self):
        session = self._get_auth_session()
        if not self._is_admin(session):
            return self._json(403, {"error": "Forbidden: admin access required"})

        with db.get_conn() as conn:
            row = conn.execute(text("""
                SELECT
                    (SELECT COUNT(*) FROM students) AS total_students,
                    (SELECT COUNT(*) FROM students WHERE date(created_at) = CURRENT_DATE) AS new_today,
                    (SELECT COUNT(*) FROM questions) AS total_questions,
                    (SELECT COUNT(DISTINCT student_id) FROM questions WHERE date(created_at) = CURRENT_DATE) AS active_today
            """)).fetchone()

        return self._json(200, {
            "ok": True,
            "total_students": row[0],
            "new_today": row[1],
            "total_questions": row[2],
            "active_today": row[3],
        })

    # ── GET /api/ping ─────────────────────────────────────────────────────────
    def _ping(self):
        try:
            info = db.ping()
            return self._json(200, {"ok": True, **info})
        except Exception as exc:
            return self._json(503, {"ok": False, "error": str(exc)})

    # ── GET /api/ai/status ────────────────────────────────────────────────────
    def _ai_status(self):
        provider = os.environ.get("PROVIDER", "groq").strip().lower() or "groq"
        model = os.environ.get("MODEL", "").strip() or "openai/gpt-oss-120b"
        groq_set = bool(os.environ.get("GROQ_API_KEY", "").strip())
        gemini_set = bool(os.environ.get("GEMINI_API_KEY", "").strip())
        openrouter_set = bool(os.environ.get("OPENROUTER_API_KEY", "").strip())

        ready = (
            (provider == "groq" and groq_set)
            or (provider == "gemini" and gemini_set)
            or (provider == "openrouter" and openrouter_set)
        )

        return self._json(200, {
            "ok": True,
            "provider": provider,
            "model": model,
            "server_ai_ready": ready,
            "configured_providers": {
                "groq": groq_set,
                "gemini": gemini_set,
                "openrouter": openrouter_set
            }
        })

    # ── Dispatchers ───────────────────────────────────────────────────────────
    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        routes = {
            "/api/register": self._register,
            "/api/login": self._login,
            "/api/logout": self._logout,
            "/api/solve": self._solve,
        }
        handler = routes.get(path)
        if handler:
            handler()
        else:
            self._json(404, {"error": "Not found"})

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)

        if path == "/api/ping":
            self._ping()
        elif path == "/api/ai/status":
            self._ai_status()
        elif path == "/api/auth/me":
            self._auth_me()
        elif path == "/api/history":
            self._history(params)
        elif path == "/api/admin/students":
            self._admin_students(params)
        elif path == "/api/admin/stats":
            self._admin_stats()
        elif path.startswith("/api"):
            self._json(404, {"error": "Not found"})
        else:
            self.do_GET_static()


# ══════════════════════════════════════════════════════════════════════════════
# Entry Point
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print("  EchoTwins AI — Supabase Edition (ThreadingHTTPServer)")
    print(f"  http://localhost:{PORT}")
    print("=" * 60)
    print("  Initialising database …")
    db.init_db()
    print("  Verifying database connection …")
    try:
        info = db.ping()
        print(f"  [OK] Connected -> database: {info['database']}, time: {info['server_time']}")
    except Exception as exc:
        print(f"  [WARN] Could not ping database: {exc}")
    print("=" * 60)
    provider = os.environ.get("PROVIDER", "groq").strip().lower() or "groq"
    model = os.environ.get("MODEL", "").strip() or "openai/gpt-oss-120b"
    print(f"  AI Provider:    {provider.upper()} ({model})")
    print(f"  Secret Key:     {'CONFIGURED' if SECRET_KEY else 'DEFAULT [WARN]'}")
    print(f"  Admin Secret:   {'CONFIGURED' if ADMIN_SECRET else 'NOT SET [WARN]'}")
    print("=" * 60)
    httpd = ThreadingHTTPServer(("", PORT), Handler)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n  Server stopped.")
