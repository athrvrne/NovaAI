"""
Crawler Agent
─────────────
Fetches raw articles from RSS feeds and stores them in the database.
Runs every 30 minutes as part of the pipeline.
"""

import asyncio
import logging
import hashlib
from datetime import datetime
from typing import Optional

import aiohttp
import feedparser
from bs4 import BeautifulSoup
from sqlalchemy import select

from models.database import AsyncSessionLocal, Article, ArticleTag
from config import settings

logger = logging.getLogger(__name__)

# ── Source definitions ─────────────────────────────────────────────────────────
# Each source has: name, feed URL, and a tag hint for the classifier
SOURCES = [
    # ── Major tech news ───────────────────────────────────────────────────────
    {"name": "The Verge AI",        "url": "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",         "tag_hint": ArticleTag.industry},
    {"name": "TechCrunch AI",       "url": "https://techcrunch.com/category/artificial-intelligence/feed/",              "tag_hint": ArticleTag.industry},
    {"name": "MIT Tech Review",     "url": "https://www.technologyreview.com/feed/",                                     "tag_hint": ArticleTag.research},
    {"name": "VentureBeat AI",      "url": "https://venturebeat.com/category/ai/feed/",                                  "tag_hint": ArticleTag.industry},
    {"name": "Wired AI",            "url": "https://www.wired.com/feed/category/artificial-intelligence/latest/rss",     "tag_hint": ArticleTag.industry},
    {"name": "AI News",             "url": "https://artificialintelligence-news.com/feed/",                              "tag_hint": ArticleTag.other},
    {"name": "Ars Technica",        "url": "https://feeds.arstechnica.com/arstechnica/technology-lab",                   "tag_hint": ArticleTag.industry},
    {"name": "ZDNet AI",            "url": "https://www.zdnet.com/topic/artificial-intelligence/rss.xml",                "tag_hint": ArticleTag.industry},
    {"name": "InfoWorld AI",        "url": "https://www.infoworld.com/category/artificial-intelligence/index.rss",       "tag_hint": ArticleTag.tools},
    {"name": "The Register AI",     "url": "https://www.theregister.com/software/ai_ml/headlines.atom",                  "tag_hint": ArticleTag.industry},
    {"name": "Forbes AI",           "url": "https://www.forbes.com/ai/feed/",                                            "tag_hint": ArticleTag.industry},
    {"name": "IEEE Spectrum",       "url": "https://spectrum.ieee.org/feeds/feed.rss",                                   "tag_hint": ArticleTag.research},

    # ── AI lab & company blogs ────────────────────────────────────────────────
    {"name": "Google AI Blog",      "url": "https://blog.google/technology/ai/rss/",                                     "tag_hint": ArticleTag.model},
    {"name": "Google DeepMind",     "url": "https://deepmind.google/blog/rss.xml",                                       "tag_hint": ArticleTag.research},
    {"name": "OpenAI Blog",         "url": "https://openai.com/blog/rss.xml",                                            "tag_hint": ArticleTag.model},
    {"name": "Anthropic Blog",      "url": "https://www.anthropic.com/rss.xml",                                          "tag_hint": ArticleTag.model},
    {"name": "Meta AI Blog",        "url": "https://ai.meta.com/blog/rss/",                                              "tag_hint": ArticleTag.model},
    {"name": "Microsoft AI",        "url": "https://blogs.microsoft.com/ai/feed/",                                       "tag_hint": ArticleTag.industry},
    {"name": "HuggingFace Blog",    "url": "https://huggingface.co/blog/feed.xml",                                       "tag_hint": ArticleTag.tools},
    {"name": "NVIDIA Blog",         "url": "https://blogs.nvidia.com/feed/",                                             "tag_hint": ArticleTag.industry},
    {"name": "AWS ML Blog",         "url": "https://aws.amazon.com/blogs/machine-learning/feed/",                        "tag_hint": ArticleTag.tools},

    # ── Research & academic ───────────────────────────────────────────────────
    {"name": "arXiv cs.AI",         "url": "http://arxiv.org/rss/cs.AI",                                                 "tag_hint": ArticleTag.research},
    {"name": "arXiv cs.LG",         "url": "http://arxiv.org/rss/cs.LG",                                                 "tag_hint": ArticleTag.research},
    {"name": "arXiv cs.CL",         "url": "http://arxiv.org/rss/cs.CL",                                                 "tag_hint": ArticleTag.research},
    {"name": "Towards Data Science", "url": "https://towardsdatascience.com/feed",                                       "tag_hint": ArticleTag.research},

    # ── Newsletters & community ───────────────────────────────────────────────
    {"name": "Import AI",           "url": "https://importai.substack.com/feed",                                         "tag_hint": ArticleTag.research},
    {"name": "Ben's Bites",         "url": "https://bensbites.beehiiv.com/feed",                                         "tag_hint": ArticleTag.other},

    # ── Google News search feeds ──────────────────────────────────────────────
    {"name": "Google News: AI",          "url": "https://news.google.com/rss/search?q=artificial+intelligence&hl=en-US&gl=US&ceid=US:en",  "tag_hint": ArticleTag.other},
    {"name": "Google News: LLM",         "url": "https://news.google.com/rss/search?q=large+language+model&hl=en-US&gl=US&ceid=US:en",     "tag_hint": ArticleTag.model},
    {"name": "Google News: Generative AI","url": "https://news.google.com/rss/search?q=generative+AI&hl=en-US&gl=US&ceid=US:en",           "tag_hint": ArticleTag.model},
    {"name": "Google News: AI Startup",  "url": "https://news.google.com/rss/search?q=AI+startup+funding&hl=en-US&gl=US&ceid=US:en",       "tag_hint": ArticleTag.industry},
    {"name": "Google News: AI Policy",   "url": "https://news.google.com/rss/search?q=AI+regulation+policy&hl=en-US&gl=US&ceid=US:en",     "tag_hint": ArticleTag.policy},
]

