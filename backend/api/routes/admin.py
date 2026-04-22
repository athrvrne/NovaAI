"""
Admin Auth Routes
POST /api/admin/login   — returns JWT token
GET  /api/admin/status  — pipeline status
"""

from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from datetime import datetime, timedelta
import jwt

from config import settings

router  = APIRouter()
bearer  = HTTPBearer(auto_error=False)


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type:   str = "bearer"


def create_token(username: str) -> str:
    payload = {
        "sub": username,
        "exp": datetime.utcnow() + timedelta(minutes=settings.jwt_expire_minutes),
        "iat": datetime.utcnow(),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def require_admin(credentials: HTTPAuthorizationCredentials = Depends(bearer)):
    """FastAPI dependency — validates admin JWT."""
    if not credentials:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = jwt.decode(
            credentials.credentials,
            settings.jwt_secret,
            algorithms=["HS256"],
        )
        return payload["sub"]
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


@router.post("/login", response_model=LoginResponse)
async def login(req: LoginRequest):
    if req.username != settings.admin_username or req.password != settings.admin_password:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_token(req.username)
    return LoginResponse(access_token=token)


@router.get("/status", dependencies=[Depends(require_admin)])
async def pipeline_status():
    """Admin: current pipeline run status and log."""
    from agents.pipeline import get_pipeline_status
    return get_pipeline_status()


@router.post("/pipeline/run", dependencies=[Depends(require_admin)])
async def trigger_pipeline():
    """Admin: manually trigger the agent pipeline."""
    import asyncio
    from agents.pipeline import run_pipeline, pipeline_running
    if pipeline_running:
        raise HTTPException(status_code=409, detail="Pipeline already running")
    asyncio.create_task(run_pipeline())
    return {"status": "triggered"}
