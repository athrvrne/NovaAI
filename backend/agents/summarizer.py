"""
Summarizer Agent
────────────────
Uses the Anthropic Claude API to generate:
  - A concise 2-sentence newsletter summary
  - A full 4–6 paragraph article body with H3 headers and a blockquote
"""

import logging
import asyncio
from typing import Optional

import anthropic
from sqlalchemy import select, update

from models.database import AsyncSessionLocal, Article
from config import settings

logger = logging.getLogger(__name__)

client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

SUMMARY_PROMPT = """You are an expert AI news editor. Write a concise 2-sentence newsletter summary of the following article.
Focus on: what happened, why it matters. Be factual, no hype.

Article title: {title}
Article content: {content}
Source: {source}

Return ONLY the 2-sentence summary, nothing else."""

BODY_PROMPT = """You are an expert AI journalist writing for a technical newsletter read by engineers, researchers, and product people.

Write a detailed article body (400–550 words) about the following news item.
Structure it as:
- Opening paragraph (context and what happened)
- <h3>Section heading</h3> — key details / technical depth
- A <blockquote> containing a relevant real or plausible quote (attributed to a named person or the source publication)
- <h3>Another section</h3> — implications / what comes next
- Closing paragraph

Use <p>, <h3>, and <blockquote> HTML tags only. No markdown.
Be factual, specific, and useful. Avoid fluff.

Article title: {title}
Source summary: {summary}
Source: {source}

Return ONLY the HTML body content, no wrapper tags."""


def call_claude(prompt: str) -> Optional[str]:
    """Synchronous Claude API call."""
    try:
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text.strip()
    except anthropic.APIError as e:
        logger.error(f"Claude API error: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error calling Claude: {e}")
        return None


def generate_summary(title: str, content: str, source: str) -> Optional[str]:
    prompt = SUMMARY_PROMPT.format(title=title, content=content[:2000], source=source)
    return call_claude(prompt)


def generate_body(title: str, summary: str, source: str) -> Optional[str]:
    prompt = BODY_PROMPT.format(title=title, summary=summary, source=source)
    return call_claude(prompt)


async def summarise_article(article_id: int) -> bool:
    """
    Generate summary + body for a single article.
    Returns True on success.
    """
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Article).where(Article.id == article_id))
        article = result.scalar_one_or_none()

        if not article:
            logger.warning(f"Article {article_id} not found")
            return False

        if article.body:
            logger.info(f"Article {article_id} already summarised, skipping")
            return True

        logger.info(f"Summarising article {article_id}: {article.title[:60]}...")

        # Run blocking Claude calls in a thread pool to avoid blocking the event loop
        loop = asyncio.get_event_loop()

        summary = await loop.run_in_executor(
            None, generate_summary, article.title, article.summary, article.source_name
        )

        if summary:
            body = await loop.run_in_executor(
                None, generate_body, article.title, summary, article.source_name
            )
        else:
            body = None

        # Update article with AI-generated content
        await db.execute(
            update(Article)
            .where(Article.id == article_id)
            .values(
                summary=summary or article.summary,
                body=body or f"<p>{article.summary}</p>",
            )
        )
        await db.commit()

    logger.info(f"Article {article_id} summarised successfully")
    return True


async def run_summarizer(article_ids: list[int]) -> int:
    """
    Summarise all selected articles.
    Processes them with a small concurrency limit to respect API rate limits.
    Returns count of successfully summarised articles.
    """
    logger.info(f"=== Summarizer Agent starting: {len(article_ids)} articles ===")

    if not settings.anthropic_api_key:
        logger.warning("No Anthropic API key set — skipping summarization")
        return 0

    success_count = 0
    semaphore = asyncio.Semaphore(3)  # Max 3 concurrent Claude calls

    async def bounded_summarise(article_id: int):
        nonlocal success_count
        async with semaphore:
            ok = await summarise_article(article_id)
            if ok:
                success_count += 1
            await asyncio.sleep(0.5)  # Small delay between calls

    tasks = [bounded_summarise(aid) for aid in article_ids]
    await asyncio.gather(*tasks)

    logger.info(f"=== Summarizer Agent done: {success_count}/{len(article_ids)} summarised ===")
    return success_count
