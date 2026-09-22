"""Central configuration. All secrets come from environment variables.

MOCK_MODE=true (default) -> no real API calls, everything is simulated.
Set MOCK_MODE=false and provide tokens to post for real.
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("DATA_DIR", BASE_DIR / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)


def _load_env_file() -> str:
    """Load `.env` (repo root or backend/) into os.environ.

    Real environment variables always win — this only fills in what is not
    already set, so Render/Railway/Docker env config still takes precedence.
    Returns the path that was loaded ("" if there was no .env).
    """
    for candidate in (BASE_DIR.parent / ".env", BASE_DIR / ".env"):
        if not candidate.is_file():
            continue
        try:
            lines = candidate.read_text(encoding="utf-8").splitlines()
        except OSError:
            return ""
        for raw in lines:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            if line.lower().startswith("export "):
                line = line[7:]
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            if value[:1] in ("'", '"'):
                quote = value[0]
                end = value.find(quote, 1)
                value = value[1:end] if end != -1 else value[1:]
            else:
                # `.env.example` ships with trailing notes like
                # "MOCK_MODE=true   # demo mode" — drop those.
                value = value.split(" #", 1)[0].split("\t#", 1)[0].strip()
            if key and key not in os.environ:
                os.environ[key] = value
        return str(candidate)
    return ""


ENV_FILE = _load_env_file()


class Settings:
    MOCK_MODE: bool = os.getenv("MOCK_MODE", "true").lower() == "true"
    DATABASE_URL: str = os.getenv("DATABASE_URL", f"sqlite:///{DATA_DIR / 'app.db'}")

    # Meta / Instagram Graph API
    META_APP_ID: str = os.getenv("META_APP_ID", "")
    META_APP_SECRET: str = os.getenv("META_APP_SECRET", "")
    META_GRAPH_VERSION: str = os.getenv("META_GRAPH_VERSION", "v21.0")

    # Google / YouTube (Google Cloud free tier — YouTube Data API v3)
    GOOGLE_CLIENT_ID: str = os.getenv("GOOGLE_CLIENT_ID", "")
    GOOGLE_CLIENT_SECRET: str = os.getenv("GOOGLE_CLIENT_SECRET", "")

    # AI assistant (Google Gemini free tier — optional; app works without it)
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")

    # Meta webhook verification token (real-time comment events)
    META_VERIFY_TOKEN: str = os.getenv("META_VERIFY_TOKEN", "socialauto-verify-token")

    # Public URL of this app (OAuth redirect base) — set in production
    APP_PUBLIC_URL: str = os.getenv("APP_PUBLIC_URL", "")

    # Auto-comment behaviour
    AUTO_COMMENT_ENABLED: bool = os.getenv("AUTO_COMMENT_ENABLED", "true").lower() == "true"
    # How long after publishing a post we start watching for new comments (seconds)
    COMMENT_WATCH_WINDOW_HOURS: int = int(os.getenv("COMMENT_WATCH_WINDOW_HOURS", "24"))
    # How far back to pull comments at all. The first sync after connecting an
    # account used to drag in months of history: slow, and useless in an inbox
    # you clear daily. Older comments are neither stored nor replied to, and
    # rows that age out are pruned so the inbox stays "recent only".
    COMMENT_SYNC_WINDOW_DAYS: int = int(os.getenv("COMMENT_SYNC_WINDOW_DAYS", "7"))

    # Shared secret GitHub Actions / cron uses to call the protected publish endpoint
    CRON_SECRET: str = os.getenv("CRON_SECRET", "dev-cron-secret-change-me")

    # Raw JWT_SECRET (security.py owns the signing key) - kept here so the
    # startup checks can flag placeholder/weak values.
    JWT_SECRET_RAW: str = os.getenv("JWT_SECRET", "")

    # Optional explicit OAuth callback URL for Meta (Instagram/Facebook/Threads),
    # for when the callback differs from APP_PUBLIC_URL + /api/oauth/callback.
    # Must match the redirect URI registered in the Meta app dashboard exactly.
    META_OAUTH_REDIRECT_URI: str = os.getenv("META_OAUTH_REDIRECT_URI", "")

    # YouTube: the Data API has no "publish from URL" — an upload means POSTing
    # the actual video bytes. Opt in explicitly (default off = manual step),
    # and keep uploads private unless you really want them public.
    YOUTUBE_AUTO_UPLOAD: bool = os.getenv("YOUTUBE_AUTO_UPLOAD", "false").lower() == "true"
    YOUTUBE_PRIVACY_STATUS: str = os.getenv("YOUTUBE_PRIVACY_STATUS", "private")


settings = Settings()


# ---------------------------------------------------------------- validation
# Placeholder text that looks filled-in but isn't. This bit us in production:
# DEPLOY.md shows the *shape* of a Neon URL, it got pasted verbatim, and the app
# died deep inside psycopg2 with `could not translate host name "..."`.
PLACEHOLDER_HINTS = ("...", "change-me", "changeme", "change_me", "put-a-long",
                     "long random string", "your-", "your_", "xxx", "todo",
                     "<", ">", "example.com", "ep-xxxx")


def looks_like_placeholder(value: str) -> bool:
    v = (value or "").strip().lower()
    return bool(v) and any(h in v for h in PLACEHOLDER_HINTS)


def database_url_problem(url: str) -> str:
    """Return a human explanation if DATABASE_URL cannot possibly work."""
    url = (url or "").strip()
    if not url or url.startswith("sqlite"):
        return ""
    if "..." in url:
        return ("it still contains '...', which is the placeholder from the docs, "
                "not your own connection string")
    try:
        from sqlalchemy.engine.url import make_url

        parsed = make_url(url)
    except Exception as exc:
        return f"it is not a valid database URL ({exc})"
    host = parsed.host or ""
    if not host:
        return "it has no host name"
    if "." not in host:
        return f"the host name {host!r} is not a real server address"
    if not parsed.username:
        return "it has no username"
    if "example" in host or host.startswith("ep-xxxx"):
        return f"the host {host!r} is still a documentation example"
    return ""


def secret_problem(value: str, name: str, min_length: int = 16) -> str:
    """Return a message if a secret is missing, guessable, or example text."""
    v = (value or "").strip()
    if not v:
        return f"{name} is empty"
    if looks_like_placeholder(v):
        return f"{name} is still example text ({v[:40]!r}) - anyone can guess it"
    if len(v) < min_length:
        return (f"{name} is only {len(v)} characters - use at least {min_length}: "
                f"python3 -c \"import secrets;print(secrets.token_urlsafe(48))\"")
    return ""


def oauth_redirect_problem() -> str:
    """Warn when the Meta redirect URI and APP_PUBLIC_URL disagree."""
    override = (settings.META_OAUTH_REDIRECT_URI or "").strip()
    if not override:
        return ""
    if not override.startswith("https://"):
        return f"META_OAUTH_REDIRECT_URI must be https (got {override!r})"
    public = (settings.APP_PUBLIC_URL or "").strip().rstrip("/")
    if public and not override.startswith(public):
        return (f"META_OAUTH_REDIRECT_URI ({override}) does not start with "
                f"APP_PUBLIC_URL ({public}) - Meta rejects the connect flow with "
                f"'URL Blocked' unless both are registered on the app")
    return ""


def config_problems() -> list[str]:
    """Everything that will bite in live mode, in one list."""
    out = []
    db = database_url_problem(settings.DATABASE_URL)
    if db:
        out.append(f"DATABASE_URL: {db}")
    if not settings.MOCK_MODE:
        for value, name in ((settings.JWT_SECRET_RAW, "JWT_SECRET"),
                            (settings.CRON_SECRET, "CRON_SECRET")):
            problem = secret_problem(value, name)
            if problem:
                out.append(problem)
        if not settings.APP_PUBLIC_URL:
            out.append("APP_PUBLIC_URL is empty - Instagram cannot fetch your "
                       "media and OAuth redirects point at the wrong host")
        elif not settings.APP_PUBLIC_URL.startswith("https://"):
            out.append("APP_PUBLIC_URL must be https in production")
    oauth = oauth_redirect_problem()
    if oauth:
        out.append(oauth)
    return out
