"""FastAPI entrypoint.

Run locally:  uvicorn app.main:app --reload --port 8000
In mock mode (default) the app seeds demo data so the dashboard is alive
on first open — no API keys needed.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .database import Base, engine, SessionLocal
from .models import Account, Post, PostStatus, Platform, ShortLink, Tag, User
from .security import hash_password
from .routers import auth as auth_router, oauth as oauth_router, webhooks as webhooks_router
from .routers import accounts, posts, comments, analytics, cron, media, ai as ai_router, ideas as ideas_router, community, templates, tags, links, settings as settings_router
from .routers.media import MEDIA_DIR

app = FastAPI(title="SocialAuto — free-tier social media automation", version="1.9.5")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

app.include_router(auth_router.router)
app.include_router(oauth_router.router)
app.include_router(webhooks_router.router)
app.include_router(settings_router.router)
app.include_router(ai_router.router)
app.include_router(ideas_router.router)
app.include_router(community.router)
app.include_router(templates.router)
app.include_router(accounts.router)
app.include_router(posts.router)
app.include_router(comments.router)
app.include_router(analytics.router)
app.include_router(cron.router)
app.include_router(media.router)
app.include_router(tags.router)
app.include_router(links.router)

# ---- uploaded media -------------------------------------------------------
# Served by a handler rather than StaticFiles so that:
#   * legacy rows pointing at "/media/u3/x.mp4" still resolve (basename fallback)
#   * a missing file returns a *useful* error instead of a bare 404 — Meta's
#     crawler logging a 404 is how a wiped disk silently breaks Instagram posts
#   * HEAD is allowed (Render's health check uses it)
from .media_store import resolve as _resolve_media  # noqa: E402


@app.api_route("/media/{rel_path:path}", methods=["GET", "HEAD"])
def serve_media(rel_path: str):
    found = _resolve_media(rel_path)
    if not found:
        return JSONResponse(
            status_code=404,
            content={"detail": f"media file '{rel_path}' is not on this server. "
                               f"Free hosts wipe the disk on every deploy, so "
                               f"uploads do not survive a redeploy — re-upload the "
                               f"file or use an external https:// URL.",
                     "media_dir": str(MEDIA_DIR)},
        )
    return FileResponse(found, headers={"Cache-Control": "public, max-age=86400"})


# ---- public short-link redirect (Buffer-style /l/abc123) ----
@app.get("/l/{code}")
def redirect_short_link(code: str):
    from fastapi.responses import RedirectResponse
    db = SessionLocal()
    try:
        row = db.query(ShortLink).filter(ShortLink.code == code).first()
        if not row:
            return RedirectResponse(url="/?shortlink=notfound")
        row.clicks += 1
        db.commit()
        return RedirectResponse(url=row.long_url)
    finally:
        db.close()


@app.on_event("startup")
async def on_startup():
    _warn_about_ephemeral_storage()
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        # A migration bug once crashed startup, so the whole deploy failed and
        # the service stayed on the previous version. Optional migrations log
        # loudly instead of preventing boot.
        try:
            _run_migrations(db)
        except Exception as exc:
            print(f"ERROR: migrations failed ({type(exc).__name__}: {exc}) — "
                  f"continuing with the existing schema", flush=True)
        demo_user = _ensure_demo_user(db)
    if settings.MOCK_MODE:
        await _seed_demo_data(demo_user)


def _warn_about_ephemeral_storage():
    """Shout at startup about the things a free host silently gets wrong."""
    from .config import DATA_DIR, config_problems

    for problem in config_problems():
        print(f"WARNING: {problem}", flush=True)

    if engine.dialect.name == "sqlite":
        print(f"WARNING: using SQLite at {settings.DATABASE_URL!r}. On a host with "
              f"an ephemeral disk (Render/Railway free tiers) every deploy wipes "
              f"your users, posts and comments. Set DATABASE_URL to a Postgres "
              f"instance (Neon free tier) to keep data.", flush=True)
    public = settings.APP_PUBLIC_URL or "unset (platforms cannot fetch your media)"
    print(f"INFO: uploaded media is stored in {DATA_DIR / 'media'} "
          f"(APP_PUBLIC_URL={public})", flush=True)


def _media_url_needs_widening(insp, tables) -> bool:
    """True when posts.media_url is still a narrow VARCHAR (Postgres only).

    Kept as its own function because the first version of this check indexed
    `cols["posts"]["media_url"]` — `cols` actually holds *sets of column names*,
    so startup raised `TypeError: 'set' object is not subscriptable` and every
    deploy of 1.9.0 failed to boot. There is a smoke test for it now.
    """
    if "posts" not in tables:
        return False
    try:
        col = next((c for c in insp.get_columns("posts") if c["name"] == "media_url"), None)
    except Exception:
        return False
    if col is None:
        return False
    return "TEXT" not in str(col.get("type") or "").upper()


def _run_migrations(db):
    """Lightweight additive migration for existing DBs (SQLite + Postgres):
    adds new NOT NULL owner columns, new enum values, and back-fills demo owner."""
    from sqlalchemy import text, inspect
    insp = inspect(engine)
    cols = {t: {c["name"] for c in insp.get_columns(t)} for t in insp.get_table_names()}

    # X and LinkedIn were removed from the Platform enum. Any pre-existing rows
    # for those platforms would crash every future query that touches them
    # (SQLAlchemy can't deserialize a DB value that's no longer a Python enum
    # member) — Postgres also can't drop enum values via ALTER TYPE. So we
    # purge those accounts (and their posts/comments/metrics) up front, using
    # raw SQL comparisons that don't go through the Python enum at all.
    if "accounts" in cols:
        with engine.begin() as conn:
            try:
                conn.execute(text("""
                    DELETE FROM metrics WHERE post_id IN (
                        SELECT id FROM posts WHERE account_id IN (
                            SELECT id FROM accounts WHERE platform IN ('x','linkedin')))
                """))
                conn.execute(text("""
                    DELETE FROM comments WHERE post_id IN (
                        SELECT id FROM posts WHERE account_id IN (
                            SELECT id FROM accounts WHERE platform IN ('x','linkedin')))
                """))
                conn.execute(text("""
                    DELETE FROM posts WHERE account_id IN (
                        SELECT id FROM accounts WHERE platform IN ('x','linkedin'))
                """))
                conn.execute(text("DELETE FROM accounts WHERE platform IN ('x','linkedin')"))
            except Exception:
                pass  # tables not created yet on a brand-new DB, or already clean

    with engine.begin() as conn:
        if "accounts" in cols and "user_id" not in cols["accounts"]:
            conn.execute(text("ALTER TABLE accounts ADD COLUMN user_id INTEGER"))
        if "posts" in cols and "user_id" not in cols["posts"]:
            conn.execute(text("ALTER TABLE posts ADD COLUMN user_id INTEGER"))
        if "posts" in cols and "group_id" not in cols["posts"]:
            conn.execute(text("ALTER TABLE posts ADD COLUMN group_id VARCHAR(40) DEFAULT ''"))
        if "posts" in cols and "source" not in cols["posts"]:
            conn.execute(text("ALTER TABLE posts ADD COLUMN source VARCHAR(12) NOT NULL DEFAULT 'scheduled'"))
        if "users" in cols and "timezone" not in cols["users"]:
            conn.execute(text("ALTER TABLE users ADD COLUMN timezone VARCHAR(64) NOT NULL DEFAULT 'Asia/Kolkata'"))
        if "accounts" in cols and "posting_slots" not in cols["accounts"]:
            conn.execute(text("ALTER TABLE accounts ADD COLUMN posting_slots JSON"))
        if "accounts" in cols and "posting_goal" not in cols["accounts"]:
            conn.execute(text("ALTER TABLE accounts ADD COLUMN posting_goal INTEGER NOT NULL DEFAULT 7"))
        # Backfill NULL posting_slots (rows created before the column existed) —
        # otherwise AccountOut serialization 500s on production databases.
        if "accounts" in cols and "posting_slots" in cols["accounts"]:
            if engine.dialect.name == "postgresql":
                conn.execute(text("UPDATE accounts SET posting_slots = '[]'::json WHERE posting_slots IS NULL"))
            else:
                conn.execute(text("UPDATE accounts SET posting_slots = '[]' WHERE posting_slots IS NULL"))
        pg = engine.dialect.name == "postgresql"
        if "comments" in cols and "resolved" not in cols["comments"]:
            conn.execute(text("ALTER TABLE comments ADD COLUMN resolved BOOLEAN NOT NULL DEFAULT false"))
            if pg:
                conn.execute(text("UPDATE comments SET resolved=false"))
        if "comments" in cols and "reply_type" not in cols["comments"]:
            conn.execute(text("ALTER TABLE comments ADD COLUMN reply_type VARCHAR(10) NOT NULL DEFAULT 'auto'"))
        if "comments" in cols and "author_avatar" not in cols["comments"]:
            conn.execute(text("ALTER TABLE comments ADD COLUMN author_avatar VARCHAR(20) NOT NULL DEFAULT ''"))
        if "accounts" in cols and "refresh_token" not in cols["accounts"]:
            conn.execute(text("ALTER TABLE accounts ADD COLUMN refresh_token VARCHAR(500) NOT NULL DEFAULT ''"))
        # posts.media_url was VARCHAR(500) — real CDN URLs are longer and made
        # every import fail. Postgres needs an explicit widening.
        #
        # Only when it is still narrow, and with a lock timeout: ALTER TABLE needs
        # an ACCESS EXCLUSIVE lock on posts, and a single stale transaction is
        # enough to make this statement queue — which then blocks every read and
        # write on posts behind it. Failing fast (and retrying next boot) is far
        # better than wedging the whole app.
        if engine.dialect.name == "postgresql" and _media_url_needs_widening(insp, cols):
            try:
                conn.execute(text("SET lock_timeout = '5s'"))
                conn.execute(text("ALTER TABLE posts ALTER COLUMN media_url TYPE TEXT"))
                print("[migrate] posts.media_url widened to TEXT", flush=True)
            except Exception as exc:
                print(f"[migrate] media_url widening skipped ({type(exc).__name__}); "
                      f"will retry on next start", flush=True)
        if "posts" in cols and "post_type" not in cols["posts"]:
            conn.execute(text("ALTER TABLE posts ADD COLUMN post_type VARCHAR(12) NOT NULL DEFAULT 'feed'"))
        if "users" in cols and "reset_token" not in cols["users"]:
            conn.execute(text("ALTER TABLE users ADD COLUMN reset_token VARCHAR(120) NOT NULL DEFAULT ''"))
        if "users" in cols and "reset_token_expires" not in cols["users"]:
            conn.execute(text("ALTER TABLE users ADD COLUMN reset_token_expires TIMESTAMP"))

    # Postgres: add new ENUM values that create_all won't add on existing DBs.
    if engine.dialect.name == "postgresql":
        wanted = ["youtube", "threads", "moj", "sharechat", "snapchat", "bilibili"]
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            for e in insp.get_enums():
                labels = e.get("labels") or []
                if "instagram" not in labels:
                    continue
                for val in wanted:
                    if val not in labels:
                        try:
                            conn.execute(text(f"ALTER TYPE {e['name']} ADD VALUE '{val}'"))
                        except Exception:
                            pass  # value already added

    demo = db.query(User).filter(User.email == "demo@socialauto.app").first()
    if not demo:
        demo = User(email="demo@socialauto.app", name="Demo User",
                    password_hash=hash_password("demo1234"))
        db.add(demo)
        db.commit()
        db.refresh(demo)

    with engine.begin() as conn:
        conn.execute(text("UPDATE accounts SET user_id=:u WHERE user_id IS NULL"), {"u": demo.id})
        conn.execute(text("UPDATE posts SET user_id=:u WHERE user_id IS NULL"), {"u": demo.id})


def _ensure_demo_user(db) -> User:
    demo = db.query(User).filter(User.email == "demo@socialauto.app").first()
    if not demo:
        demo = User(email="demo@socialauto.app", name="Demo User",
                    password_hash=hash_password("demo1234"))
        db.add(demo)
        db.commit()
        db.refresh(demo)
    return demo


async def _seed_demo_data(demo_user: User):
    from .services import engine as eng
    db = SessionLocal()
    try:
        uid = demo_user.id
        demo = [
            (Platform.instagram, "@hyderabad.foodie", "ig_demo_1001", True, ""),
            (Platform.facebook, "Hyderabad Foodie Page", "fb_demo_2002", True,
             "Thanks for commenting! Check our bio for the full menu 🙌"),
            (Platform.youtube, "Foodie Tube", "yt_demo_5005", True, ""),
        ]
        accs = []
        created = False
        for plat, name, ext, ac, tmpl in demo:
            exists = (db.query(Account)
                      .filter(Account.user_id == uid, Account.external_id == ext).first())
            if exists:
                accs.append(exists)
                continue
            a = Account(user_id=uid, platform=plat, display_name=name, external_id=ext,
                        access_token="MOCK_TOKEN", auto_comment=ac, comment_template=tmpl)
            db.add(a)
            accs.append(a)
            created = True
        db.commit()
        if not created and db.query(Post).filter(Post.user_id == uid).count() > 0:
            return

        # demo tags (Buffer-style) — idempotent per user
        tag_names = {"Food": "#e1306c", "Festive": "#f5a524", "Behind the Scenes": "#22a06b"}
        for tname, tcol in tag_names.items():
            if not db.query(Tag).filter(Tag.user_id == uid, Tag.name == tname).first():
                db.add(Tag(user_id=uid, name=tname, color=tcol))
        db.commit()

        now = datetime.now(timezone.utc)
        pub_captions = [
            "Best biryani in Hyderabad? Drop your pick 🍗 #Hyderabad #Biryani",
            "New menu drop this Friday! Save the date 🎉",
        ]
        for caption in pub_captions:
            p = Post(user_id=uid, account_id=accs[0].id, caption=caption,
                     scheduled_at=now - timedelta(hours=2), source="scheduled",
                     status=PostStatus.published, platform_post_id=f"mock_seed_{caption[:6]}",
                     published_at=now - timedelta(hours=2))
            db.add(p)
        sched = [
            ("Morning chai + osmania biscuit vibes ☕", now + timedelta(hours=2)),
            ("Weekend special: Haleem night 🌙", now + timedelta(hours=6)),
            ("Behind the scenes at our kitchen 👨‍🍳", now + timedelta(days=1, hours=3)),
            ("Poll: Irani chai vs filter coffee? ☕", now + timedelta(days=2)),
        ]
        for caption, dt in sched:
            db.add(Post(user_id=uid, account_id=accs[0].id, caption=caption, scheduled_at=dt,
                        status=PostStatus.scheduled, source="scheduled"))
            db.add(Post(user_id=uid, account_id=accs[1].id, caption=caption, scheduled_at=dt,
                        status=PostStatus.scheduled, source="scheduled"))
        # a few Buffer-style queue posts (drag-to-reorder works on these)
        queue_caps = [
            "Saturday foodie walk — guessing the street? 🚶",
            "Secret menu item reveal 🍔",
        ]
        for i, caption in enumerate(queue_caps):
            db.add(Post(user_id=uid, account_id=accs[0].id, caption=caption,
                        scheduled_at=now + timedelta(hours=4 + i), status=PostStatus.scheduled,
                        source="queue"))
        db.commit()

        await eng.sync_metrics(db, uid)
        await eng.sync_comments(db, uid)
    finally:
        db.close()


@app.api_route("/api/health", methods=["GET", "HEAD"])
def health():
    # `version` doubles as a deploy marker — bump it to verify new code is live.
    from . import meta_store
    return {
        "ok": True,
        "mock_mode": settings.MOCK_MODE,
        "version": "1.9.5",
        "meta_configured": meta_store.meta_configured(),
    }


# ---- serve the dashboard (static) + PWA files at the origin root ----
FRONTEND = Path(__file__).resolve().parent.parent.parent / "frontend"
if FRONTEND.exists():
    app.mount("/static", StaticFiles(directory=FRONTEND), name="static")
    icons_dir = FRONTEND / "icons"
    if icons_dir.exists():
        app.mount("/icons", StaticFiles(directory=str(icons_dir)), name="pwa-icons")

    # Render's health check issues a HEAD request; a GET-only route answers 405,
    # which makes the service look unhealthy (and restarts wipe the disk).
    @app.api_route("/", methods=["GET", "HEAD"])
    def index():
        return FileResponse(FRONTEND / "index.html")

    @app.get("/manifest.webmanifest")
    def pwa_manifest():
        return FileResponse(
            FRONTEND / "manifest.webmanifest",
            media_type="application/manifest+json",
            headers={"Cache-Control": "no-cache"},
        )

    @app.get("/sw.js")
    def pwa_service_worker():
        return FileResponse(
            FRONTEND / "sw.js",
            media_type="application/javascript",
            headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"},
        )

    @app.get("/offline")
    def pwa_offline():
        return FileResponse(FRONTEND / "offline.html")
