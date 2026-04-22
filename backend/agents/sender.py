"""
Sender Agent
────────────
Renders the newsletter HTML template and sends it to all active subscribers
via the SendGrid API. Tracks recipient counts on the Edition record.
"""

import logging
from datetime import datetime
from typing import Optional

import sendgrid
from sendgrid.helpers.mail import Mail, Email, To, Content, HtmlContent
from sqlalchemy import select, update

from models.database import AsyncSessionLocal, Edition, EditionItem, Subscriber, SubscriberFrequency, SubscriberStatus
from config import settings

logger = logging.getLogger(__name__)


def render_html(edition: Edition, items: list) -> str:
    """Render the newsletter as a self-contained HTML email."""
    articles_html = ""
    for i, item in enumerate(items):
        article = item.article
        tag_color = {
            "model":    "#7c6dfa",
            "research": "#4ade80",
            "industry": "#fb923c",
            "policy":   "#f472b6",
            "tools":    "#38bdf8",
        }.get(article.tag.value if article.tag else "other", "#888")

        featured_style = (
            "border-left: 3px solid #7c6dfa; padding-left: 1rem;"
            if i == 0 else ""
        )

        articles_html += f"""
        <div style="margin-bottom:2rem; padding-bottom:2rem;
                    border-bottom:1px solid rgba(255,255,255,0.07); {featured_style}">
          <p style="font-size:11px; font-weight:600; letter-spacing:0.1em;
                    text-transform:uppercase; color:{tag_color}; margin:0 0 8px;">
            {article.tag.value.upper() if article.tag else "AI"}
          </p>
          <h2 style="font-family:Georgia,serif; font-size:20px; color:#ffffff;
                     line-height:1.3; margin:0 0 10px; font-weight:700;">
            {article.title}
          </h2>
          <p style="font-size:14px; color:rgba(255,255,255,0.55);
                    line-height:1.6; margin:0 0 12px;">
            {article.summary}
          </p>
          <a href="{article.source_url}"
             style="font-size:12px; color:#7c6dfa; text-decoration:none; font-weight:500;">
            Read on {article.source_name} →
          </a>
        </div>
        """

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{edition.subject}</title>
</head>
<body style="margin:0; padding:0; background:#0a0a0f; font-family:'Helvetica Neue',Arial,sans-serif;">
  <div style="max-width:600px; margin:0 auto; padding:40px 24px;">

    <!-- Header -->
    <div style="text-align:center; margin-bottom:40px; padding-bottom:24px;
                border-bottom:1px solid rgba(255,255,255,0.08);">
      <p style="font-size:11px; letter-spacing:0.15em; text-transform:uppercase;
                color:#7c6dfa; margin:0 0 8px; font-weight:600;">AI Intelligence Daily</p>
      <h1 style="font-family:Georgia,serif; font-size:32px; color:#ffffff;
                 margin:0; font-weight:700; letter-spacing:-0.02em;">
        Nova<span style="color:#D4843A;">AI</span>
      </h1>
      <p style="font-size:12px; color:rgba(255,255,255,0.3); margin:8px 0 0;">
        Edition #{edition.edition_number} · {datetime.utcnow().strftime('%B %d, %Y')}
      </p>
    </div>

    <!-- Intro -->
    <div style="background:rgba(124,109,250,0.08); border:1px solid rgba(124,109,250,0.15);
                border-radius:10px; padding:20px 24px; margin-bottom:36px;">
      <p style="font-size:15px; color:rgba(255,255,255,0.75); line-height:1.7; margin:0;">
        {edition.intro or "Today's top AI stories, curated by our agent pipeline."}
      </p>
    </div>

    <!-- Articles -->
    {articles_html}

    <!-- Footer -->
    <div style="text-align:center; padding-top:24px;
                border-top:1px solid rgba(255,255,255,0.06);">
      <p style="font-size:12px; color:rgba(255,255,255,0.2); margin:0 0 8px;">
        You're receiving this because you subscribed to NovaAI.
      </p>
      <a href="{{{{ unsubscribe_url }}}}"
         style="font-size:12px; color:rgba(255,255,255,0.3); text-decoration:underline;">
        Unsubscribe
      </a>
    </div>

  </div>
</body>
</html>"""


async def run_sender(edition_id: int) -> int:
    """
    Send a given Edition to all active subscribers.
    Returns the number of emails sent.
    """
    logger.info(f"=== Sender Agent starting: Edition {edition_id} ===")

    if not settings.sendgrid_api_key:
        logger.warning("No SendGrid API key set — skipping send")
        return 0

    async with AsyncSessionLocal() as db:
        # Load edition + items + articles
        result = await db.execute(
            select(Edition).where(Edition.id == edition_id)
        )
        edition = result.scalar_one_or_none()
        if not edition:
            logger.error(f"Edition {edition_id} not found")
            return 0

        items_result = await db.execute(
            select(EditionItem)
            .where(EditionItem.edition_id == edition_id)
            .order_by(EditionItem.position)
        )
        items = items_result.scalars().all()

        # Load active subscribers
        subs_result = await db.execute(
            select(Subscriber).where(Subscriber.status == SubscriberStatus.active)
        )
        subscribers = subs_result.scalars().all()

    if not subscribers:
        logger.warning("No active subscribers to send to")
        return 0

    html_body = render_html(edition, items)
    sg = sendgrid.SendGridAPIClient(api_key=settings.sendgrid_api_key)

    sent = 0
    failed = 0

    for subscriber in subscribers:
        try:
            message = Mail(
                from_email=Email(
                    settings.sendgrid_from_email,
                    settings.sendgrid_from_name,
                ),
                to_emails=To(subscriber.email),
                subject=edition.subject,
                html_content=HtmlContent(
                    html_body.replace("{{ unsubscribe_url }}", f"https://novaai.com/unsubscribe?email={subscriber.email}")
                ),
            )
            sg.send(message)
            sent += 1
        except Exception as e:
            logger.error(f"Failed to send to {subscriber.email}: {e}")
            failed += 1

    # Update edition stats
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(Edition)
            .where(Edition.id == edition_id)
            .values(
                recipients=sent,
                status="sent",
                sent_at=datetime.utcnow(),
            )
        )
        await db.commit()

    logger.info(
        f"=== Sender Agent done: {sent} sent, {failed} failed ==="
    )
    return sent
