from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File

from ..media_store import (
    ALLOWED_EXT, MAX_UPLOAD_BYTES, MEDIA_DIR, list_user_media, new_filename,
    rel_path, size_error, url_for, user_dir,
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
    """Store an upload.

    Written in chunks rather than `await file.read()` so a phone-sized video
    doesn't have to fit in memory (free instances have ~512MB). Oversize files
    get a message telling the user what to do instead of a bare 400.
    """
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(400, f"File type {ext or '(none)'} not allowed. "
                                 f"Use {'/'.join(sorted(ALLOWED_EXT))}")

    name = new_filename(file.filename)
    dest = user_dir(user.id) / name
    written = 0
    try:
        with dest.open("wb") as out:
            while True:
                chunk = await file.read(1 << 20)  # 1MB at a time
                if not chunk:
                    break
                written += len(chunk)
                if written > MAX_UPLOAD_BYTES:
                    out.close()
                    dest.unlink(missing_ok=True)
                    raise HTTPException(400, size_error(written, file.filename))
                out.write(chunk)
    except HTTPException:
        raise
    except Exception as exc:
        dest.unlink(missing_ok=True)
        raise HTTPException(400, "Upload failed while writing the file") from exc

    if written == 0:
        dest.unlink(missing_ok=True)
        raise HTTPException(400, "Uploaded file is empty")

    rel = rel_path(user.id, name)
    return {"url": url_for(rel), "filename": name, "path": rel, "size": written}
