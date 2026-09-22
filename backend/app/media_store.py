"""Media storage shared by the upload router, the /media server and publishers.

Why this module exists
----------------------
Uploaded files are the one thing the app needs a *public, stable* URL for:
Instagram does not accept an upload from us, it fetches the file itself. Two
things broke that in production:

1. Render's free disk is **ephemeral** — every deploy or restart wipes
   `DATA_DIR`, so a URL that worked at upload time 404s minutes later, and Meta's
   crawler logs the failure (and the post fails).
2. Old rows in the database point at `/media/u<id>/<file>` while new code wrote
   flat `/media/<file>`, so lookups missed.

So the path layout is fixed here (per user, `u<id>/`), lookups fall back to the
basename anywhere under the media root (so legacy URLs keep resolving), and
`missing_local_media()` lets a publisher fail fast with a clear message instead
of handing Meta a dead URL.
"""
import uuid
from pathlib import Path

from .config import DATA_DIR, settings

ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".webp", ".mp4", ".mov", ".m4v"}
# Phone videos are routinely 100-400MB. We stream uploads straight to disk so a
# large file cannot blow the 512MB RAM of a free instance, but the platform
# still has to fetch the file over this host's egress, so keep a sane ceiling.
MAX_UPLOAD_BYTES = 100 * 1024 * 1024

MEDIA_URL_PREFIX = "/media"
MEDIA_DIR = DATA_DIR / "media"
MEDIA_DIR.mkdir(parents=True, exist_ok=True)

# Photos (and small clips) are also stored in Postgres so a Render redeploy
# cannot 404 Instagram. Bigger videos stay disk-only — Neon free is ~0.5GB.
DB_KEEP_BYTES = 12 * 1024 * 1024

# NOTE: deliberately no "any host containing /media/" regex here. Any host can
# have a /media/ path (https://my-cdn.com/media/pic.jpg), and treating those as
# ours made the publisher refuse perfectly valid external URLs.


def user_dir(user_id: int) -> Path:
    """Per-user upload folder — keeps one workspace's files out of another's."""
    d = MEDIA_DIR / f"u{user_id}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def url_for(rel_path: str) -> str:
    """Public URL for a stored file. Absolute when APP_PUBLIC_URL is set.

    Relative URLs are what the composer stores, and the publisher absolutises
    them at publish time — but a *relative* media URL can never satisfy
    Instagram, so APP_PUBLIC_URL should be set in production.
    """
    rel = str(rel_path).lstrip("/")
    base = (settings.APP_PUBLIC_URL or "").rstrip("/")
    return f"{base}{MEDIA_URL_PREFIX}/{rel}" if base else f"{MEDIA_URL_PREFIX}/{rel}"


def rel_path(user_id: int, filename: str) -> str:
    return f"u{user_id}/{filename}"


def new_filename(original: str) -> str:
    return f"{uuid.uuid4().hex[:12]}{Path(original).suffix.lower()}"


def save(user_id: int, original_name: str, content: bytes) -> tuple[str, str]:
    """Write already-read bytes and return `(rel_path, public_url)`."""
    name = new_filename(original_name)
    (user_dir(user_id) / name).write_bytes(content)
    rel = rel_path(user_id, name)
    persist_blob(user_id, rel, name, content)
    return rel, url_for(rel)


def size_error(size: int, name: str = "") -> str:
    """Message for an upload that is too big — says what to do about it."""
    mb = size / (1024 * 1024)
    limit = MAX_UPLOAD_BYTES / (1024 * 1024)
    return (f"{name or 'file'} is {mb:.0f}MB and the upload limit is "
            f"{limit:.0f}MB. Compress it, or paste a public https:// link "
            f"instead (videos hosted on Drive/Cloudinary work fine and skip "
            f"this host entirely).")


def persist_blob(user_id: int, rel: str, filename: str, content: bytes,
                 content_type: str = "") -> None:
    """Copy a small upload into Postgres. No-op if it's too big or DB is down."""
    if not content or len(content) > DB_KEEP_BYTES:
        return
    from .database import SessionLocal
    from .models import MediaBlob
    rel = (rel or "").strip().lstrip("/")
    db = SessionLocal()
    try:
        row = db.query(MediaBlob).filter(MediaBlob.rel == rel).first()
        if row:
            row.data = content
            row.size = len(content)
            row.content_type = content_type or row.content_type
        else:
            db.add(MediaBlob(
                user_id=user_id, rel=rel, filename=filename or Path(rel).name,
                content_type=content_type or "application/octet-stream",
                size=len(content), data=content,
            ))
        db.commit()
    except Exception as exc:
        db.rollback()
        print(f"media blob persist failed: {exc}", flush=True)
    finally:
        db.close()


