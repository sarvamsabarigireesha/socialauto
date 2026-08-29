"""Media library: upload images once, reuse them in posts (Publer-style)."""
import os
import uuid

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session

from ..config import DATA_DIR
from ..database import get_db
from ..models import Post

MEDIA_DIR = DATA_DIR / "media"
MEDIA_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg"}

router = APIRouter(prefix="/api/media", tags=["media"])


def _seed_samples():
    """Drop a few demo SVG images so the library isn't empty on first run."""
    if any(MEDIA_DIR.glob("*")):
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
        (MEDIA_DIR / name).write_text(svg, encoding="utf-8")


_seed_samples()


@router.get("")
def list_media():
    files = []
    for f in sorted(MEDIA_DIR.glob("*"), key=lambda p: p.stat().st_mtime, reverse=True):
        if f.suffix.lower() in ALLOWED:
            files.append({"name": f.name, "url": f"/media/{f.name}", "size": f.stat().st_size})
    return files


@router.post("", status_code=201)
async def upload_media(file: UploadFile = File(...)):
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED:
        raise HTTPException(400, "Only image files (jpg/png/gif/webp/svg) are allowed")
    name = f"{uuid.uuid4().hex[:12]}{ext}"
    content = await file.read()
    if len(content) > 8 * 1024 * 1024:
        raise HTTPException(400, "File too large (max 8MB)")
    (MEDIA_DIR / name).write_bytes(content)
    return {"name": name, "url": f"/media/{name}", "size": len(content)}


@router.delete("/{name}", status_code=204)
def delete_media(name: str, db: Session = Depends(get_db)):
    # prevent path traversal
    safe = os.path.basename(name)
    path = MEDIA_DIR / safe
    if not path.exists():
        raise HTTPException(404, "not found")
    in_use = db.query(Post).filter(Post.media_url.like(f"%{safe}")).first()
    if in_use:
        raise HTTPException(409, "Media is used by a post; delete the post first")
    path.unlink()
