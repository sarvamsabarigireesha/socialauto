from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from ..models import User
from ..security import get_current_user
from ..services.ai_assistant import suggest
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
