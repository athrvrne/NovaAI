# NovaAI — Architecture & Workflow

NovaAI is an autonomous AI newsletter platform. A 6-agent pipeline crawls AI news sources every 30 minutes, filters and summarises articles with Claude, indexes them into a vector store for semantic search, composes a newsletter edition, and emails it to subscribers every weekday morning.

---

## System Overview

```
┌─────────────────────────────────────────────────────────────┐
│                        SCHEDULER                            │
│  APScheduler — pipeline every 30 min, send at 08:00 UTC M-F │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                     AGENT PIPELINE                          │
│                                                             │
│  ┌──────────┐   ┌──────────┐   ┌─────────────┐             │
│  │ Crawler  │ → │  Filter  │ → │ Summarizer  │             │
│  └──────────┘   └──────────┘   └──────┬──────┘             │
│                                       │                     │
│                                       ▼                     │
│                              ┌─────────────┐               │
│                              │  RAG Index  │               │
│                              └──────┬──────┘               │
│                                     │                       │
│                              ┌──────▼──────┐               │
│                              │   Editor    │               │
│                              └──────┬──────┘               │
│                                     │                       │
│                              ┌──────▼──────┐               │
│                              │   Sender    │               │
│                              └─────────────┘               │
└─────────────────────────────────────────────────────────────┘
                           │
          ┌────────────────┼────────────────┐
          ▼                ▼                ▼
   ┌────────────┐  ┌─────────────┐  ┌────────────────┐
   │  SQLite DB │  │  ChromaDB   │  │    SendGrid    │
   │ (articles, │  │ (embeddings)│  │  (email send)  │
   │ editions,  │  └─────────────┘  └────────────────┘
   │ subscribers│
   └────────────┘
```

---

## Pipeline Stages

### Stage 1 — Crawler (`backend/agents/crawler.py`)

Fetches raw articles from **30+ RSS feeds** in parallel using `aiohttp` and `feedparser`.

**Sources include:**
- Major tech outlets: The Verge, TechCrunch, VentureBeat, Wired, Ars Technica
- AI lab blogs: OpenAI, Anthropic, Google DeepMind, Meta AI, HuggingFace
- Research feeds: arXiv (cs.AI, cs.LG, cs.CL), MIT Technology Review, IEEE Spectrum
- Community: Import AI, Ben's Bites, Towards Data Science
- Google News search feeds for AI, LLMs, policy, and startup funding

After fetching, the crawler:
1. Strips HTML from article summaries using BeautifulSoup
2. Classifies each article into a tag (`model`, `research`, `industry`, `policy`, `tools`, `other`) using keyword scoring weighted by source hints
3. Deduplicates by URL hash before writing to the database
4. Saves up to 10 articles per source per run

**Output:** Count of new articles saved to `articles` table.

---

### Stage 2 — Filter (`backend/agents/filter.py`)

Scores every unsummarised article fetched within the last 48 hours and selects the top 12.

**Scoring formula (0–1):**
| Component | Weight | Details |
|-----------|--------|---------|
| Keyword relevance | 40% | High-value keywords (model names, "funding", "breakthrough") boost score; clickbait terms ("top 10", "beginner") penalise it |
| Recency | 30% | Linear decay — articles older than 48h score 0 |
| Tag weight | 30% | `model` (1.3×) > `research` (1.2×) > `industry`/`policy` (1.1×) > `tools` (0.9×) > `other` (0.7×) |

Only articles scoring above `min_relevance_score` (default `0.6`) advance. Scores are persisted to the DB.

**Output:** List of selected article IDs.

---

### Stage 3 — Summarizer (`backend/agents/summarizer.py`)

Calls the **Claude API** (claude-sonnet-4-20250514) for each selected article to generate:

- **2-sentence newsletter summary** — what happened and why it matters, no hype
- **400–550 word HTML body** — structured with `<h3>` section headings, a `<blockquote>` with a relevant quote, and a closing paragraph

Claude calls are run with `asyncio.Semaphore(3)` to cap concurrency at 3 simultaneous API calls and avoid rate-limit errors.

**Output:** Count of successfully summarised articles. Bodies are saved to the `articles` table.

---

### Stage 3b — RAG Index (`backend/agents/rag.py`)

After summarisation, all newly summarised articles are upserted into **ChromaDB** (a local persistent vector store).

Each article is stored as:
```
{article title}\n\n{summary}\n\n{body}  (truncated to 4000 chars)
```

ChromaDB uses its built-in embedding model with cosine similarity. The collection is created once and persisted to `./chroma_db/` on disk.

**Output:** Count of newly indexed articles.

---

### Stage 4 — Editor (`backend/agents/editor.py`)

Assembles the selected articles into a newsletter **Edition** record.

1. Sorts articles by relevance score — the highest becomes the featured/lead story
2. Calls Claude to write a punchy 2-sentence intro paragraph referencing the lead story and other topics
3. Calls Claude to generate a compelling email subject line (max 60 chars)
4. Creates `Edition` and `EditionItem` records in the database, marking the lead article as featured

**Output:** Edition ID.

---

