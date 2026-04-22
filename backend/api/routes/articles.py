"""
Articles API Routes
GET  /api/articles          — paginated list (public)
GET  /api/articles/{id}     — single article (public)
GET  /api/articles/today    — today's feed (public)
"""

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy import select, desc
from datetime import datetime, timedelta

from models.database import AsyncSession, get_db, Article

router = APIRouter()


@router.get("/today")
async def get_today_articles(
    tag: str | None = Query(None, description="Filter by tag"),
    db: AsyncSession = Depends(get_db),
):
    """Return all articles fetched in the last 24h, ordered by relevance."""
    cutoff = datetime.utcnow() - timedelta(hours=24)

    q = select(Article).where(Article.fetched_at >= cutoff)
    if tag and tag != "all":
        q = q.where(Article.tag == tag)
    q = q.order_by(Article.is_featured.desc(), Article.relevance.desc())

    result = await db.execute(q)
    articles = result.scalars().all()

    return {"articles": [a.to_dict() for a in articles], "count": len(articles)}


@router.get("/")
async def list_articles(
    page:  int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    tag:   str | None = Query(None),
    db:    AsyncSession = Depends(get_db),
):
    offset = (page - 1) * limit
    q = select(Article).order_by(desc(Article.fetched_at)).offset(offset).limit(limit)
    if tag and tag != "all":
        q = q.where(Article.tag == tag)

    result = await db.execute(q)
    articles = result.scalars().all()

    return {
        "articles": [a.to_dict() for a in articles],
        "page":     page,
        "limit":    limit,
    }


@router.get("/{article_id}")
async def get_article(article_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Article).where(Article.id == article_id))
    article = result.scalar_one_or_none()
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    return article.to_dict()