def hydrate_from_db(rel: str) -> Path | None:
    """Write a blob back to disk after a wipe. None if we never stored it."""
    from .database import SessionLocal
    from .models import MediaBlob
    rel = (rel or "").strip().lstrip("/")
    if not rel:
        return None
    db = SessionLocal()
    try:
        row = db.query(MediaBlob).filter(MediaBlob.rel == rel).first()
        if row is None:
            name = Path(rel).name
            if name:
                row = (db.query(MediaBlob)
                       .filter(MediaBlob.filename == name)
                       .order_by(MediaBlob.id.desc()).first())
        if row is None:
            return None
        dest = MEDIA_DIR / row.rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not dest.is_file() or dest.stat().st_size != (row.size or 0):
            dest.write_bytes(bytes(row.data))
        return dest if dest.is_file() else None
    except Exception as exc:
        print(f"media blob hydrate failed: {exc}", flush=True)
        return None
    finally:
        db.close()


def resolve(rel: str) -> Path | None:
    """Locate a stored file from a URL path, or None.

    Order: exact path (with traversal blocked) → basename at the root →
    basename anywhere under the root (legacy `/media/u3/x.mp4` rows).
    """
    rel = (rel or "").strip().lstrip("/")
    if not rel:
        return None
    root = MEDIA_DIR.resolve()
    try:
        candidate = (MEDIA_DIR / rel).resolve()
    except (OSError, ValueError):
        return None
    if candidate == root or root in candidate.parents:
        if candidate.is_file():
            return candidate

    name = Path(rel).name
    if not name or name in (".", ".."):
        return None
    direct = root / name
    if direct.is_file():
        return direct
    for found in root.rglob(name):
        if found.is_file():
            return found
    return hydrate_from_db(rel)


def missing_local_media(url: str) -> str:
    """Return a human message if `url` is one of ours but the file is gone.

    Publishing hands the URL to the platform, which fetches it a moment later.
    If the file was wiped by a redeploy we would get an opaque Meta error, so
    this turns it into something actionable. Returns "" when nothing is wrong.
    """
    if not url:
        return ""
    base = (settings.APP_PUBLIC_URL or "").rstrip("/")
    if url.startswith(("http://", "https://")):
        if not base:
            # An absolute URL with no configured public host: we cannot tell
            # whether we serve it, and guessing "missing" would block a good
            # publish. Hand it to the platform.
            return ""
        prefix = f"{base}{MEDIA_URL_PREFIX}/"
        if not url.startswith(prefix):
            return ""  # some other host — none of our business
        rel = url[len(prefix):]
    elif url.startswith(MEDIA_URL_PREFIX):
        rel = url[len(MEDIA_URL_PREFIX):]
    else:
        return ""
    if resolve(rel):
        return ""
    if not base:
        return ("media is stored at a relative path and APP_PUBLIC_URL is not set, "
                "so the platform has nothing it can fetch. Set APP_PUBLIC_URL to "
                "this app's public https URL.")
    return (f"the media file {MEDIA_URL_PREFIX}/{rel.lstrip('/')} is missing on this "
            f"server (it was uploaded before photos were saved in the database). "
            f"Open the post → ✏️ Re-attach the image → Retry. New uploads survive deploys.")


def list_user_media(user_id: int) -> list[dict]:
    """Newest-first listing for the dashboard's Media library."""
    rows = []
    seen = set()
    d = MEDIA_DIR / f"u{user_id}"
    if d.is_dir():
        for p in d.iterdir():
            if not p.is_file():
                continue
            st = p.stat()
            seen.add(p.name)
            rows.append({
                "name": p.name,
                "filename": p.name,
                "url": url_for(rel_path(user_id, p.name)),
                "size": st.st_size,
                "uploaded_at": st.st_mtime,
            })
    try:
        from .database import SessionLocal
        from .models import MediaBlob
        db = SessionLocal()
        try:
            for rel, filename, size, created in (
                db.query(MediaBlob.rel, MediaBlob.filename, MediaBlob.size,
                         MediaBlob.created_at)
                .filter(MediaBlob.user_id == user_id)
                .all()
            ):
                if filename in seen:
                    continue
                seen.add(filename)
                ts = created.timestamp() if created and hasattr(created, "timestamp") else 0
                rows.append({
                    "name": filename,
                    "filename": filename,
                    "url": url_for(rel),
                    "size": size or 0,
                    "uploaded_at": ts,
                })
        finally:
            db.close()
    except Exception as exc:
        print(f"list_user_media db: {exc}", flush=True)
    rows.sort(key=lambda r: r["uploaded_at"], reverse=True)
    return rows
