"""
Newsletter Editions API Routes
GET  /api/newsletter/editions       — list past editions (public)
GET  /api/newsletter/editions/{id}  — edition detail (public)
POST /api/newsletter/send/{id}      — manually send edition (admin)
"""

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy import select, desc

from models.database import AsyncSession, get_db, Edition, EditionItem, Article
from api.routes.admin import require_admin

router = APIRouter()


@router.get("/editions")
async def list_editions(db: AsyncSession = Depends(get_db)):
    """List all sent/draft editions, newest first."""
    result = await db.execute(
        select(Edition).order_by(desc(Edition.edition_number)).limit(20)
    )
    editions = result.scalars().all()
    return {"editions": [e.to_dict() for e in editions]}


@router.get("/editions/{edition_id}")
async def get_edition(edition_id: int, db: AsyncSession = Depends(get_db)):
    """Get a single edition with its articles."""
    result = await db.execute(select(Edition).where(Edition.id == edition_id))
    edition = result.scalar_one_or_none()
    if not edition:
        raise HTTPException(status_code=404, detail="Edition not found")

    items_result = await db.execute(
        select(EditionItem)
        .where(EditionItem.edition_id == edition_id)
        .order_by(EditionItem.position)
    )
    items = items_result.scalars().all()

    articles = []
    for item in items:
        art_result = await db.execute(select(Article).where(Article.id == item.article_id))
        article = art_result.scalar_one_or_none()
        if article:
            articles.append(article.to_dict())

    data = edition.to_dict()
    data["articles"] = articles
    return data


@router.post("/send/{edition_id}", dependencies=[Depends(require_admin)])
async def send_edition(
    edition_id: int,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Admin: manually send a specific edition."""
    result = await db.execute(select(Edition).where(Edition.id == edition_id))
    edition = result.scalar_one_or_none()
    if not edition:
        raise HTTPException(status_code=404, detail="Edition not found")

    from agents.sender import run_sender
    background_tasks.add_task(run_sender, edition_id)
    return {"status": "send queued", "edition_id": edition_id}


async def send_daily_newsletter():
    """Called by the scheduler every weekday at 08:00 UTC."""
    import logging
    from sqlalchemy import desc
    from models.database import AsyncSessionLocal
    from agents.sender import run_sender

    logger = logging.getLogger(__name__)
    logger.info("Scheduled daily send triggered")

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Edition)
            .where(Edition.status == "draft")
            .order_by(desc(Edition.edition_number))
            .limit(1)
        )
        edition = result.scalar_one_or_none()

    if not edition:
        logger.warning("No draft edition found for daily send")
        return

    await run_sender(edition.id)
