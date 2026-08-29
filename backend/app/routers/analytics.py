from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..services import engine

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


@router.get("")
def summary(db: Session = Depends(get_db)):
    return engine.analytics_summary(db)


@router.post("/sync")
async def sync(db: Session = Depends(get_db)):
    """Refresh metrics snapshots from the platforms."""
    return await engine.sync_metrics(db)
