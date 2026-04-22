"""
Editor Agent
────────────
Assembles the selected, summarised articles into a newsletter Edition.
- Picks the featured article (highest relevance score)
- Writes an intro paragraph via Claude
- Creates the Edition and EditionItem records
"""

import logging
from datetime import datetime
from typing import Optional

import anthropic
from sqlalchemy import select, func

from models.database import AsyncSessionLocal, Article, Edition, EditionItem
from config import settings

logger = logging.getLogger(__name__)

client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

INTRO_PROMPT = """You are the editor of NovaAI, a daily AI intelligence briefing.
Write a short, punchy 2-sentence intro paragraph for today's edition.
The lead story is: "{lead_story}"
Other topics covered: {other_topics}

Tone: knowledgeable, direct, slightly opinionated. No fluff.
Return ONLY the 2-sentence intro, nothing else."""

SUBJECT_PROMPT = """Write a compelling email subject line for today's AI newsletter.
Lead story: "{lead_story}"
Max 60 characters. No emojis. Make it specific and click-worthy.
Return ONLY the subject line."""


def call_claude(prompt: str, max_tokens: int = 200) -> Optional[str]:
    try:
        msg = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        return msg.content[0].text.strip()
    except Exception as e:
        logger.error(f"Claude error in editor: {e}")
        return None


async def get_next_edition_number() -> int:
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(func.max(Edition.edition_number)))
        max_num = result.scalar_one_or_none()
        return (max_num or 0) + 1


async def run_editor(article_ids: list[int]) -> Optional[int]:
    """
    Compose a new Edition from the given article IDs.
    Returns the new Edition ID, or None on failure.
    """
    logger.info(f"=== Editor Agent starting with {len(article_ids)} articles ===")

    if not article_ids:
        logger.warning("No articles to compose edition from")
        return None

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Article)
            .where(Article.id.in_(article_ids))
            .order_by(Article.relevance.desc())
        )
        articles = result.scalars().all()

    if not articles:
        return None

    # Featured = highest relevance
    featured      = articles[0]
    rest          = articles[1:]
    other_topics  = ", ".join([a.title[:50] for a in rest[:4]])

    # Generate intro and subject line via Claude (fallback to plain text if no key)
    if settings.anthropic_api_key:
        intro = call_claude(INTRO_PROMPT.format(
            lead_story=featured.title,
            other_topics=other_topics or "various AI developments",
        ))
        subject = call_claude(SUBJECT_PROMPT.format(lead_story=featured.title))
    else:
        intro   = f"Today's top story: {featured.title}. Plus more AI developments below."
        subject = f"NovaAI: {featured.title[:50]}"

    intro   = intro   or f"Today in AI: {featured.title}"
    subject = subject or f"NovaAI Daily — {datetime.utcnow().strftime('%b %d, %Y')}"

    edition_number = await get_next_edition_number()

    async with AsyncSessionLocal() as db:
        edition = Edition(
            edition_number=edition_number,
            subject=subject,
            intro=intro,
            created_at=datetime.utcnow(),
        )
        db.add(edition)
        await db.flush()  # get edition.id

        # Mark featured article
        for i, article in enumerate(articles):
            item = EditionItem(
                edition_id=edition.id,
                article_id=article.id,
                position=i,
            )
            db.add(item)
            # Mark first article as featured
            if i == 0:
                article.is_featured = True

        await db.commit()
        edition_id = edition.id

    logger.info(
        f"=== Editor Agent done: Edition #{edition_number} created "
        f"(id={edition_id}, {len(articles)} articles) ==="
    )
    return edition_id
