"""
Database models and async engine setup using SQLAlchemy + aiosqlite
"""

from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Text, Float,
    DateTime, Boolean, ForeignKey, Enum as SAEnum
)
from sqlalchemy.orm import relationship, declarative_base
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
import enum

from config import settings

Base = declarative_base()

# ── Engine & Session ───────────────────────────────────────────────────────────

engine = create_async_engine(
    settings.database_url,
    echo=(settings.app_env == "development"),
    future=True,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db():
    """FastAPI dependency — yields a DB session per request."""
    async with AsyncSessionLocal() as session:
        yield session


async def init_db():
    """Create all tables on startup."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


# ── Enums ──────────────────────────────────────────────────────────────────────

class ArticleTag(str, enum.Enum):
    model     = "model"
    research  = "research"
    industry  = "industry"
    policy    = "policy"
    tools     = "tools"
    other     = "other"


class SubscriberFrequency(str, enum.Enum):
    daily   = "daily"
    weekly  = "weekly"


class SubscriberStatus(str, enum.Enum):
    active  = "active"
    paused  = "paused"
    bounced = "bounced"


class EditionStatus(str, enum.Enum):
    draft   = "draft"
    sent    = "sent"
    failed  = "failed"


# ── Models ─────────────────────────────────────────────────────────────────────

class Article(Base):
    __tablename__ = "articles"

    id            = Column(Integer, primary_key=True, index=True)
    title         = Column(String(512), nullable=False)
    summary       = Column(Text, nullable=False)
    body          = Column(Text, nullable=True)       # AI-generated full body
    source_name   = Column(String(128), nullable=False)
    source_url    = Column(String(1024), nullable=False, unique=True)
    tag           = Column(SAEnum(ArticleTag), default=ArticleTag.other)
    relevance     = Column(Float, default=0.0)        # 0–1 score from filter agent
    is_featured   = Column(Boolean, default=False)
    fetched_at    = Column(DateTime, default=datetime.utcnow)
    published_at  = Column(DateTime, nullable=True)

    edition_items = relationship("EditionItem", back_populates="article")

    def to_dict(self):
        return {
            "id":           self.id,
            "headline":     self.title,
            "summary":      self.summary,
            "body":         self.body or "",
            "source":       self.source_name,
            "source_url":   self.source_url,
            "tag":          self.tag.value if self.tag else "other",
            "cls":          f"tag-{self.tag.value}" if self.tag else "tag-other",
            "relevance":    self.relevance,
            "is_featured":  self.is_featured,
            "time":         self._time_ago(),
            "read":         self._read_time(),
        }

    def _time_ago(self) -> str:
        if not self.fetched_at:
            return "recently"
        delta = datetime.utcnow() - self.fetched_at
        hours = int(delta.total_seconds() / 3600)
        if hours < 1:
            return "just now"
        if hours == 1:
            return "1h ago"
        if hours < 24:
            return f"{hours}h ago"
        return f"{delta.days}d ago"

    def _read_time(self) -> str:
        if not self.body:
            return "3 min read"
        words = len(self.body.split())
        minutes = max(1, round(words / 200))
        return f"{minutes} min read"


class Subscriber(Base):
    __tablename__ = "subscribers"

    id            = Column(Integer, primary_key=True, index=True)
    email         = Column(String(256), nullable=False, unique=True, index=True)
    frequency     = Column(SAEnum(SubscriberFrequency), default=SubscriberFrequency.daily)
    status        = Column(SAEnum(SubscriberStatus), default=SubscriberStatus.active)
    subscribed_at = Column(DateTime, default=datetime.utcnow)
    unsubscribed_at = Column(DateTime, nullable=True)

    def to_dict(self):
        return {
            "id":        self.id,
            "email":     self.email,
            "frequency": self.frequency.value,
            "status":    self.status.value,
            "joined":    self.subscribed_at.strftime("%b %d, %Y") if self.subscribed_at else "",
        }


class Edition(Base):
    __tablename__ = "editions"

    id            = Column(Integer, primary_key=True, index=True)
    edition_number = Column(Integer, nullable=False, unique=True)
    subject       = Column(String(512), nullable=False)
    intro         = Column(Text, nullable=True)
    status        = Column(SAEnum(EditionStatus), default=EditionStatus.draft)
    recipients    = Column(Integer, default=0)
    opens         = Column(Integer, default=0)
    clicks        = Column(Integer, default=0)
    created_at    = Column(DateTime, default=datetime.utcnow)
    sent_at       = Column(DateTime, nullable=True)

    items = relationship("EditionItem", back_populates="edition", order_by="EditionItem.position")

    @property
    def open_rate(self) -> float:
        if not self.recipients:
            return 0.0
        return round((self.opens / self.recipients) * 100, 1)

    def to_dict(self):
        return {
            "id":             self.id,
            "edition_number": self.edition_number,
            "subject":        self.subject,
            "intro":          self.intro,
            "status":         self.status.value,
            "recipients":     self.recipients,
            "open_rate":      self.open_rate,
            "sent_at":        self.sent_at.isoformat() if self.sent_at else None,
            "created_at":     self.created_at.isoformat() if self.created_at else None,
        }


class EditionItem(Base):
    __tablename__ = "edition_items"

    id         = Column(Integer, primary_key=True, index=True)
    edition_id = Column(Integer, ForeignKey("editions.id"))
    article_id = Column(Integer, ForeignKey("articles.id"))
    position   = Column(Integer, default=0)

    edition = relationship("Edition", back_populates="items")
    article = relationship("Article", back_populates="edition_items")
