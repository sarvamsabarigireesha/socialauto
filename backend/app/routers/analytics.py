import csv
import io

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User
from ..security import get_current_user
from ..services import engine

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


@router.get("")
def summary(days: int | None = Query(default=None, ge=1, le=365),
            db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return engine.analytics_summary(db, user.id, days=days)


@router.post("/sync")
async def sync(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Refresh YOUR posts' metrics snapshots from the platforms."""
    return await engine.sync_metrics(db, user.id)


@router.get("/export.csv")
def export_csv(days: int | None = Query(default=None, ge=1, le=365),
               db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Buffer-style: download analytics as CSV."""
    d = engine.analytics_summary(db, user.id, days=days)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["post_id", "platform", "account", "caption", "published_at",
                "likes", "comments", "shares", "impressions", "reach"])
    for p in d["per_post"]:
        w.writerow([p["post_id"], p["platform"], p["account"], p["caption"],
                    p.get("published_at") or "", p["likes"], p["comments"],
                    p["shares"], p["impressions"], p["reach"]])
    buf.seek(0)
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition":
                                      "attachment; filename=socialauto_analytics.csv"})
