"""Central configuration. All secrets come from environment variables
plus an optional on-disk overlay written by the in-app Meta setup wizard
(DATA_DIR/meta_app.json).

MOCK_MODE=true (default) -> no real API calls, everything is simulated.
Set MOCK_MODE=false (or uncheck it in Channels → Meta App setup) and
provide App ID + Secret to post for real.
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("DATA_DIR", BASE_DIR / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)


class Settings:
    DATABASE_URL: str = os.getenv("DATABASE_URL", f"sqlite:///{DATA_DIR / 'app.db'}")

    # Google / YouTube (Google Cloud free tier — YouTube Data API v3)
    GOOGLE_CLIENT_ID: str = os.getenv("GOOGLE_CLIENT_ID", "")
    GOOGLE_CLIENT_SECRET: str = os.getenv("GOOGLE_CLIENT_SECRET", "")

    # AI assistant (Google Gemini free tier — optional; app works without it)
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")

    # Auto-comment behaviour
    AUTO_COMMENT_ENABLED: bool = os.getenv("AUTO_COMMENT_ENABLED", "true").lower() == "true"
    # Only ingest / keep comments from the last N days. Older history is never
    # stored and existing rows are pruned on each sync (Community inbox stays current).
    COMMENT_SYNC_WINDOW_DAYS: int = int(os.getenv("COMMENT_SYNC_WINDOW_DAYS", "7"))
    # Auto-reply only to comments on posts published in this many hours.
    COMMENT_WATCH_WINDOW_HOURS: int = int(os.getenv("COMMENT_WATCH_WINDOW_HOURS", "24"))

    # Shared secret GitHub Actions / cron uses to call the protected publish endpoint
    CRON_SECRET: str = os.getenv("CRON_SECRET", "dev-cron-secret-change-me")

    # ---- live Meta overlay (env + wizard JSON) ----
    @property
    def MOCK_MODE(self) -> bool:
        from . import meta_store
        return meta_store.mock_mode()

    @property
    def META_APP_ID(self) -> str:
        from . import meta_store
        return meta_store.meta_app_id()

    @property
    def META_APP_SECRET(self) -> str:
        from . import meta_store
        return meta_store.meta_app_secret()

    @property
    def META_GRAPH_VERSION(self) -> str:
        from . import meta_store
        return meta_store.meta_graph_version()

    @property
    def META_VERIFY_TOKEN(self) -> str:
        from . import meta_store
        return meta_store.meta_verify_token()

    @property
    def APP_PUBLIC_URL(self) -> str:
        from . import meta_store
        return meta_store.app_public_url()


settings = Settings()
