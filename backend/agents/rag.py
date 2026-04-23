"""
RAG Agent
─────────
Indexes article embeddings into ChromaDB (persistent, local vector store).
Retrieves semantically relevant articles for a query, then uses Claude to
generate a grounded answer from the retrieved context.
"""

import logging
import asyncio
from typing import Optional

import chromadb
import anthropic
from sqlalchemy import select

from models.database import AsyncSessionLocal, Article
from config import settings

logger = logging.getLogger(__name__)

_collection: Optional[chromadb.Collection] = None

RAG_SYSTEM = (
    "You are an expert AI news analyst. Answer the user's question using ONLY the articles provided. "
    "Be concise and factual. Cite sources by name in brackets, e.g. [OpenAI Blog]. "
    "If the articles don't contain enough information, say so clearly."
)

RAG_USER = "Articles:\n{context}\n\nQuestion: {question}"


def _get_collection() -> chromadb.Collection:
    global _collection
    if _collection is None:
        client = chromadb.PersistentClient(path="./chroma_db")
        _collection = client.get_or_create_collection(
            name="articles",
            metadata={"hnsw:space": "cosine"},
        )
    return _collection


def index_article(article) -> bool:
    """Upsert a single article into ChromaDB. Returns True on success."""
    try:
        collection = _get_collection()
        text = f"{article.title}\n\n{article.summary}\n\n{article.body or ''}"
        collection.upsert(
            ids=[str(article.id)],
            documents=[text[:4000]],
            metadatas=[{
                "title":      article.title,
                "source":     article.source_name,
                "source_url": article.source_url,
                "tag":        article.tag.value if article.tag else "other",
                "article_id": article.id,
            }],
        )
        return True
    except Exception as e:
        logger.error(f"Failed to index article {article.id}: {e}")
        return False


def retrieve(query: str, k: int = 5) -> list[dict]:
    """Return top-k articles most semantically similar to query."""
    collection = _get_collection()
    n = collection.count()
    if n == 0:
        return []
    results = collection.query(
        query_texts=[query],
        n_results=min(k, n),
        include=["documents", "metadatas", "distances"],
    )
    hits = []
    for doc, meta, dist in zip(
        results["documents"][0],
        results["metadatas"][0],
        results["distances"][0],
    ):
        hits.append({
            "article_id": meta.get("article_id"),
            "title":      meta.get("title", ""),
            "source":     meta.get("source", ""),
            "source_url": meta.get("source_url", ""),
            "tag":        meta.get("tag", "other"),
            "snippet":    doc[:400],
            "score":      round(1.0 - float(dist), 4),
        })
    return hits


def rag_answer(question: str, k: int = 5) -> dict:
    """Retrieve relevant articles and produce a Claude-grounded answer."""
    hits = retrieve(question, k=k)

    if not hits:
        return {
            "answer":  "No indexed articles found. Run the pipeline first to populate the knowledge base.",
            "sources": [],
        }

    context_parts = []
    for i, hit in enumerate(hits, 1):
        context_parts.append(f"[{i}] {hit['title']} ({hit['source']})\n{hit['snippet']}")
    context = "\n\n---\n\n".join(context_parts)

    if not settings.anthropic_api_key:
        return {
            "answer":  "Set ANTHROPIC_API_KEY to enable AI-generated answers.",
            "sources": hits,
        }

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    try:
        msg = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=512,
            system=RAG_SYSTEM,
            messages=[{"role": "user", "content": RAG_USER.format(context=context, question=question)}],
        )
        answer = msg.content[0].text.strip()
    except Exception as e:
        logger.error(f"Claude RAG call failed: {e}")
        answer = "Failed to generate an answer — please try again."

    return {"answer": answer, "sources": hits}


async def index_all_articles() -> int:
    """Index every summarised article not yet in ChromaDB. Returns count added."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Article).where(Article.body.isnot(None)))
        articles = result.scalars().all()

    collection = _get_collection()
    existing_ids = set(collection.get()["ids"])

    count = 0
    for article in articles:
        if str(article.id) not in existing_ids:
            if index_article(article):
                count += 1

    logger.info(f"RAG: indexed {count} new articles (total in store: {collection.count()})")
    return count
