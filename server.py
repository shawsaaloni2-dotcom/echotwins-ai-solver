#!/usr/bin/env python3
"""
EchoTwins AI — Local Backend Server
Serves all HTML files + provides a REST API to store/read student data in students.json
Run: python server.py
Then open: http://localhost:3000
"""

import json
import os
import hashlib
import time
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

DB_FILE = os.path.join(os.path.dirname(__file__), "students.json")

# ── DB helpers ──────────────────────────────────────────────────────────────
def load_db():
    if not os.path.exists(DB_FILE):
        with open(DB_FILE, "w") as f:
            json.dump({"students": []}, f)
    with open(DB_FILE, "r") as f:
        return json.load(f)

def save_db(data):
    with open(DB_FILE, "w") as f:
        json.dump(data, f, indent=2)

def hash_password(pwd):
    return hashlib.sha256(pwd.encode()).hexdigest()

def find_student(db, email):
    for s in db["students"]:
        if s["email"].lower() == email.lower():
            return s
    return None

# ── Request Handler ──────────────────────────────────────────────────────────
class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=os.path.dirname(__file__), **kwargs)

    def log_message(self, fmt, *args):
        print(f"  {self.address_string()} -> {fmt % args}")

    # ── CORS headers ────────────────────────────────────────────────────────
    def send_cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_cors()
        self.end_headers()

    # ── JSON response helper ─────────────────────────────────────────────────
    def json_response(self, code, payload):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self.send_cors()
        self.end_headers()
        self.wfile.write(body)

    # ── Read request body ───────────────────────────────────────────────────
    def read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length)) if length else {}

    # ── Route: POST /api/register ────────────────────────────────────────────
    def api_register(self):
        body = self.read_body()
        name  = body.get("name", "").strip()
        email = body.get("email", "").strip().lower()
        pwd   = body.get("password", "")

        if not name or not email or not pwd:
            return self.json_response(400, {"error": "Name, email and password are required"})

        db = load_db()
        if find_student(db, email):
            return self.json_response(409, {"error": "Email already registered"})

        student = {
            "id":          len(db["students"]) + 1,
            "name":        name,
            "email":       email,
            "password":    hash_password(pwd),
            "joinDate":    time.strftime("%Y-%m-%d"),
            "joinTime":    time.strftime("%H:%M:%S"),
            "lastLogin":   time.strftime("%Y-%m-%d %H:%M:%S"),
            "questionsSolved": 0,
            "xp":          0,
            "streak":      0,
        }
        db["students"].append(student)
        save_db(db)

        safe = {k: v for k, v in student.items() if k != "password"}
        print(f"  [OK] New student registered: {name} <{email}>")
        return self.json_response(201, {"ok": True, "student": safe})

    # ── Route: POST /api/login ───────────────────────────────────────────────
    def api_login(self):
        body  = self.read_body()
        email = body.get("email", "").strip().lower()
        pwd   = body.get("password", "")

        db = load_db()
        student = find_student(db, email)
        if not student:
            return self.json_response(401, {"error": "Email not found"})
        if student["password"] != hash_password(pwd):
            return self.json_response(401, {"error": "Incorrect password"})

        # Update last login
        student["lastLogin"] = time.strftime("%Y-%m-%d %H:%M:%S")
        save_db(db)

        safe = {k: v for k, v in student.items() if k != "password"}
        print(f"  [OK] Student logged in: {student['name']} <{email}>")
        return self.json_response(200, {"ok": True, "student": safe})

    # ── Route: POST /api/update ──────────────────────────────────────────────
    def api_update(self):
        body  = self.read_body()
        email = body.get("email", "").strip().lower()
        db    = load_db()
        student = find_student(db, email)
        if not student:
            return self.json_response(404, {"error": "Student not found"})

        # Update allowed fields
        for field in ["questionsSolved", "xp", "streak", "lastLogin"]:
            if field in body:
                student[field] = body[field]
        save_db(db)
        safe = {k: v for k, v in student.items() if k != "password"}
        return self.json_response(200, {"ok": True, "student": safe})

    # ── Route: GET /api/students (admin) ────────────────────────────────────
    def api_students(self):
        # Simple admin check via query param ?admin=echotwins
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        token  = params.get("admin", [""])[0]
        if token != "echotwins":
            return self.json_response(403, {"error": "Admin token required: ?admin=echotwins"})
        db = load_db()
        safe = [{k: v for k, v in s.items() if k != "password"} for s in db["students"]]
        return self.json_response(200, {"ok": True, "students": safe, "total": len(safe)})

    # ── Route dispatch ───────────────────────────────────────────────────────
    def do_POST(self):
        path = urlparse(self.path).path
        if   path == "/api/register": self.api_register()
        elif path == "/api/login":    self.api_login()
        elif path == "/api/update":   self.api_update()
        else: self.json_response(404, {"error": "Not found"})

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/students":
            self.api_students()
        else:
            super().do_GET()

# ── Entry point ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    port = 3000
    print("=" * 50)
    print("  EchoTwins AI -- Local Server")
    print(f"  http://localhost:{port}")
    print("=" * 50)
    print("  API endpoints:")
    print("    POST /api/register  -- Register student")
    print("    POST /api/login     -- Login student")
    print("    POST /api/update    -- Update student data")
    print("    GET  /api/students?admin=echotwins")
    print("         -- View ALL students (admin)")
    print("  Student database: students.json")
    print("=" * 50)
    httpd = HTTPServer(("", port), Handler)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n  Server stopped.")
