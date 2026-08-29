from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from ..models import User
from ..security import get_current_user
from ..services.ai_assistant import suggest
from ..services.growth import growth_report
import os

router = APIRouter(prefix="/api/ai", tags=["ai"])


class SuggestIn(BaseModel):
    caption: str = ""
    media_url: str = ""
    platforms: list[str] = []


@router.post("/suggest")
async def ai_suggest(data: SuggestIn, request: Request,
                     user: User = Depends(get_current_user)):
    base = os.getenv("APP_PUBLIC_URL") or str(request.base_url).rstrip("/")
    return await suggest(data.caption, data.media_url, data.platforms, base)


class GrowthIn(BaseModel):
    title: str = ""
    description: str = ""


@router.post("/growth")
def growth(data: GrowthIn, user: User = Depends(get_current_user)):
    """VidIQ-style title SEO score + tags + monetization checklist."""
    return growth_report(data.title, data.description)
