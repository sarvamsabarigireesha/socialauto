from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User
from ..security import get_current_user
from ..services import engine

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


@router.get("")
def summary(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return engine.analytics_summary(db, user.id)


@router.post("/sync")
async def sync(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Refresh YOUR posts' metrics snapshots from the platforms."""
    return await engine.sync_metrics(db, user.id)
