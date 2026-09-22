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

    # Shared secret GitHub Actions / cron uses to call the protected publish endpoint
    CRON_SECRET: str = os.getenv("CRON_SECRET", "dev-cron-secret-change-me")

    # YouTube: the Data API has no "publish from URL" — an upload means POSTing
    # the actual video bytes. Opt in explicitly (default off = manual step),
    # and keep uploads private unless you really want them public.
    YOUTUBE_AUTO_UPLOAD: bool = os.getenv("YOUTUBE_AUTO_UPLOAD", "false").lower() == "true"
    YOUTUBE_PRIVACY_STATUS: str = os.getenv("YOUTUBE_PRIVACY_STATUS", "private")


settings = Settings()
