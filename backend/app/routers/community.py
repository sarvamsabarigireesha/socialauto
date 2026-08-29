"""Community inbox — Buffer-style comment moderation.

Fetches real comments from platforms (sync), shows them grouped by post with
replied/total progress, and supports MANUAL human replies posted via the
official comment-reply APIs (plus auto-reply already running on cron/webhooks).
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Comment, Post, User, PostStatus
from ..security import get_current_user
from ..services import platforms, engine
from sqlalchemy import func

router = APIRouter(prefix="/api/community", tags=["community"])


class ReplyIn(BaseModel):
    text: str


@router.get("/summary")
def summary(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Per-post thread list: channel, caption, media, replied, total, unresolved."""
    posts = (db.query(Post).filter(Post.user_id == user.id)
             .filter(Post.status == PostStatus.published)
             .order_by(Post.published_at.desc()).all())
    threads = []
    total_comments = total_replied = total_unresolved = 0
    for p in posts:
        comments = db.query(Comment).filter(Comment.post_id == p.id).all()
        replied = sum(1 for c in comments if c.replied)
        # a comment needs attention if it has no reply and hasn't been dismissed
        unresolved = sum(1 for c in comments if not c.replied and not c.resolved)
        total_comments += len(comments)
        total_replied += replied
        total_unresolved += unresolved
        threads.append({
            "post_id": p.id,
            "platform": p.account.platform.value,
            "account_name": p.account.display_name,
            "caption": p.caption,
            "media_url": p.media_url,
            "published_at": p.published_at,
            "total": len(comments),
            "replied": replied,
            "unresolved": unresolved,
            "comments": [{
                "id": c.id, "author": c.author, "avatar": c.author_avatar or c.author[:1].upper(),
                "text": c.text, "our_reply": c.our_reply, "reply_type": c.reply_type,
                "replied": c.replied, "resolved": c.resolved,
                "created_at": c.created_at,
            } for c in sorted(comments, key=lambda x: x.created_at)],
        })
    return {
        "threads": threads,
        "totals": {"comments": total_comments, "replied": total_replied,
                   "unresolved": total_unresolved},
    }


@router.post("/sync")
async def pull_latest(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Fetch fresh comments from the real platforms for this user."""
    return await engine.sync_comments(db, user.id)


@router.post("/import/{account_id}")
async def import_channel(account_id: int,
                         db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Import a connected channel's existing videos so their comments appear here."""
    return await engine.import_channel_content(db, user.id, account_id)


@router.post("/import-all")
async def import_all(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Import existing content from EVERY connected account (full auto-sync)."""
    return await engine.auto_import_all(db, user.id)


@router.post("/bootstrap-sync")
async def bootstrap_sync(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Run the full first-login sync: import existing channel content,
    fetch existing comments, run auto-replies, and refresh metrics."""
    return await engine.auto_import_all(db, user.id, run_sync=True, force_all_sync=True)


@router.post("/comments/{comment_id}/reply")
async def manual_reply(comment_id: int, data: ReplyIn,
                       db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    text = data.text.strip()
    if not text:
        raise HTTPException(400, "reply text is empty")
    c = db.get(Comment, comment_id)
    if not c or c.post.user_id != user.id:
        raise HTTPException(404, "comment not found")
    post = db.get(Post, c.post_id)
    client = platforms.get_client(post.account.platform)
    ok = await client.reply_to_comment(post.account, post.platform_post_id,
                                       c.external_comment_id, text)
    c.our_reply = text
    c.reply_type = "manual"
    c.replied = True
    c.resolved = True
    db.commit()
    return {"ok": bool(ok), "reply": text, "note": "" if ok else "saved (will post when channel is live)"}


@router.post("/comments/{comment_id}/resolve")
def resolve(comment_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    c = db.get(Comment, comment_id)
    if not c or c.post.user_id != user.id:
        raise HTTPException(404, "not found")
    c.resolved = not c.resolved
    db.commit()
    return {"resolved": c.resolved}
