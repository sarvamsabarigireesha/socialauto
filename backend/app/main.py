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
from .models import Account, Post, PostStatus, Platform
from .routers import accounts, posts, comments, analytics, cron, media
from .routers.media import MEDIA_DIR

app = FastAPI(title="SocialAuto — free-tier social media automation", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

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
    if settings.MOCK_MODE:
        await _seed_demo_data()


async def _seed_demo_data():
    from .services import engine as eng
    db = SessionLocal()
    try:
        if db.query(Account).count() > 0:
            return
        demo = [
            (Platform.instagram, "@hyderabad.foodie", "ig_demo_1001", True, ""),
            (Platform.facebook, "Hyderabad Foodie Page", "fb_demo_2002", True,
             "Thanks for commenting! Check our bio for the full menu 🙌"),
            (Platform.x, "@hyd_foodie", "x_demo_3003", True, ""),
            (Platform.linkedin, "Foodie Media", "li_demo_4004", False, ""),
        ]
        accs = []
        for plat, name, ext, ac, tmpl in demo:
            a = Account(platform=plat, display_name=name, external_id=ext,
                        access_token="MOCK_TOKEN", auto_comment=ac, comment_template=tmpl)
            db.add(a)
            accs.append(a)
        db.commit()

        now = datetime.now(timezone.utc)
        # a couple of already-published posts (so analytics/comments have data)
        pub_captions = [
            "Best biryani in Hyderabad? Drop your pick 🍗 #Hyderabad #Biryani",
            "New menu drop this Friday! Save the date 🎉",
        ]
        for caption in pub_captions:
            p = Post(account_id=accs[0].id, caption=caption, scheduled_at=now - timedelta(hours=2),
                     status=PostStatus.published, platform_post_id=f"mock_seed_{caption[:6]}",
                     published_at=now - timedelta(hours=2))
            db.add(p)
        # upcoming scheduled posts
        sched = [
            ("Morning chai + osmania biscuit vibes ☕", now + timedelta(hours=2)),
            ("Weekend special: Haleem night 🌙", now + timedelta(hours=6)),
            ("Behind the scenes at our kitchen 👨‍🍳", now + timedelta(days=1, hours=3)),
            ("Poll: Irani chai vs filter coffee? ☕", now + timedelta(days=2)),
        ]
        for caption, dt in sched:
            db.add(Post(account_id=accs[0].id, caption=caption, scheduled_at=dt,
                        status=PostStatus.scheduled))
            db.add(Post(account_id=accs[1].id, caption=caption, scheduled_at=dt,
                        status=PostStatus.scheduled))
        db.commit()

        # generate metrics + comments for the published ones
        await eng.sync_metrics(db)
        await eng.sync_comments(db)
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
