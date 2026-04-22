# NovaAI Newsletter

An agent-powered AI newsletter service. A Python/FastAPI backend runs a 5-stage
agent pipeline that crawls, filters, summarizes, edits, and delivers daily AI news
to subscribers. A single-file HTML frontend displays the live feed and admin dashboard.

```
novaai-newsletter/
├── index.html                  ← Frontend (deploy to GitHub Pages / Vercel / Netlify)
├── README.md
└── backend/
    ├── main.py                 ← FastAPI app entry point
    ├── config.py               ← Settings loader (.env)
    ├── requirements.txt        ← Python dependencies
    ├── .env.example            ← Copy to .env and fill in keys
    ├── agents/
    │   ├── crawler.py          ← Fetches RSS feeds and news sources
    │   ├── filter.py           ← Scores and selects best articles
    │   ├── summarizer.py       ← Claude API — generates summaries + bodies
    │   ├── editor.py           ← Composes newsletter editions
    │   ├── sender.py           ← SendGrid email delivery
    │   └── pipeline.py         ← Orchestrates all agents in sequence
    ├── models/
    │   └── database.py         ← SQLAlchemy models (Article, Subscriber, Edition)
    └── api/
        └── routes/
            ├── articles.py     ← GET /api/articles/*
            ├── subscribers.py  ← POST /api/subscribers/subscribe
            ├── admin.py        ← POST /api/admin/login + JWT auth
            └── newsletter.py   ← GET /api/newsletter/editions/*
```

---

## Quickstart

### 1. Clone and set up Python backend

```bash
git clone https://github.com/your-username/novaai-newsletter.git
cd novaai-newsletter/backend

python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env` and fill in:

| Key | Where to get it |
|-----|----------------|
| `ANTHROPIC_API_KEY` | https://console.anthropic.com |
| `SENDGRID_API_KEY` | https://app.sendgrid.com/settings/api_keys |
| `SENDGRID_FROM_EMAIL` | A verified sender in SendGrid |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | Choose your own |
| `SECRET_KEY` / `JWT_SECRET` | Any long random string |

### 3. Start the backend

```bash
uvicorn main:app --reload --port 8000
```

The API will be available at `http://localhost:8000`.  
Interactive docs at `http://localhost:8000/docs`.

### 4. Open the frontend

Open `index.html` in a browser, or serve it locally:

```bash
# From the project root
python -m http.server 5500
# Then open http://localhost:5500
```

---

## Changing the API endpoint

In `index.html`, find this line near the top of the `<script>` block:

```js
const API_BASE = 'http://localhost:8000';
```

Change it to your deployed backend URL, e.g.:

```js
const API_BASE = 'https://your-api.railway.app';
```

---

## Pipeline agents

The pipeline runs automatically every 6 hours. You can also trigger it manually:

```bash
# Via API (requires admin token)
curl -X POST http://localhost:8000/api/pipeline/trigger

# Or directly in Python
cd backend
python -c "import asyncio; from agents.pipeline import run_pipeline; asyncio.run(run_pipeline())"
```

### Agent sequence

```
Crawler → Filter → Summarizer → Editor → Sender
```

| Agent | What it does |
|-------|-------------|
| **Crawler** | Fetches RSS feeds from 16+ AI news sources |
| **Filter** | Scores articles by relevance, recency, and tag — selects top 12 |
| **Summarizer** | Calls Claude API to generate 2-sentence summaries + full article bodies |
| **Editor** | Creates the Edition record, picks featured article, writes intro via Claude |
| **Sender** | Renders HTML email template and sends via SendGrid |

---

## Deployment

### Backend — Railway (recommended)

```bash
# Install Railway CLI
npm install -g @railway/cli
railway login
railway init
railway up
```

Set environment variables in the Railway dashboard under your project's Variables tab.

### Backend — Render

1. Connect your GitHub repo at https://render.com
2. Create a new **Web Service**, root directory: `backend`
3. Build command: `pip install -r requirements.txt`
4. Start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
5. Add environment variables from `.env.example`

### Frontend — GitHub Pages

1. Push `index.html` to your repo
2. Go to **Settings → Pages → Source: Deploy from branch → main / root**
3. Update `API_BASE` in `index.html` to your deployed backend URL before pushing

### Frontend — Vercel / Netlify

Drag and drop `index.html` into the Vercel or Netlify dashboard, or connect via GitHub.

---

## Switching to PostgreSQL (production)

In `.env`, change:

```
DATABASE_URL=postgresql+asyncpg://user:password@your-db-host:5432/novaai
```

Then run migrations:

```bash
alembic init alembic
# Edit alembic/env.py to import your models
alembic revision --autogenerate -m "initial"
alembic upgrade head
```

---

## Adding more RSS sources

In `backend/agents/crawler.py`, add to the `SOURCES` list:

```python
{"name": "My Source", "url": "https://example.com/feed.xml", "tag_hint": ArticleTag.research},
```

---

## Admin credentials

Default: `admin` / `novaai2026` — **change these in `.env` before deploying**.

The admin login issues a JWT token stored in `localStorage`. Admin tabs
(Agents, Subscribers) are hidden from public visitors until login.