# Add any custom RSS feeds from config
for feed_url in settings.rss_feed_list:
    SOURCES.append({"name": "Custom Feed", "url": feed_url, "tag_hint": ArticleTag.other})


# ── Tag classifier ─────────────────────────────────────────────────────────────
TAG_KEYWORDS = {
    ArticleTag.model:    ["gpt", "claude", "gemini", "llama", "model", "release", "open source", "weights", "benchmark", "hugging face", "mistral", "openai", "anthropic"],
    ArticleTag.research: ["paper", "study", "research", "arxiv", "deepmind", "stanford", "mit", "university", "experiment", "findings", "dataset", "evaluation"],
    ArticleTag.industry: ["funding", "raises", "valuation", "microsoft", "google", "meta", "amazon", "startup", "acquisition", "partnership", "enterprise", "product"],
    ArticleTag.policy:   ["regulation", "policy", "law", "eu ai act", "government", "congress", "ban", "compliance", "gdpr", "safety", "ethics", "audit"],
    ArticleTag.tools:    ["tool", "plugin", "extension", "api", "sdk", "integration", "developer", "framework", "library", "open source", "github"],
}


def classify_tag(title: str, summary: str, hint: ArticleTag) -> ArticleTag:
    """Simple keyword-based tag classifier. Returns the best matching tag."""
    text = (title + " " + summary).lower()
    scores = {tag: 0 for tag in ArticleTag}
    scores[hint] += 1  # Give weight to source hint

    for tag, keywords in TAG_KEYWORDS.items():
        for kw in keywords:
            if kw in text:
                scores[tag] += 1

    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else ArticleTag.other


def url_hash(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()


async def fetch_feed(session: aiohttp.ClientSession, source: dict) -> list[dict]:
    """Fetch and parse a single RSS feed, returning raw article dicts."""
    raw_articles = []
    try:
        async with session.get(source["url"], timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200:
                logger.warning(f"Feed {source['name']} returned HTTP {resp.status}")
                return []
            content = await resp.text()

        feed = feedparser.parse(content)
        logger.info(f"  {source['name']}: {len(feed.entries)} entries found")

        for entry in feed.entries[:10]:  # Max 10 per source per run
            title   = entry.get("title", "").strip()
            link    = entry.get("link", "").strip()
            summary = BeautifulSoup(
                entry.get("summary", entry.get("description", "")), "html.parser"
            ).get_text()[:600].strip()

            if not title or not link:
                continue

            # Parse published date
            published_at = None
            if hasattr(entry, "published_parsed") and entry.published_parsed:
                try:
                    published_at = datetime(*entry.published_parsed[:6])
                except Exception:
                    pass

            raw_articles.append({
                "title":        title,
                "summary":      summary,
                "source_name":  source["name"],
                "source_url":   link,
                "tag_hint":     source["tag_hint"],
                "published_at": published_at,
            })

    except asyncio.TimeoutError:
        logger.warning(f"Timeout fetching {source['name']}")
    except Exception as e:
        logger.error(f"Error fetching {source['name']}: {e}")

    return raw_articles


async def run_crawler() -> int:
    """
    Main crawler entry point.
    Fetches all feeds, deduplicates, and saves new articles to DB.
    Returns the number of new articles saved.
    """
    logger.info("=== Crawler Agent starting ===")
    saved = 0

    async with aiohttp.ClientSession(
        headers={"User-Agent": "NovaAI-Bot/1.0"}
    ) as session:
        tasks = [fetch_feed(session, src) for src in SOURCES]
        results = await asyncio.gather(*tasks)

    all_raw = [item for batch in results for item in batch]
    logger.info(f"Total raw articles fetched: {len(all_raw)}")

    async with AsyncSessionLocal() as db:
        for raw in all_raw:
            # Check for duplicates by URL
            existing = await db.execute(
                select(Article).where(Article.source_url == raw["source_url"])
            )
            if existing.scalar_one_or_none():
                continue  # Already stored

            tag = classify_tag(raw["title"], raw["summary"], raw["tag_hint"])

            article = Article(
                title        = raw["title"],
                summary      = raw["summary"],
                source_name  = raw["source_name"],
                source_url   = raw["source_url"],
                tag          = tag,
                published_at = raw.get("published_at"),
                fetched_at   = datetime.utcnow(),
            )
            db.add(article)
            saved += 1

        await db.commit()

    logger.info(f"=== Crawler Agent done: {saved} new articles saved ===")
    return saved
