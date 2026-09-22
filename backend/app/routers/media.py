from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File

from ..media_store import (
    ALLOWED_EXT, MAX_UPLOAD_BYTES, MEDIA_DIR, list_user_media, save,
)
from ..security import get_current_user

router = APIRouter(prefix="/api/media", tags=["media"])

# main.py serves /media from this folder and imports this name.
__all__ = ["router", "MEDIA_DIR", "ALLOWED_EXT"]


@router.get("")
def list_media(user=Depends(get_current_user)):
    """Media library — the dashboard calls this on the Content screen."""
    return list_user_media(user.id)


@router.post("")
async def upload_media(file: UploadFile = File(...), user=Depends(get_current_user)):
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(400, f"File type {ext or '(none)'} not allowed. "
                                 f"Use {'/'.join(sorted(ALLOWED_EXT))}")
    content = await file.read()
    if not content:
        raise HTTPException(400, "Uploaded file is empty")
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(400, "File too large, max 50MB")

    rel, url = save(user.id, file.filename, content)
    return {"url": url, "filename": rel.split("/")[-1], "path": rel,
            "size": len(content)}
