"""Buffer-style link shortener (self-hosted, no external service).

POST /api/links          {url, custom?}  ->  {short_url: '/l/Ab3xYz'}
GET  /l/{code}           ->  302 redirect to long_url (counts a click)
GET  /api/links/stats    ->  user's links with click counts
"""
import secrets

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import ShortLink, User
from ..security import get_current_user

router = APIRouter(tags=["links"])

CODE_ALPHABET = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
BAD_DOMAINS = ("localhost", "127.0.0.1", "0.0.0.0", "::1")


class ShortenIn(BaseModel):
    url: str
    custom: str = ""  # optional custom code


def _normalize(url: str) -> str:
    u = url.strip()
    if not u:
        raise HTTPException(400, "URL is empty")
    if not u.lower().startswith(("http://", "https://")):
        u = "https://" + u
    host = u.split("/")[2].split(":")[0].lower() if "://" in u else ""
    if host in BAD_DOMAINS:
        raise HTTPException(400, "cannot shorten local addresses")
    if len(u) > 2000:
        raise HTTPException(400, "URL too long")
    return u


def _gen_code(n: int = 6) -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(n))


@router.post("/api/links", status_code=201)
def shorten(data: ShortenIn, db: Session = Depends(get_db),
            user: User = Depends(get_current_user)):
    long_url = _normalize(data.url)
    code = (data.custom or "").strip()[:12] or _gen_code()
    if not code or not all(c in CODE_ALPHABET for c in code):
        raise HTTPException(400, "custom code may only contain letters and digits")
    if db.query(ShortLink).filter(ShortLink.code == code).first():
        raise HTTPException(409, "that short code is already taken")
    link = ShortLink(user_id=user.id, code=code, long_url=long_url)
    db.add(link)
    db.commit()
    db.refresh(link)
    return {"code": link.code, "long_url": link.long_url,
            "short_url": f"/l/{link.code}", "clicks": 0}


@router.get("/api/links/stats")
def link_stats(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = (db.query(ShortLink).filter(ShortLink.user_id == user.id)
            .order_by(ShortLink.created_at.desc()).limit(100).all())
    return [{"code": r.code, "long_url": r.long_url, "clicks": r.clicks,
             "short_url": f"/l/{r.code}", "created_at": r.created_at} for r in rows]


@router.get("/api/links/expand/{code}")
def expand(code: str, db: Session = Depends(get_db),
           user: User = Depends(get_current_user)):
    """Composer uses this to restore the original URL (no click counted)."""
    link = db.query(ShortLink).filter(ShortLink.code == code,
                                      ShortLink.user_id == user.id).first()
    if not link:
        raise HTTPException(404, "short link not found")
    return {"code": link.code, "long_url": link.long_url, "clicks": link.clicks}
