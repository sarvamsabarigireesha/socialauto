"""Real-time webhooks.

Meta (Instagram/Facebook):
  GET  /api/webhooks/meta  -> verification challenge (hub.challenge)
  POST /api/webhooks/meta  -> comment events → instant auto-reply

Subscribe in App Dashboard → Webhooks → Page + Instagram → fields: comments.
After OAuth we also POST /{page-id}/subscribed_apps so events start flowing.
"""
import hashlib
import hmac
import json

from fastapi import APIRouter, Request, HTTPException, Response

from ..config import settings
from ..database import SessionLocal
from ..models import Post, Comment
from ..services import platforms, autocomment

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])


def _valid_signature(raw: bytes, header: str) -> bool:
    secret = settings.META_APP_SECRET
    if not secret or not header:
        # No secret yet — accept in local/dev so Verify still works.
        return not secret
    try:
        algo, given = header.split("=", 1)
    except ValueError:
        return False
    if algo != "sha256":
        return False
    expected = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, given)


@router.get("/meta")
def verify_meta(request: Request):
    q = request.query_params
    mode = q.get("hub.mode")
    token = q.get("hub.verify_token")
    challenge = q.get("hub.challenge")
    if mode == "subscribe" and token == settings.META_VERIFY_TOKEN:
        # Meta requires the raw challenge string back.
        return Response(content=challenge or "", media_type="text/plain")
    raise HTTPException(403, "Verification failed — check META_VERIFY_TOKEN")


@router.post("/meta")
async def meta_event(request: Request):
    raw = await request.body()
    sig = request.headers.get("X-Hub-Signature-256") or request.headers.get("X-Hub-Signature")
    if settings.META_APP_SECRET and not _valid_signature(raw, sig or ""):
        raise HTTPException(403, "Invalid webhook signature")

    try:
        body = await request.json() if not raw else __import__("json").loads(raw.decode() or "{}")
    except Exception:
        return {"received": True, "replies": 0}

    db = SessionLocal()
    try:
        replies = 0
        for entry in body.get("entry", []):
            changes = entry.get("changes") or []
            # Messenger-style messaging is ignored; we only handle feed/comments.
            for change in changes:
                val = change.get("value") or {}
                field = change.get("field") or ""
                item = val.get("item") or ""
                if field not in ("comments", "feed", "mentions") and item != "comment":
                    continue
                if field == "feed" and item and item != "comment":
                    continue

                comment_id = str(val.get("comment_id") or val.get("id") or "")
                media = val.get("media") or {}
                post_igid = str(
                    val.get("post_id")
                    or val.get("media_id")
                    or media.get("id")
                    or ""
                )
                text = val.get("message") or val.get("text") or ""
                frm = val.get("from") or {}
                author = frm.get("username") or frm.get("name") or "someone"
                if not comment_id:
                    continue

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
                            author=author,
                            author_avatar=(author[:1].upper() if author else "?"),
                            text=text)
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
