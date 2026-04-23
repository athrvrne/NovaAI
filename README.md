# NovaAI

An agent-powered AI intelligence platform with RAG-based Q&A. A Python/FastAPI backend runs a 6-stage pipeline that crawls 32+ sources every 30 minutes, filters, summarizes with Claude, indexes into a vector store, assembles editions, and delivers daily AI news to subscribers. A single-file HTML frontend displays the live feed, admin dashboard, and an Ask AI interface for grounded Q&A over the article corpus.

```
novaai/
├── index.html                  ← Frontend (deploy to GitHub Pages / Vercel / Netlify)
├── README.md
└── backend/
    ├── main.py                 ← FastAPI app entry point
    ├── config.py               ← Settings loader (.env)
    ├── requirements.txt        ← Python dependencies
    ├── .env.example            ← Copy to .env and fill in keys
    ├── agents/
    │   ├── crawler.py          ← Fetches 32+ RSS feeds and news sources every 30 min
    │   ├── filter.py           ← Scores and selects best articles
    │   ├── summarizer.py       ← Claude API — generates summaries + bodies
    │   ├── rag.py              ← RAG agent — ChromaDB indexing + Claude Q&A
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
            ├── newsletter.py   ← GET /api/newsletter/editions/*
            └── search.py       ← POST /api/search/ask (RAG Q&A)
```

---

## Tech stack

| Layer | Technology |
|-------|-----------|
| **API framework** | FastAPI (Python) |
| **Database ORM** | SQLAlchemy 2.0 (async) |
| **Database** | SQLite (dev) · PostgreSQL via asyncpg (prod) |
| **AI** | Anthropic Claude API — summaries, article bodies, edition intros, RAG answers |
| **Vector store** | ChromaDB (persistent, local) — HNSW index with cosine similarity |
| **Embeddings** | ChromaDB default (`all-MiniLM-L6-v2` via ONNX — no extra API key required) |
| **Email delivery** | SendGrid |
| **Scheduling** | APScheduler — 30-min crawl interval, weekday 08:00 UTC send |
| **HTTP / async** | aiohttp — concurrent RSS fetching · asyncio throughout |
| **Feed parsing** | feedparser · BeautifulSoup4 for HTML cleaning |
| **Auth** | PyJWT — admin login issues short-lived tokens |
| **Config** | Pydantic Settings — typed `.env` loading |
| **Frontend** | Vanilla HTML / CSS / JS (single file, no build step) |
| **Typography** | Playfair Display · DM Sans via Google Fonts |
| **Deployment** | Railway or Render (backend) · GitHub Pages / Vercel / Netlify (frontend) |

---

## Quickstart

### 1. Clone and set up Python backend

```bash
git clone https://github.com/your-username/novaai.git
cd novaai/backend

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

API available at `http://localhost:8000`. Interactive docs at `http://localhost:8000/docs`.

### 4. Open the frontend

```bash
# From the project root
python -m http.server 5500
# Then open http://localhost:5500
```

---

## Pipeline agents

The crawler runs every **30 minutes**. The full pipeline runs on the same interval but only dispatches emails on weekdays at 08:00 UTC. You can also trigger it manually:

```bash
# Via API
curl -X POST http://localhost:8000/api/pipeline/trigger

# Or directly in Python
cd backend
python -c "import asyncio; from agents.pipeline import run_pipeline; asyncio.run(run_pipeline())"
```

### Agent sequence

```
Crawler → Filter → Summarizer → RAG Index → Editor → Sender
```

| Agent | What it does |
|-------|-------------|
| **Crawler** | Fetches up to 100 articles from 32+ sources every 30 minutes; deduplicates by URL |
| **Filter** | Scores articles by relevance, recency, and tag — selects the best candidates |
| **Summarizer** | Calls Claude API to generate 2-sentence summaries + full article bodies |
| **RAG Index** | Embeds and upserts summarised articles into ChromaDB for semantic search |
| **Editor** | Creates the Edition record, picks featured article, writes intro via Claude |
| **Sender** | Renders HTML email and dispatches via SendGrid to active subscribers |

### News sources

The crawler pulls from 32+ sources grouped by category:

| Category | Sources |
|----------|---------|
| **Major tech news** | The Verge AI, TechCrunch AI, Wired AI, VentureBeat AI, Ars Technica, ZDNet, Forbes AI, IEEE Spectrum, The Register AI, InfoWorld AI |
| **AI lab blogs** | OpenAI, Anthropic, Google DeepMind, Google AI, Meta AI, Microsoft AI, HuggingFace, NVIDIA, AWS ML |
| **Research** | arXiv cs.AI, arXiv cs.LG, arXiv cs.CL, MIT Tech Review, Towards Data Science |
| **Newsletters** | Import AI, Ben's Bites, AI News |
| **Google News** | Search feeds for: AI, LLMs, Generative AI, AI startups, AI policy |

To add more sources, append to the `SOURCES` list in `backend/agents/crawler.py`:

```python
{"name": "My Source", "url": "https://example.com/feed.xml", "tag_hint": ArticleTag.research},
```

---

## RAG — Ask AI

The **Ask AI** tab in the frontend lets users query the article knowledge base with natural language.

### How it works

1. User submits a question via `POST /api/search/ask`
2. The question is embedded using `all-MiniLM-L6-v2` (runs locally via ONNX — no extra API key)
3. ChromaDB returns the top-5 most semantically similar articles (cosine similarity)
4. Retrieved articles are injected as context into a Claude prompt
5. Claude generates a concise, source-cited answer

### API

```bash
# Ask a question
curl -X POST http://localhost:8000/api/search/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "What new open-source models were released this week?", "k": 5}'

# Manually trigger re-indexing
curl -X POST http://localhost:8000/api/search/index
```

### Vector store

Articles are stored in `backend/chroma_db/` (auto-created on first run). They are indexed automatically at the end of each pipeline run. To re-index all existing articles manually:

```bash
curl -X POST http://localhost:8000/api/search/index
```

---

## Changing the API endpoint

In `index.html`, update this line at the top of the `<script>` block:

```js
const API_BASE = 'http://localhost:8000';
```

Change to your deployed backend URL:

```js
const API_BASE = 'https://your-api.railway.app';
```

---

## Deployment

### Backend — Railway (recommended)

```bash
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

## Pipeline settings

Key values you can tune in `.env`:

| Variable | Default | Description |
|----------|---------|-------------|
| `PIPELINE_INTERVAL_MINUTES` | `30` | How often the crawler runs |
| `MAX_ARTICLES_PER_RUN` | `100` | Max articles fetched per pipeline run |
| `MIN_RELEVANCE_SCORE` | `0.6` | Minimum score for an article to be included |

---

## Admin access

Default credentials: `admin` / `novaai2026` — **change these in `.env` before deploying**.

The admin panel is not linked anywhere in the public UI. Navigate to `/?admin=unlock` to open the login modal. On successful login, a JWT is stored in `localStorage` and the Agents and Subscribers tabs become visible.

---
