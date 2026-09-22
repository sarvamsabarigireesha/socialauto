from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from pathlib import Path
from ..config import settings, DATA_DIR
from ..security import get_current_user
import uuid

router = APIRouter(prefix="/api/media", tags=["media"])
ALLOWED = {".jpg",".jpeg",".png",".webp",".mp4",".mov",".m4v"}

@router.post("")
async def upload_media(file: UploadFile = File(...), user=Depends(get_current_user)):
    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED:
        raise HTTPException(400, f"File type {ext} not allowed. Use jpg/png/mp4")
    
    media_dir = DATA_DIR / "media"
    media_dir.mkdir(parents=True, exist_ok=True)  # FIX: create folder if not exists
    
    fname = f"{uuid.uuid4().hex[:12]}{ext}"
    fpath = media_dir / fname
    content = await file.read()
    if len(content) > 50*1024*1024:  # 50MB limit
        raise HTTPException(400, "File too large, max 50MB")
    fpath.write_bytes(content)
    
    # Return public URL
    base = (settings.APP_PUBLIC_URL or "").rstrip("/")
    return {"url": f"{base}/media/{fname}" if base else f"/media/{fname}", "filename": fname}
