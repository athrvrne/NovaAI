"""
Search / RAG Routes
POST /api/search/ask    — question → grounded AI answer with sources (public)
POST /api/search/index  — (re)index all summarised articles into ChromaDB (admin)
"""

import asyncio
from fastapi import APIRouter
from pydantic import BaseModel, Field

from agents.rag import rag_answer, index_all_articles

router = APIRouter()


class AskRequest(BaseModel):
    question: str = Field(..., min_length=3, max_length=500)
    k:        int = Field(5, ge=1, le=10, description="Articles to retrieve")


@router.post("/ask")
async def ask(body: AskRequest):
    """RAG endpoint: retrieve relevant articles then answer with Claude."""
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, rag_answer, body.question, body.k)
    return result


@router.post("/index")
async def trigger_index():
    """(Re)index all summarised articles into ChromaDB."""
    count = await index_all_articles()
    return {"indexed": count}
