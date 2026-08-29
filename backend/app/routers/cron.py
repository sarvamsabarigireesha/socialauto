"""Protected endpoints called by GitHub Actions / Cloudflare Worker cron.

Auth: header  X-Cron-Secret: <CRON_SECRET>
GitHub Actions stores CRON_SECRET in its repository secrets.
"""
from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..services import engine

router = APIRouter(prefix="/api/cron", tags=["cron"])

DEV_DEFAULT_SECRET = "dev-cron-secret-change-me"


def _check(secret: str | None):
    if not settings.MOCK_MODE and settings.CRON_SECRET == DEV_DEFAULT_SECRET:
        # Defense in depth: never accept the well-known dev default in production.
        raise HTTPException(503, "CRON_SECRET is still the dev default — "
                                 "set a strong CRON_SECRET environment variable")
    if secret != settings.CRON_SECRET:
        raise HTTPException(401, "invalid cron secret")


@router.post("/tick")
async def tick(x_cron_secret: str | None = Header(default=None),
               db: Session = Depends(get_db)):
    """One cron tick = publish due posts + sync comments/auto-reply + refresh analytics."""
    _check(x_cron_secret)
    imported = await engine.auto_import_all(db)
    published = await engine.publish_due_posts(db)
    comments = await engine.sync_comments(db)
    metrics = await engine.sync_metrics(db)
    return {"ok": True, "imported": imported, "published": published,
            "comments": comments, "metrics": metrics}


@router.post("/publish")
async def publish_only(x_cron_secret: str | None = Header(default=None),
                       db: Session = Depends(get_db)):
    _check(x_cron_secret)
    return await engine.publish_due_posts(db)
