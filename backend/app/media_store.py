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
import re
import uuid
from pathlib import Path

from .config import DATA_DIR, settings

ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".webp", ".mp4", ".mov", ".m4v"}
MAX_UPLOAD_BYTES = 50 * 1024 * 1024

MEDIA_URL_PREFIX = "/media"
MEDIA_DIR = DATA_DIR / "media"
MEDIA_DIR.mkdir(parents=True, exist_ok=True)

# matches one of our own absolute media URLs and captures the stored path
_OWN_URL = re.compile(r"^https?://[^/]+/media/(?P<rel>.*)$", re.I)


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
    """Write an upload and return `(rel_path, public_url)`."""
    name = new_filename(original_name)
    (user_dir(user_id) / name).write_bytes(content)
    return rel_path(user_id, name), url_for(rel_path(user_id, name))


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
    return None


def missing_local_media(url: str) -> str:
    """Return a human message if `url` is one of ours but the file is gone.

    Publishing hands the URL to the platform, which fetches it a moment later.
    If the file was wiped by a redeploy we would get an opaque Meta error, so
    this turns it into something actionable. Returns "" when nothing is wrong.
    """
    if not url:
        return ""
    if url.startswith(("http://", "https://")):
        own = _OWN_URL.match(url)
        if not own:
            return ""  # hosted elsewhere — not ours to check
        rel = own.group("rel")
    elif url.startswith(MEDIA_URL_PREFIX):
        rel = url[len(MEDIA_URL_PREFIX):]
    else:
        return ""
    if resolve(rel):
        return ""
    base = (settings.APP_PUBLIC_URL or "").rstrip("/")
    if not base:
        return ("media is stored at a relative path and APP_PUBLIC_URL is not set, "
                "so the platform has nothing it can fetch. Set APP_PUBLIC_URL to "
                "this app's public https URL.")
    return (f"the media file {MEDIA_URL_PREFIX}/{rel.lstrip('/')} is missing on this "
            f"server. Free hosts wipe the disk on every deploy, so uploads do not "
            f"survive a redeploy — re-upload the file, or paste an external https:// "
            f"URL as the media, or mount a persistent disk (see DEPLOY.md).")


def list_user_media(user_id: int) -> list[dict]:
    """Newest-first listing for the dashboard's Media library."""
    d = MEDIA_DIR / f"u{user_id}"
    if not d.is_dir():
        return []
    rows = []
    for p in d.iterdir():
        if not p.is_file():
            continue
        st = p.stat()
        rows.append({
            "name": p.name,
            "filename": p.name,
            "url": url_for(rel_path(user_id, p.name)),
            "size": st.st_size,
            "uploaded_at": st.st_mtime,
        })
    rows.sort(key=lambda r: r["uploaded_at"], reverse=True)
    return rows
