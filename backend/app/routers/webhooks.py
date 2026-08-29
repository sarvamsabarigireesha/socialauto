"""Real-time webhooks.

Meta (Instagram/Facebook):
  GET  /api/webhooks/meta  -> verification challenge (hub.challenge)
  POST /api/webhooks/meta  -> comment events → instant auto-reply
Subscribe in App Dashboard → Webhooks → Page/Instagram → fields: comments.
"""
from fastapi import APIRouter, Request, HTTPException

from ..config import settings
from ..database import SessionLocal
from ..models import Account, Post, Comment, Platform
from ..services import platforms, autocomment

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])


@router.get("/meta")
def verify_meta(request: Request):
    q = request.query_params
    mode = q.get("hub.mode")
    token = q.get("hub.verify_token")
    challenge = q.get("hub.challenge")
    if mode == "subscribe" and token == settings.META_VERIFY_TOKEN:
        return int(challenge) if (challenge or "").isdigit() else (challenge or "")
    raise HTTPException(403, "Verification failed")


@router.post("/meta")
async def meta_event(request: Request):
    body = await request.json()
    db = SessionLocal()
    try:
        replies = 0
        for entry in body.get("entry", []):
            for change in entry.get("changes", []):
                val = change.get("value", {})
                if change.get("field") != "comments":
                    continue
                # payload: {id: comment_id, post_id, from{name}, message}
                comment_id = val.get("comment_id") or val.get("id", "")
                post_igid = val.get("post_id") or val.get("media_id") or ""
                text = val.get("message") or val.get("text") or ""
                author = (val.get("from") or {}).get("name", "someone")

                post = (db.query(Post)
                        .filter(Post.platform_post_id == post_igid).first()
                        if post_igid else None)
                if not post:
                    continue
                exists = (db.query(Comment)
                          .filter(Comment.external_comment_id == comment_id).first())
                if exists:
                    continue
                c = Comment(post_id=post.id, external_comment_id=comment_id,
                            author=author, text=text)
                db.add(c)
                db.commit()
                if settings.AUTO_COMMENT_ENABLED and post.account.auto_comment:
                    reply = autocomment.generate_reply(text, post.account)
                    client = platforms.get_client(post.account.platform)
                    if await client.reply_to_comment(post.account, post.platform_post_id,
                                                     comment_id, reply):
                        c.our_reply = reply
                        c.replied = True
                        replies += 1
                        db.commit()
        return {"received": True, "replies": replies}
    finally:
        db.close()
