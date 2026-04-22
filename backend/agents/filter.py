"""
Filter Agent
────────────
Scores unprocessed articles by relevance using keyword matching + recency.
Selects the top N articles for the next newsletter edition.
"""

import logging
from datetime import datetime, timedelta
from sqlalchemy import select, update

from models.database import AsyncSessionLocal, Article, ArticleTag
from config import settings

logger = logging.getLogger(__name__)

# ── Relevance scoring weights ──────────────────────────────────────────────────
HIGH_VALUE_KEYWORDS = [
    "gpt", "claude", "gemini", "llama", "openai", "anthropic", "deepmind",
    "google ai", "meta ai", "microsoft ai", "nvidia", "model release",
    "open source", "benchmark", "research", "study", "funding", "raises",
    "regulation", "eu ai act", "breakthrough", "new model", "launches",
    "multimodal", "agi", "safety", "alignment",
]

LOW_VALUE_KEYWORDS = [
    "how to use", "tutorial", "beginner", "explained", "what is",
    "listicle", "top 10", "you need to know", "everything about",
]

TAG_WEIGHTS = {
    ArticleTag.model:    1.3,
    ArticleTag.research: 1.2,
    ArticleTag.industry: 1.1,
    ArticleTag.policy:   1.1,
    ArticleTag.tools:    0.9,
    ArticleTag.other:    0.7,
}


def score_article(article: Article) -> float:
    """
    Score an article 0–1 based on:
    - Keyword relevance   (40%)
    - Recency             (30%)
    - Tag weight          (30%)
    """
    text = (article.title + " " + (article.summary or "")).lower()

    # 1. Keyword score (0–1)
    high_hits = sum(1 for kw in HIGH_VALUE_KEYWORDS if kw in text)
    low_hits  = sum(1 for kw in LOW_VALUE_KEYWORDS if kw in text)
    kw_score  = min(1.0, (high_hits * 0.15) - (low_hits * 0.2))
    kw_score  = max(0.0, kw_score)

    # 2. Recency score (0–1) — articles older than 48h score 0
    ref_time = article.published_at or article.fetched_at or datetime.utcnow()
    age_hours = (datetime.utcnow() - ref_time).total_seconds() / 3600
    recency_score = max(0.0, 1.0 - (age_hours / 48.0))

    # 3. Tag weight (0–1)
    tag_weight = TAG_WEIGHTS.get(article.tag, 0.7)
    tag_score  = (tag_weight - 0.7) / 0.6  # normalise 0.7–1.3 → 0–1

    # Weighted combination
    final = (kw_score * 0.40) + (recency_score * 0.30) + (tag_score * 0.30)
    return round(min(1.0, max(0.0, final)), 4)


async def run_filter(limit: int = 12) -> list[int]:
    """
    Score all unsummarised articles, mark the top `limit` as selected.
    Returns list of selected article IDs.
    """
    logger.info("=== Filter Agent starting ===")

    cutoff = datetime.utcnow() - timedelta(hours=48)

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Article).where(
                Article.body == None,          # not yet summarised
                Article.fetched_at >= cutoff,  # recent only
            )
        )
        articles = result.scalars().all()

    logger.info(f"Scoring {len(articles)} unsummarised articles")

    scored = []
    for article in articles:
        score = score_article(article)
        scored.append((article.id, score))

    # Sort by score descending
    scored.sort(key=lambda x: x[1], reverse=True)

    # Filter by minimum threshold
    qualified = [
        (aid, score) for aid, score in scored
        if score >= settings.min_relevance_score
    ]

    # Take top `limit`
    selected = qualified[:limit]

    # Persist scores
    async with AsyncSessionLocal() as db:
        for article_id, score in scored:
            await db.execute(
                update(Article)
                .where(Article.id == article_id)
                .values(relevance=score)
            )
        await db.commit()

    selected_ids = [aid for aid, _ in selected]
    logger.info(
        f"=== Filter Agent done: {len(selected_ids)}/{len(articles)} articles selected "
        f"(threshold={settings.min_relevance_score}) ==="
    )
    return selected_ids
