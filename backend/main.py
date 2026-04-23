"""
NovaAI
Run with: uvicorn main:app --reload --port 8000
"""

from fastapi import FastAPI, HTTPException, Depends, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from contextlib import asynccontextmanager
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import logging

from api.routes import articles, subscribers, admin, newsletter, search
from models.database import init_db
from agents.pipeline import run_pipeline

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Initialising database...")
    await init_db()

    logger.info("Starting scheduler...")
    # Run pipeline every 30 minutes
    scheduler.add_job(run_pipeline, "interval", minutes=30, id="pipeline")
    # Send newsletter every weekday at 08:00 UTC
    scheduler.add_job(
        newsletter.send_daily_newsletter,
        "cron",
        day_of_week="mon-fri",
        hour=8,
        minute=0,
        id="daily_send",
    )
    scheduler.start()
    logger.info("Scheduler started.")

    yield

    # Shutdown
    scheduler.shutdown()
    logger.info("Scheduler stopped.")


app = FastAPI(
    title="NovaAI API",
    description="Agent-powered AI intelligence platform",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS — update origins for production
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:5500", "*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(articles.router,     prefix="/api/articles",     tags=["Articles"])
app.include_router(subscribers.router,  prefix="/api/subscribers",  tags=["Subscribers"])
app.include_router(admin.router,        prefix="/api/admin",        tags=["Admin"])
app.include_router(newsletter.router,   prefix="/api/newsletter",   tags=["Newsletter"])
app.include_router(search.router,       prefix="/api/search",       tags=["Search / RAG"])


@app.get("/")
async def root():
    return {"status": "ok", "service": "NovaAI API"}


@app.post("/api/pipeline/trigger")
async def trigger_pipeline(background_tasks: BackgroundTasks):
    """Manually trigger the agent pipeline (admin use)."""
    background_tasks.add_task(run_pipeline)
    return {"status": "pipeline triggered"}
