"""Media library: shared sample images (read-only) + per-user uploads."""
import os
import uuid

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session

from ..config import DATA_DIR
from ..database import get_db
from ..models import Post, User
from ..security import get_current_user

MEDIA_DIR = DATA_DIR / "media"
SAMPLES_DIR = MEDIA_DIR / "samples"
SAMPLES_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg",
           ".mp4", ".mov", ".m4v", ".webm"}  # videos for YouTube/Shorts/Reels

router = APIRouter(prefix="/api/media", tags=["media"])


def _seed_samples():
    """Shared demo images available to every user."""
    if any(SAMPLES_DIR.glob("*")):
        return
    samples = [
        ("sample-biryani.svg", "#ff7a59", "🍛", "Biryani shoot"),
        ("sample-chai.svg", "#8b5e3c", "☕", "Irani chai"),
        ("sample-kitchen.svg", "#2f9e6e", "👨‍🍳", "Behind the scenes"),
        ("sample-offer.svg", "#5b6cff", "🎉", "Festival offer"),
    ]
    for name, color, emoji, label in samples:
        svg = (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="600" height="600">'
            f'<rect width="600" height="600" fill="{color}"/>'
            f'<text x="300" y="270" font-size="150" text-anchor="middle" dominant-baseline="middle">{emoji}</text>'
            f'<text x="300" y="430" font-size="42" fill="#ffffff" text-anchor="middle" '
            f'font-family="sans-serif" font-weight="bold">{label}</text></svg>'
        )
        (SAMPLES_DIR / name).write_text(svg, encoding="utf-8")


_seed_samples()


def _list_dir(d, url_prefix):
    out = []
    for f in sorted(d.glob("*"), key=lambda p: p.stat().st_mtime, reverse=True):
        if f.suffix.lower() in ALLOWED:
            out.append({"name": f.name, "url": f"{url_prefix}/{f.name}",
                        "size": f.stat().st_size})
    return out


@router.get("")
def list_media(user: User = Depends(get_current_user)):
    user_dir = MEDIA_DIR / f"u{user.id}"
    user_dir.mkdir(parents=True, exist_ok=True)
    uploads = _list_dir(user_dir, f"/media/u{user.id}")
    samples = _list_dir(SAMPLES_DIR, "/media/samples")
    return uploads + samples


@router.post("", status_code=201)
async def upload_media(file: UploadFile = File(...),
                       user: User = Depends(get_current_user)):
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED:
        raise HTTPException(400, "Supported: images (jpg/png/gif/webp/svg) and videos (mp4/mov/webm)")
    max_bytes = 100 * 1024 * 1024 if ext in (".mp4",".mov",".m4v",".webm") else 8 * 1024 * 1024
    user_dir = MEDIA_DIR / f"u{user.id}"
    user_dir.mkdir(parents=True, exist_ok=True)
    name = f"{uuid.uuid4().hex[:12]}{ext}"
    content = await file.read()
    if len(content) > max_bytes:
        raise HTTPException(400, f"File too large (max {max_bytes//(1024*1024)}MB)")
    (user_dir / name).write_bytes(content)
    from ..config import settings
    base = (settings.APP_PUBLIC_URL or "").rstrip("/")
    rel = f"/media/u{user.id}/{name}"
    return {"name": name, "url": f"{base}{rel}" if base else rel,
            "size": len(content)}


@router.delete("/{name}", status_code=204)
def delete_media(name: str, db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    safe = os.path.basename(name)
    path = MEDIA_DIR / f"u{user.id}" / safe
    if not path.exists():
        raise HTTPException(404, "not found (or not your upload)")
    in_use = (db.query(Post).filter(Post.user_id == user.id)
              .filter(Post.media_url.like(f"%{safe}")).first())
    if in_use:
        raise HTTPException(409, "Media is used by a post; delete the post first")
    path.unlink()