### Stage 5 — Sender (`backend/agents/sender.py`)

Renders the edition as a **self-contained HTML email** and sends it to all active subscribers via **SendGrid**.

The email template features:
- Dark background (`#0a0a0f`) with colour-coded article tags
- Featured/lead article highlighted with a purple left border
- Per-article "Read on [Source] →" links
- Personalised unsubscribe link per recipient

Stats (recipients, status, sent_at) are written back to the `Edition` record after sending.

**Output:** Count of emails successfully dispatched.

---

## RAG / "Ask AI" Feature

Beyond the pipeline, articles are queryable via a semantic search endpoint.

```
User question
     │
     ▼
POST /api/search/ask
     │
     ▼
ChromaDB cosine search → top-k article chunks retrieved
     │
     ▼
Claude (system: "answer using ONLY the articles provided, cite sources")
     │
     ▼
{ answer: "...", sources: [ {title, source, url, score} ] }
```

The frontend exposes this as the **"Ask AI"** tab with suggestion chips and source cards.

---

## API Routes

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/api/articles` | — | List articles (paginated, filterable by tag) |
| `GET` | `/api/articles/{id}` | — | Single article detail |
| `POST` | `/api/subscribers` | — | Subscribe with email |
| `DELETE` | `/api/subscribers/{email}` | — | Unsubscribe |
| `POST` | `/api/admin/login` | — | Get JWT token |
| `GET` | `/api/admin/status` | JWT | Pipeline run log |
| `POST` | `/api/admin/pipeline/run` | JWT | Manually trigger pipeline |
| `GET` | `/api/newsletter` | — | List editions |
| `GET` | `/api/newsletter/{id}` | — | Single edition detail |
| `POST` | `/api/search/ask` | — | RAG question answering |
| `POST` | `/api/search/index` | — | Re-index all articles into ChromaDB |
| `POST` | `/api/pipeline/trigger` | — | Background pipeline trigger |

---

## Data Models

```
Article
├── id, title, summary, body (AI-generated HTML)
├── source_name, source_url (unique)
├── tag: model | research | industry | policy | tools | other
├── relevance: float 0–1
├── is_featured: bool
└── fetched_at, published_at

Edition
├── id, edition_number (unique)
├── subject, intro (both AI-generated)
├── status: draft | sent | failed
├── recipients, opens, clicks
└── created_at, sent_at

EditionItem (join table)
├── edition_id → Edition
├── article_id → Article
└── position (order within edition)

Subscriber
├── email (unique)
├── frequency: daily | weekly
└── status: active | paused | bounced
```

---

## Directory Structure

```
AI_Newsletters/
├── index.html                  # Single-file frontend (HTML/CSS/JS)
├── backend/
│   ├── main.py                 # FastAPI app, scheduler setup, CORS
│   ├── config.py               # Pydantic settings (loaded from .env)
│   ├── requirements.txt
│   ├── agents/
│   │   ├── pipeline.py         # Orchestrator — runs all stages in sequence
│   │   ├── crawler.py          # Stage 1: RSS fetching + tag classification
│   │   ├── filter.py           # Stage 2: relevance scoring + selection
│   │   ├── summarizer.py       # Stage 3: Claude API summaries + bodies
│   │   ├── rag.py              # Stage 3b + RAG: ChromaDB index + Q&A
│   │   ├── editor.py           # Stage 4: edition composition via Claude
│   │   └── sender.py           # Stage 5: HTML rendering + SendGrid send
│   ├── api/routes/
│   │   ├── articles.py         # Article CRUD endpoints
│   │   ├── subscribers.py      # Subscribe / unsubscribe endpoints
│   │   ├── admin.py            # JWT auth + pipeline control
│   │   ├── newsletter.py       # Edition listing + daily send trigger
│   │   └── search.py           # RAG ask + re-index endpoints
│   └── models/
│       └── database.py         # SQLAlchemy models + async engine
```

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend framework | FastAPI + Uvicorn |
| Database ORM | SQLAlchemy 2.0 async (`aiosqlite`) |
| Database | SQLite (dev) / PostgreSQL (prod) |
| AI model | Anthropic Claude (claude-sonnet-4-20250514) |
| Vector store | ChromaDB (local persistent) |
| Email delivery | SendGrid |
| Scheduler | APScheduler (async) |
| HTTP client | aiohttp |
| RSS parsing | feedparser |
| Frontend | Single-file HTML/CSS/JS |

---

## Configuration (`.env`)

| Variable | Default | Description |
|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | — | Required for summaries, editor, and RAG answers |
| `SENDGRID_API_KEY` | — | Required to send emails |
| `SENDGRID_FROM_EMAIL` | `hello@novaai.com` | Sender address |
| `DATABASE_URL` | SQLite | Switch to PostgreSQL for production |
| `MIN_RELEVANCE_SCORE` | `0.6` | Minimum filter score (0–1) |
| `PIPELINE_INTERVAL_MINUTES` | `30` | How often the pipeline runs |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | `admin` / `novaai2026` | Admin dashboard credentials |
| `JWT_SECRET` | dev default | Sign admin JWT tokens — **change in production** |
