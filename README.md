# EchoTwins AI — Supabase Edition

## Stack
| Layer | Technology |
|-------|-----------|
| Frontend | HTML + Vanilla JS (4 pages) |
| Backend  | Python `http.server` + SQLAlchemy |
| Database | Supabase PostgreSQL (transaction pooler) |
| Auth     | Email/password with werkzeug PBKDF2 hashing |

---

## Setup

### 1. Set your Supabase connection string

Copy the example env file and fill in your values:

```bash
copy .env.example .env
```

Open `.env` and set:
```
DATABASE_URL=postgresql://postgres.YOURREF:PASSWORD@aws-0-REGION.pooler.supabase.com:6543/postgres
ADMIN_SECRET=your_strong_secret_here
```

> **Tip:** Use the **Transaction Pooler** (port **6543**), not the direct connection (5432).

### 2. Install Python packages

```bash
python -m pip install -r requirements.txt
```

Packages installed: `sqlalchemy`, `psycopg2-binary`, `python-dotenv`, `werkzeug`

### 3. Run the migration (one-time)

Imports existing `students.json` records into Supabase:

```bash
python migrate_students.py
```

> ⚠️ Legacy SHA-256 passwords are replaced with a locked placeholder. Affected users must reset their passwords.  
> `students.json` is **not deleted** — it stays as a backup.

### 4. Start the server

```bash
python server.py
```

The server will:
- Connect to Supabase and print the DB name + server time
- Create tables if they don't exist (idempotent)
- Serve the app at **http://localhost:3000**

---

## API Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/api/register` | — | Register student |
| POST | `/api/login` | — | Login, returns student profile |
| POST | `/api/questions` | student_id in body | Save a solved question |
| GET | `/api/history?student_id=&page=&size=` | — | Paginated history (default 20/page) |
| GET | `/api/admin/students?page=&size=` | `X-Admin-Secret` header | All students with question counts |
| GET | `/api/admin/stats` | `X-Admin-Secret` header | Aggregate stats |
| GET | `/api/ping` | — | DB health check |

---

## Testing

### Test DB connection
```
GET http://localhost:3000/api/ping
```

### Test login
```bash
curl -X POST http://localhost:3000/api/login \
  -H "Content-Type: application/json" \
  -d "{\"email\":\"test@echotwins.ai\",\"password\":\"test123\"}"
```

### Test question save
```bash
curl -X POST http://localhost:3000/api/questions \
  -H "Content-Type: application/json" \
  -d "{\"student_id\":1,\"question\":\"What is photosynthesis?\",\"approaches\":[\"Biology\"],\"answer\":\"Process of converting light to energy\"}"
```

### Test history (paginated)
```
GET http://localhost:3000/api/history?student_id=1&page=1&size=20
```

### Test admin
```
GET http://localhost:3000/api/admin/students
Header: X-Admin-Secret: your_secret_here
```

---

## Database Schema

```sql
students (
  id           SERIAL PRIMARY KEY,
  name         TEXT NOT NULL,
  email        TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  role         TEXT DEFAULT 'student',
  created_at   TIMESTAMPTZ DEFAULT NOW()
)

questions (
  id          SERIAL PRIMARY KEY,
  student_id  INTEGER REFERENCES students(id) ON DELETE CASCADE,
  question    TEXT NOT NULL,
  approaches  TEXT,           -- JSON array stored as text
  answer      TEXT,
  created_at  TIMESTAMPTZ DEFAULT NOW()
)

-- Index for fast paginated history queries:
CREATE INDEX idx_questions_student_created ON questions (student_id, created_at DESC);
```

---

## Security Notes

- All database access is **server-side only** — no secrets are ever sent to the browser
- Passwords are hashed with **werkzeug PBKDF2** (never stored as plain text)
- All queries use **parameterized `?` / `:param` placeholders** — no string concatenation
- Admin endpoints require `X-Admin-Secret` header and return **403** for non-admins
- Row Level Security (RLS) remains **enabled** on both Supabase tables
- `.env`, `config.js`, `students.json`, and `*.db` are in `.gitignore`

---

## File Reference

| File | Purpose |
|------|---------|
| `server.py` | Main HTTP server + REST API |
| `db.py` | SQLAlchemy engine + `init_db()` / `ping()` |
| `migrate_students.py` | One-time import from `students.json` |
| `requirements.txt` | Python dependencies |
| `.env` | Secrets (never commit) |
| `.env.example` | Template for `.env` |
| `config.js` | Client-side config (no secrets) |
| `config.example.js` | Template for `config.js` |
| `.gitignore` | Excludes secrets and local data |

