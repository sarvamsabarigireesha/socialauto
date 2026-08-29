"""FastAPI entrypoint.

Run locally:  uvicorn app.main:app --reload --port 8000
In mock mode (default) the app seeds demo data so the dashboard is alive
on first open — no API keys needed.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .database import Base, engine, SessionLocal
from .models import Account, Post, PostStatus, Platform, User
from .security import hash_password
from .routers import auth as auth_router, oauth as oauth_router, webhooks as webhooks_router
from .routers import accounts, posts, comments, analytics, cron, media, ai as ai_router, ideas as ideas_router, community, templates
from .routers.media import MEDIA_DIR

app = FastAPI(title="SocialAuto — free-tier social media automation", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

app.include_router(auth_router.router)
app.include_router(oauth_router.router)
app.include_router(webhooks_router.router)
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

app.mount("/media", StaticFiles(directory=str(MEDIA_DIR)), name="media")


@app.on_event("startup")
async def on_startup():
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        _run_migrations(db)
        demo_user = _ensure_demo_user(db)
    if settings.MOCK_MODE:
        await _seed_demo_data(demo_user)


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
        if "posts" in cols and "post_type" not in cols["posts"]:
            conn.execute(text("ALTER TABLE posts ADD COLUMN post_type VARCHAR(12) NOT NULL DEFAULT 'feed'"))

    # Postgres: add new ENUM values that create_all won't add on existing DBs.
    if engine.dialect.name == "postgresql":
        wanted = ["youtube", "threads", "moj", "sharechat"]
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

        now = datetime.now(timezone.utc)
        pub_captions = [
            "Best biryani in Hyderabad? Drop your pick 🍗 #Hyderabad #Biryani",
            "New menu drop this Friday! Save the date 🎉",
        ]
        for caption in pub_captions:
            p = Post(user_id=uid, account_id=accs[0].id, caption=caption,
                     scheduled_at=now - timedelta(hours=2),
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
                        status=PostStatus.scheduled))
            db.add(Post(user_id=uid, account_id=accs[1].id, caption=caption, scheduled_at=dt,
                        status=PostStatus.scheduled))
        db.commit()

        await eng.sync_metrics(db, uid)
        await eng.sync_comments(db, uid)
    finally:
        db.close()


@app.get("/api/health")
def health():
    return {"ok": True, "mock_mode": settings.MOCK_MODE}


# ---- serve the dashboard (static) ----
FRONTEND = Path(__file__).resolve().parent.parent.parent / "frontend"
if FRONTEND.exists():
    app.mount("/static", StaticFiles(directory=FRONTEND), name="static")

    @app.get("/")
    def index():
        return FileResponse(FRONTEND / "index.html")
