"""
Subscribers API Routes
POST /api/subscribers/subscribe     — public signup
POST /api/subscribers/unsubscribe   — public unsubscribe
GET  /api/subscribers/              — list all (admin)
POST /api/subscribers/              — add manually (admin)
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from datetime import datetime

from models.database import AsyncSession, get_db, Subscriber, SubscriberFrequency, SubscriberStatus
from api.routes.admin import require_admin

router = APIRouter()


class SubscribeRequest(BaseModel):
    email: EmailStr
    frequency: str = "daily"


class UnsubscribeRequest(BaseModel):
    email: EmailStr


# ── Public endpoints ───────────────────────────────────────────────────────────

@router.post("/subscribe")
async def subscribe(req: SubscribeRequest, db: AsyncSession = Depends(get_db)):
    """Public newsletter signup."""
    result = await db.execute(select(Subscriber).where(Subscriber.email == req.email))
    existing = result.scalar_one_or_none()

    if existing:
        if existing.status == SubscriberStatus.paused:
            existing.status = SubscriberStatus.active
            existing.unsubscribed_at = None
            await db.commit()
            return {"status": "reactivated", "email": req.email}
        return {"status": "already_subscribed", "email": req.email}

    freq = SubscriberFrequency.weekly if req.frequency == "weekly" else SubscriberFrequency.daily
    sub = Subscriber(email=req.email, frequency=freq)
    db.add(sub)
    await db.commit()

    return {"status": "subscribed", "email": req.email}


@router.post("/unsubscribe")
async def unsubscribe(req: UnsubscribeRequest, db: AsyncSession = Depends(get_db)):
    """Public unsubscribe."""
    result = await db.execute(select(Subscriber).where(Subscriber.email == req.email))
    sub = result.scalar_one_or_none()

    if not sub:
        raise HTTPException(status_code=404, detail="Email not found")

    sub.status = SubscriberStatus.paused
    sub.unsubscribed_at = datetime.utcnow()
    await db.commit()

    return {"status": "unsubscribed", "email": req.email}


# ── Admin endpoints ────────────────────────────────────────────────────────────

@router.get("/", dependencies=[Depends(require_admin)])
async def list_subscribers(db: AsyncSession = Depends(get_db)):
    """Admin: list all subscribers."""
    result = await db.execute(
        select(Subscriber).order_by(Subscriber.subscribed_at.desc())
    )
    subs = result.scalars().all()
    return {"subscribers": [s.to_dict() for s in subs], "count": len(subs)}


@router.post("/", dependencies=[Depends(require_admin)])
async def add_subscriber(req: SubscribeRequest, db: AsyncSession = Depends(get_db)):
    """Admin: manually add a subscriber."""
    result = await db.execute(select(Subscriber).where(Subscriber.email == req.email))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Email already exists")

    freq = SubscriberFrequency.weekly if req.frequency == "weekly" else SubscriberFrequency.daily
    sub = Subscriber(email=req.email, frequency=freq)
    db.add(sub)
    await db.commit()

    return sub.to_dict()


@router.delete("/{subscriber_id}", dependencies=[Depends(require_admin)])
async def delete_subscriber(subscriber_id: int, db: AsyncSession = Depends(get_db)):
    """Admin: remove a subscriber."""
    result = await db.execute(select(Subscriber).where(Subscriber.id == subscriber_id))
    sub = result.scalar_one_or_none()
    if not sub:
        raise HTTPException(status_code=404, detail="Subscriber not found")
    await db.delete(sub)
    await db.commit()
    return {"status": "deleted"}
