from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Comment, Post, User
from ..schemas import CommentOut, SimulateCommentIn
from ..security import get_current_user
from ..services import engine

router = APIRouter(prefix="/api/comments", tags=["comments"])


@router.get("", response_model=list[CommentOut])
def list_comments(replied: bool | None = None, db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    q = (db.query(Comment).join(Post, Comment.post_id == Post.id)
         .filter(Post.user_id == user.id))
    if replied is not None:
        q = q.filter(Comment.replied == replied)
    return q.order_by(Comment.created_at.desc()).limit(200).all()


@router.post("/simulate", response_model=CommentOut, status_code=201)
def simulate(data: SimulateCommentIn, db: Session = Depends(get_db),
             user: User = Depends(get_current_user)):
    """Demo: act as a follower leaving a comment; the bot replies instantly."""
    post = db.get(Post, data.post_id)
    if not post or post.user_id != user.id:
        raise HTTPException(404, "post not found")
    c = engine.simulate_incoming_comment(db, data.post_id, data.author, data.text)
    if not c:
        raise HTTPException(404, "post not found")
    return c


@router.post("/sync")
async def sync(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Pull new comments on YOUR posts and run auto-replies."""
    return await engine.sync_comments(db, user.id)
