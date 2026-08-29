"""Central configuration. All secrets come from environment variables.

MOCK_MODE=true (default) -> no real API calls, everything is simulated.
Set MOCK_MODE=false and provide tokens to post for real.
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("DATA_DIR", BASE_DIR / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)


class Settings:
    MOCK_MODE: bool = os.getenv("MOCK_MODE", "true").lower() == "true"
    DATABASE_URL: str = os.getenv("DATABASE_URL", f"sqlite:///{DATA_DIR / 'app.db'}")

    # Meta / Instagram Graph API
    META_APP_ID: str = os.getenv("META_APP_ID", "")
    META_APP_SECRET: str = os.getenv("META_APP_SECRET", "")
    META_GRAPH_VERSION: str = os.getenv("META_GRAPH_VERSION", "v21.0")

    # X (Twitter) API v2
    X_BEARER_TOKEN: str = os.getenv("X_BEARER_TOKEN", "")
    X_API_KEY: str = os.getenv("X_API_KEY", "")
    X_API_SECRET: str = os.getenv("X_API_SECRET", "")
    X_ACCESS_TOKEN: str = os.getenv("X_ACCESS_TOKEN", "")
    X_ACCESS_SECRET: str = os.getenv("X_ACCESS_SECRET", "")

    # LinkedIn
    LINKEDIN_ACCESS_TOKEN: str = os.getenv("LINKEDIN_ACCESS_TOKEN", "")

    # Auto-comment behaviour
    AUTO_COMMENT_ENABLED: bool = os.getenv("AUTO_COMMENT_ENABLED", "true").lower() == "true"
    # How long after publishing a post we start watching for new comments (seconds)
    COMMENT_WATCH_WINDOW_HOURS: int = int(os.getenv("COMMENT_WATCH_WINDOW_HOURS", "24"))

    # Shared secret GitHub Actions / cron uses to call the protected publish endpoint
    CRON_SECRET: str = os.getenv("CRON_SECRET", "dev-cron-secret-change-me")


settings = Settings()
