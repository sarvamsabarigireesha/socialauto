from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Comment
from ..schemas import CommentOut, SimulateCommentIn
from ..services import engine

router = APIRouter(prefix="/api/comments", tags=["comments"])


@router.get("", response_model=list[CommentOut])
def list_comments(replied: bool | None = None, db: Session = Depends(get_db)):
    q = db.query(Comment)
    if replied is not None:
        q = q.filter(Comment.replied == replied)
    return q.order_by(Comment.created_at.desc()).limit(200).all()


@router.post("/simulate", response_model=CommentOut, status_code=201)
def simulate(data: SimulateCommentIn, db: Session = Depends(get_db)):
    """Demo: act as a follower leaving a comment; the bot replies instantly."""
    c = engine.simulate_incoming_comment(db, data.post_id, data.author, data.text)
    if not c:
        raise HTTPException(404, "post not found")
    return c


@router.post("/sync")
async def sync(db: Session = Depends(get_db)):
    """Pull new comments from platforms and run auto-replies."""
    return await engine.sync_comments(db)
