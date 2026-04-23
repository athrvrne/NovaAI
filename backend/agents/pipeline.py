"""
Pipeline Orchestrator
─────────────────────
Runs all agents in sequence:
  Crawler → Filter → Summarizer → Editor → Sender

Called by the APScheduler every 6 hours, and on-demand via the API.
"""

import logging
from datetime import datetime

from agents.crawler    import run_crawler
from agents.filter     import run_filter
from agents.summarizer import run_summarizer
from agents.editor     import run_editor
from agents.sender     import run_sender
from agents.rag        import index_all_articles as rag_index

logger = logging.getLogger(__name__)

# In-memory run log for the admin dashboard
pipeline_log: list[dict] = []
pipeline_running: bool = False


def log_step(level: str, message: str):
    """Append a timestamped step to the pipeline log."""
    entry = {
        "time":    datetime.utcnow().strftime("%H:%M:%S"),
        "level":   level,   # "ok" | "info" | "warn" | "error"
        "message": message,
    }
    pipeline_log.append(entry)
    # Keep only the last 200 entries
    if len(pipeline_log) > 200:
        pipeline_log.pop(0)

    getattr(logger, "info" if level in ("ok", "info") else level)(message)


async def run_pipeline():
    """Full end-to-end pipeline run."""
    global pipeline_running

    if pipeline_running:
        logger.warning("Pipeline already running — skipping trigger")
        return

    pipeline_running = True
    log_step("info", "Pipeline started")

    try:
        # ── Step 1: Crawl ──────────────────────────────────────────────────────
        log_step("info", "Crawler Agent: scanning sources...")
        new_count = await run_crawler()
        log_step("ok", f"Crawler done: {new_count} new articles fetched")

        if new_count == 0:
            log_step("info", "No new articles found — pipeline complete (no edition created)")
            return

        # ── Step 2: Filter ─────────────────────────────────────────────────────
        log_step("info", "Filter Agent: scoring and selecting articles...")
        selected_ids = await run_filter()
        log_step("ok", f"Filter done: {len(selected_ids)} articles selected")

        if not selected_ids:
            log_step("warn", "No articles passed the relevance threshold — stopping")
            return

        # ── Step 3: Summarize ──────────────────────────────────────────────────
        log_step("info", f"Summarizer Agent: generating summaries for {len(selected_ids)} articles...")
        summarised = await run_summarizer(selected_ids)
        log_step("ok", f"Summarizer done: {summarised}/{len(selected_ids)} summarised")

        # ── Step 3b: RAG Index ─────────────────────────────────────────────────
        log_step("info", "RAG Agent: indexing summarised articles...")
        indexed = await rag_index()
        log_step("ok", f"RAG Agent done: {indexed} new articles indexed")

        # ── Step 4: Edit ───────────────────────────────────────────────────────
        log_step("info", "Editor Agent: composing newsletter edition...")
        edition_id = await run_editor(selected_ids)

        if not edition_id:
            log_step("error", "Editor failed to create edition — stopping")
            return

        log_step("ok", f"Editor done: Edition created (id={edition_id})")

        # ── Step 5: Send ───────────────────────────────────────────────────────
        log_step("info", "Sender Agent: dispatching emails...")
        sent = await run_sender(edition_id)
        log_step("ok", f"Sender done: {sent} emails dispatched")

        log_step("ok", "Pipeline complete ✓")

    except Exception as e:
        log_step("error", f"Pipeline failed: {e}")
        logger.exception("Unhandled exception in pipeline")

    finally:
        pipeline_running = False


def get_pipeline_status() -> dict:
    return {
        "running": pipeline_running,
        "log":     pipeline_log[-50:],  # Return last 50 entries
    }
