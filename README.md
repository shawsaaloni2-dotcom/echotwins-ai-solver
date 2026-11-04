# EchoTwins AI — Cognitive Learning Platform

EchoTwins AI is an interactive educational question-solving platform with session-based authentication, multi-provider AI solving (Groq, Gemini, OpenRouter), and a scalable Supabase PostgreSQL backend.

---

## Architecture & Technology Stack

| Layer | Technology |
|---|---|
| **Frontend** | Responsive Vanilla HTML5, CSS3, JavaScript (Light & Dark themes, Web Speech API) |
| **Backend** | Python `http.server.ThreadingHTTPServer` + SQLAlchemy (pg8000 / PostgreSQL pooler) |
| **AI Providers** | Groq (`openai/gpt-oss-120b`), Google Gemini (`gemini-2.0-flash`), OpenRouter via unified `openai` client |
| **Sessions** | HMAC-SHA256 signed session tokens (HttpOnly cookies, SameSite=Lax) |
| **Database** | Supabase PostgreSQL (transaction pooler port 6543) with SQLite fallback |

---

## Getting Started

### 1. Environment Configuration (`.env`)

Copy the example file:
```bash
copy .env.example .env
```

Open `.env` and configure your settings:
```ini
# Supabase PostgreSQL Transaction Pooler (port 6543)
DATABASE_URL=postgresql://postgres.YOURREF:PASSWORD@aws-0-REGION.pooler.supabase.com:6543/postgres

# HMAC Session Signing Key
SECRET_KEY=generate_a_random_secret_key_here

# AI Provider Selection: groq, gemini, or openrouter
PROVIDER=groq

# Model Name
MODEL=openai/gpt-oss-120b

# Provider API Keys (Server-side only — never exposed to clients)
GROQ_API_KEY=gsk_your_groq_key_here
GEMINI_API_KEY=
OPENROUTER_API_KEY=

# Server Port
PORT=3000
```

### 2. Switching Providers and Models

You can switch the AI provider and model at any time by updating `.env`:

* **Groq (Default, Free Tier):**
  ```ini
  PROVIDER=groq
  MODEL=openai/gpt-oss-120b
  GROQ_API_KEY=your_groq_api_key
  ```
  *(Alternative Groq models: `openai/gpt-oss-20b`, `qwen/qwen3.8-27b`)*

* **Google Gemini:**
  ```ini
  PROVIDER=gemini
  MODEL=gemini-2.0-flash
  GEMINI_API_KEY=your_gemini_api_key
  ```

* **OpenRouter:**
  ```ini
  PROVIDER=openrouter
  MODEL=meta-llama/llama-3.3-70b-instruct
  OPENROUTER_API_KEY=your_openrouter_api_key
  ```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

Packages included: `sqlalchemy`, `psycopg2-binary`, `pg8000`, `python-dotenv`, `werkzeug`, `openai`.

### 4. Run the Migration (One-time)

If you have legacy students in `students.json`, migrate them into the database:
```bash
python migrate_students.py
```
*(Preserves `students.json` as a backup.)*

### 5. Start the Server

```bash
python server.py
```

The server will start at **http://localhost:3000**.

---

## API Endpoints

| Method | Path | Authentication | Description |
|---|---|---|---|
| `POST` | `/api/register` | Public | Register new student, sets `session_token` cookie |
| `POST` | `/api/login` | Public | Authenticate email/password, sets `session_token` cookie |
| `POST` | `/api/logout` | Session | Clears session cookie |
| `GET` | `/api/auth/me` | Session | Returns current authenticated student profile |
| `POST` | `/api/solve` | **Session Required** | Solves question via AI, saves to DB, returns approaches & answer |
| `GET` | `/api/history` | **Session Required** | Paginated questions for logged-in student (`?page=1&size=20`) |
| `GET` | `/api/admin/students` | **Admin Session** | Paginated student list with question counts |
| `GET` | `/api/admin/stats` | **Admin Session** | Aggregate metrics (students, new today, questions) |
| `GET` | `/api/ai/status` | Public | Check active AI provider & configuration status |
| `GET` | `/api/ping` | Public | Database health check |

---

## Security & Privacy Rules

1. **Zero Client Secrets:** No API keys or database URLs are present in HTML, JavaScript, `config.js`, or client responses.
2. **Session Verification:** `student_id` is never trusted from client request bodies or query parameters. The backend extracts `student_id` directly from the verified HMAC-signed session cookie.
3. **Static File Whitelist:** Direct access to `.env`, `*.db`, `*.py`, `students.json`, `config.js`, `test_supabase.py`, and dotfiles returns `404 Not Found`.
4. **Data Minimization:** Only the sanitized question string is sent to the AI provider. No personal student data (name, email, ID) is ever transmitted.
5. **XSS Protection:** AI outputs are escaped with strict HTML encoding prior to rendering.

---

## Deployment Guide (Render / Railway)

GitHub Pages only hosts static files and cannot execute Python backends (`server.py`). To deploy EchoTwins AI for public use:

### Deploying to Render:
1. Create a **Web Service** on [Render.com](https://render.com).
2. Connect your GitHub repository.
3. Set the Environment to **Python 3**.
4. Set the Build Command:
   ```bash
   pip install -r requirements.txt
   ```
5. Set the Start Command:
   ```bash
   python server.py
   ```
6. Add your Environment Variables in the Render dashboard:
   * `DATABASE_URL` = your Supabase pooler URL
   * `SECRET_KEY` = a long random string
   * `PROVIDER` = `groq`
   * `MODEL` = `openai/gpt-oss-120b`
   * `GROQ_API_KEY` = your Groq API key

### Deploying to Railway:
1. Create a **New Project** on [Railway.app](https://railway.app).
2. Select **Deploy from GitHub repo**.
3. In Service Settings, configure the Environment Variables (`DATABASE_URL`, `SECRET_KEY`, `PROVIDER`, `MODEL`, `GROQ_API_KEY`).
4. Railway will automatically detect `requirements.txt` and start `python server.py`.
