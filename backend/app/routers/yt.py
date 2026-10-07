"""YT Package router — SocialAuto integration.

Add to backend/app/main.py:
    from app.routers import yt
    app.include_router(yt.router)

Endpoints:
    POST /api/yt/check    -> {score, grade, issues[]}        (composer pre-flight)
    POST /api/yt/clean    -> cleaned title/description/tags   (one-click fix)
    POST /api/yt/package  -> everything + schedule, one call (bulk/CSV helper)
    GET  /api/yt/checklist -> the 12 viral-readiness items
    GET  /api/yt/trend     ?event=2026-11-16&lead=21,14

Mock-mode friendly: no tokens, no DB, pure functions.
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from typing import List, Optional

from ..models import User
from ..security import get_current_user
from ..services import ytrules

router = APIRouter(prefix="/api/yt", tags=["yt-package"])


class Package(BaseModel):
    title: str = ""
    description: str = ""
    tags: str = ""
    format: str = Field("short", description="short | long | live | youtube")
    event_date: Optional[str] = Field(None, description="YYYY-MM-DD, optional season anchor")
    lead_days: List[int] = Field(default_factory=list)


@router.post("/check")
def check(pkg: Package, user: User = Depends(get_current_user)):
    return ytrules.analyze(pkg.title, pkg.description, pkg.tags, pkg.format)


@router.post("/clean")
def clean(pkg: Package, user: User = Depends(get_current_user)):
    return ytrules.auto_clean(pkg.title, pkg.description, pkg.tags)


@router.post("/package")
def package(pkg: Package, user: User = Depends(get_current_user)):
    report = ytrules.analyze(pkg.title, pkg.description, pkg.tags, pkg.format)
    cleaned = ytrules.auto_clean(pkg.title, pkg.description, pkg.tags)
    out = {"report": report, "cleaned": cleaned,
            "publishable": report["grade"] != "fix",
            "note": ("Fix required ga unna issues tharwatha publish cheyandi" if report["grade"] == "fix"
                     else "Ready — caption field lo cleaned text paste cheyochu")}
    if pkg.event_date:
        out["schedule"] = ytrules.trend_plan(pkg.event_date, pkg.lead_days)
    return out


@router.get("/checklist")
def checklist(user: User = Depends(get_current_user)):
    return {"items": ytrules.VIRAL_CHECKS, "threshold": 85}


@router.get("/trend")
def trend(event: str, lead: str = "", user: User = Depends(get_current_user)):
    lead_days = [int(x) for x in lead.split(",") if x.strip().isdigit()]
    return ytrules.trend_plan(event, lead_days)
