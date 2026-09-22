"""Live-mode preflight for real posting (Instagram / Facebook / YouTube).

Three modes:

    python3 live_check.py                 # offline: which credentials are set,
                                          # which connected accounts can publish
    python3 live_check.py --online         # read-only calls to Meta/Google to
                                          # verify the credentials actually work
    python3 live_check.py --post 3 --media https://.../pic.jpg --yes
                                          # do ONE real publish (Instagram/FB)

Nothing here is destructive in --online mode: it only reads.
"""
import argparse
import asyncio
import os
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import httpx  # noqa: E402

from app.config import ENV_FILE, settings  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.models import Account, Platform, Post, PostStatus  # noqa: E402
from app.services import platforms  # noqa: E402

OK, WARN, BAD = "✅", "⚠️ ", "❌"
problems: list[str] = []


def say(mark, msg, fix=""):
    print(f"  {mark} {msg}")
    if fix and mark != OK:
        print(f"       ↳ {fix}")


def need(cond, label, fix=""):
    say(OK if cond else BAD, label, fix)
    if not cond:
        problems.append(label)


# --------------------------------------------------------------- offline part
def check_env():
    print("\n[1] environment")
    say(OK if ENV_FILE else WARN,
        f".env loaded: {ENV_FILE}" if ENV_FILE else "no .env file found",
        "cp .env.example .env and fill it in (the app reads it automatically now)")
    say(OK, f"MOCK_MODE = {settings.MOCK_MODE}")
    if settings.MOCK_MODE:
        say(BAD, "MOCK_MODE=true — every 'publish' is simulated",
            "set MOCK_MODE=false in .env to make real API calls")
        problems.append("MOCK_MODE still true")
    need(settings.CRON_SECRET != "dev-cron-secret-change-me", "CRON_SECRET is not the dev default",
         "set CRON_SECRET to a long random string")
    if os.getenv("JWT_SECRET", "dev-jwt-secret-change-me-in-production") == \
            "dev-jwt-secret-change-me-in-production":
        say(WARN, "JWT_SECRET is the dev default — tokens are forgeable",
            "set JWT_SECRET to a long random string")


def check_meta():
    print("\n[2] Meta (Instagram / Facebook)")
    app_id, secret = settings.META_APP_ID, settings.META_APP_SECRET
    need(bool(app_id), "META_APP_ID set", "developers.facebook.com → your app → Settings → Basic")
    need(bool(secret), "META_APP_SECRET set", "same page, App Secret")
    say(OK, f"META_GRAPH_VERSION = {settings.META_GRAPH_VERSION}")
    say(OK, f"META_VERIFY_TOKEN = {settings.META_VERIFY_TOKEN or '(empty)'}")
    if app_id and not app_id.isdigit():
        say(WARN, "META_APP_ID doesn't look numeric", "it's the numeric App ID, not the app name")


def check_google():
    print("\n[3] Google (YouTube)")
    cid, secret = settings.GOOGLE_CLIENT_ID, settings.GOOGLE_CLIENT_SECRET
    need(bool(cid), "GOOGLE_CLIENT_ID set", "console.cloud.google.com → Credentials → OAuth client")
    if cid and not cid.endswith(".apps.googleusercontent.com"):
        say(WARN, "GOOGLE_CLIENT_ID should end with .apps.googleusercontent.com")
    need(bool(secret), "GOOGLE_CLIENT_SECRET set")
    say(OK if settings.YOUTUBE_AUTO_UPLOAD else WARN,
        f"YOUTUBE_AUTO_UPLOAD = {settings.YOUTUBE_AUTO_UPLOAD} "
        f"(uploads are {settings.YOUTUBE_PRIVACY_STATUS})",
        "set YOUTUBE_AUTO_UPLOAD=true to upload the video file directly, "
        "otherwise YouTube posts stay a manual step")


def check_public_url():
    print("\n[4] public URL (Instagram needs to *fetch* your media)")
    if settings.APP_PUBLIC_URL:
        say(OK, f"APP_PUBLIC_URL = {settings.APP_PUBLIC_URL}")
        if not settings.APP_PUBLIC_URL.startswith("https://"):
            say(BAD, "must be https — Instagram/Google reject http and localhost",
                "deploy first (Render/Railway free tier) and put that URL here")
            problems.append("APP_PUBLIC_URL is not https")
    else:
        say(BAD, "APP_PUBLIC_URL is empty",
            "Instagram must download your image/video from a public https URL. "
            "localhost won't work — deploy, then set this to https://your-app.onrender.com")
        problems.append("APP_PUBLIC_URL empty")


def check_accounts():
    print("\n[5] connected accounts in the database")
    db = SessionLocal()
    try:
        accounts = db.query(Account).all()
        if not accounts:
            say(BAD, "no accounts connected",
                "run the app, log in, and use Connect on the Accounts screen")
            problems.append("no accounts connected")
            return []
        for a in accounts:
            token = bool(a.access_token and a.access_token != "MOCK_TOKEN")
            issues = []
            if not token:
                issues.append("no access token")
            if a.platform in (Platform.instagram, Platform.facebook, Platform.youtube) \
                    and not a.external_id:
                issues.append("no external_id")
            if a.platform == Platform.youtube and not a.refresh_token:
                issues.append("no refresh_token → access token dies after 1h")
            if a.platform in (Platform.moj, Platform.sharechat):
                issues.append("no public API — manual posting only")
            mark = OK if not issues else WARN
            say(mark, f"#{a.id} {a.platform.value:10s} {a.display_name}"
                      + (f"  [{', '.join(issues)}]" if issues else ""))
        return accounts
    finally:
        db.close()


# ---------------------------------------------------------------- online part
async def check_online(accounts):
    print("\n[6] live API checks (read-only)")
    async with httpx.AsyncClient(timeout=30) as c:
        # Meta app credentials — app access token is "id|secret"
        if settings.META_APP_ID and settings.META_APP_SECRET:
            r = await c.get(f"https://graph.facebook.com/{settings.META_GRAPH_VERSION}/me",
                            params={"access_token":
                                    f"{settings.META_APP_ID}|{settings.META_APP_SECRET}"})
            if r.status_code == 200:
                say(OK, f"Meta app credentials valid (app: {r.json().get('name', '?')})")
            else:
                say(BAD, f"Meta app credentials rejected ({r.status_code})",
                    r.json().get("error", {}).get("message", r.text[:200]))
                problems.append("Meta app credentials invalid")
        else:
            say(WARN, "skipping Meta check — no app id/secret")

        # APP_PUBLIC_URL reachable from the outside?
        if settings.APP_PUBLIC_URL:
            try:
                r = await c.get(settings.APP_PUBLIC_URL.rstrip("/") + "/api/health")
                say(OK if r.status_code == 200 else BAD,
                    f"APP_PUBLIC_URL reachable (HTTP {r.status_code})",
                    "Instagram will fail to fetch media if this URL isn't public")
            except Exception as exc:
                say(BAD, f"APP_PUBLIC_URL not reachable: {exc}")
                problems.append("APP_PUBLIC_URL unreachable")

        for a in accounts:
            if a.platform.value in ("moj", "sharechat"):
                continue
            if a.platform == Platform.youtube:
                if not a.refresh_token:
                    say(WARN, f"#{a.id} {a.display_name}: no refresh token, skipping")
                    continue
                r = await c.post("https://oauth2.googleapis.com/token", data={
                    "grant_type": "refresh_token", "refresh_token": a.refresh_token,
                    "client_id": settings.GOOGLE_CLIENT_ID,
                    "client_secret": settings.GOOGLE_CLIENT_SECRET})
                if r.status_code != 200:
                    say(BAD, f"#{a.id} {a.display_name}: Google token refresh failed "
                             f"({r.status_code})",
                        r.json().get("error_description", r.text[:200]))
                    problems.append(f"#{a.id} google refresh failed")
                    continue
                tok = r.json()["access_token"]
                ch = await c.get("https://www.googleapis.com/youtube/v3/channels",
                                 params={"part": "snippet", "mine": "true"},
                                 headers={"Authorization": f"Bearer {tok}"})
                items = ch.json().get("items", []) if ch.status_code == 200 else []
                if items:
                    say(OK, f"#{a.id} {a.display_name}: token OK, channel "
                            f"'{items[0]['snippet']['title']}'")
                else:
                    say(BAD, f"#{a.id} {a.display_name}: no YouTube channel on this token "
                             f"({ch.status_code})",
                        "the Google account you connected has no channel")
                    problems.append(f"#{a.id} no youtube channel")
                continue

            r = await c.get(f"https://graph.facebook.com/{settings.META_GRAPH_VERSION}"
                            f"/{a.external_id}",
                            params={"fields": "id,name,username",
                                    "access_token": a.access_token})
            if r.status_code == 200:
                d = r.json()
                say(OK, f"#{a.id} {a.display_name}: token OK "
                        f"({d.get('name') or d.get('username') or d.get('id')})")
            else:
                say(BAD, f"#{a.id} {a.display_name}: {r.status_code} "
                         f"{r.json().get('error', {}).get('message', r.text[:150])}",
                    "reconnect the account so a fresh token is stored")
                problems.append(f"#{a.id} token rejected")


# ---------------------------------------------------------------- post a test
async def do_post(account_id, caption, media_url):
    db = SessionLocal()
    try:
        account = db.get(Account, account_id)
        if not account:
            print(f"❌ no account with id {account_id}")
            return 1
        print(f"\nPublishing ONE real post to #{account.id} {account.platform.value} "
              f"{account.display_name} …")
        post = Post(user_id=account.user_id, account_id=account.id, caption=caption,
                    media_url=media_url, post_type="feed", source="now",
                    scheduled_at=__import__("datetime").datetime.now(
                        __import__("datetime").timezone.utc),
                    status=PostStatus.scheduled)
        db.add(post)
        db.commit()
        db.refresh(post)
        post_id = post.id

        from app.services import engine
        result = await engine.publish_one(db, post_id)
        print(f"\n  status : {result.status.value}")
        print(f"  id     : {result.platform_post_id or '—'}")
        if result.error:
            print(f"  error  : {result.error}")
        if result.status == PostStatus.published:
            print(f"\n{OK} real post is live — check your account / dashboard")
            return 0
        print(f"\n{BAD} publish failed (post row #{post_id} left in the dashboard)")
        return 1
    finally:
        db.close()


async def direct_publish(args):
    """One real publish with just a token — no OAuth redirect, no DB row.

    Useful for the very first live test: paste a long-lived Page/IG token and
    the numeric target id into .env as META_ACCESS_TOKEN, then run
    `--direct instagram:<ig_user_id> --media https://.../pic.jpg --yes`.
    """
    print("SocialAuto direct live-publish test")
    print("=" * 62)
    try:
        platform_name, target = args.direct.split(":", 1)
    except ValueError:
        print("❌ --direct needs PLATFORM:TARGET_ID, e.g. instagram:17841400000000000")
        return 2

    try:
        platform = Platform(platform_name.strip().lower())
    except ValueError:
        print(f"❌ unknown platform '{platform_name}' "
              f"(use {', '.join(p.value for p in Platform)})")
        return 2

    if platform in (Platform.instagram, Platform.facebook):
        token = os.getenv("META_ACCESS_TOKEN", "")
        if not token:
            print("❌ META_ACCESS_TOKEN is not set.\n"
                  "   Put a long-lived Page token in .env:\n"
                  "     META_ACCESS_TOKEN=EAAG...\n"
                  "   Get one at developers.facebook.com/tools/explorer "
                  "(select your Page, then 'Get Page Access Token').")
            return 2
    elif platform == Platform.youtube:
        token = os.getenv("GOOGLE_ACCESS_TOKEN", "")
        if not token:
            print("❌ GOOGLE_ACCESS_TOKEN is not set (a short-lived OAuth token "
                  "from the OAuth 2.0 Playground is fine for a test).")
            return 2
    else:
        print(f"❌ {platform.value} has no publishing API in this build")
        return 2

    if not args.media.startswith("https://"):
        print("❌ --media must be a public https URL — the platform downloads it "
              "itself (localhost/file paths are rejected by Instagram)")
        return 2

    if platform == Platform.youtube:
        settings.YOUTUBE_AUTO_UPLOAD = True

    print(f"platform : {platform.value}")
    print(f"target   : {target}")
    print(f"media    : {args.media}")
    print(f"caption  : {args.caption[:60]}{'…' if len(args.caption) > 60 else ''}\n")

    if not args.yes:
        if input("Send this as a REAL post? [y/N] ").strip().lower() not in ("y", "yes"):
            print("aborted")
            return 0

    account = Account(id=0, user_id=0, platform=platform, external_id=target,
                      access_token=token, refresh_token=os.getenv("GOOGLE_REFRESH_TOKEN", ""),
                      display_name="(direct test)", auto_comment=False,
                      comment_template="", posting_slots=[], posting_goal=1)
    client = platforms.get_client(platform)
    result = await client.publish(account, args.caption, args.media, post_type="feed")

    print(f"\n  ok     : {result.ok}")
    print(f"  manual : {getattr(result, 'manual', False)}")
    print(f"  id     : {result.platform_post_id or '—'}")
    if result.error:
        print(f"  error  : {result.error}")
    if result.ok:
        print(f"\n{OK} REAL POST SUCCEEDED — live id {result.platform_post_id}")
        return 0
    print(f"\n{BAD} live publish failed (nothing was posted)")
    return 1


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--online", action="store_true",
                    help="also make read-only live calls to verify credentials")
    ap.add_argument("--post", type=int, metavar="ACCOUNT_ID",
                    help="publish one real test post to this account")
    ap.add_argument("--media", default="", help="public https media URL for --post")
    ap.add_argument("--caption", default="SocialAuto test post — please ignore 🙏")
    ap.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    ap.add_argument("--direct", metavar="PLATFORM:TARGET_ID",
                    help="publish without OAuth/DB — uses META_ACCESS_TOKEN (instagram/"
                         "facebook) or GOOGLE_ACCESS_TOKEN (youtube) from .env. "
                         "Example: --direct instagram:17841400000000000")
    args = ap.parse_args()

    if args.direct:
        return asyncio.run(direct_publish(args))

    print("SocialAuto live-preflight")
    print("=" * 62)
    check_env()
    check_meta()
    check_google()
    check_public_url()
    accounts = check_accounts()

    if args.online and accounts:
        asyncio.run(check_online(accounts))
    elif args.online:
        print("\n[6] live API checks — skipped, no accounts connected")

    if args.post:
        if not args.media:
            print("\n❌ --post needs --media (a public https image URL for Instagram, "
                  "or a video URL with YOUTUBE_AUTO_UPLOAD=true)")
            return 2
        if not args.yes:
            reply = input(f"\nReally publish ONE live post to account #{args.post}? "
                          f"[y/N] ").strip().lower()
            if reply not in ("y", "yes"):
                print("aborted")
                return 0
        return asyncio.run(do_post(args.post, args.caption, args.media))

    print("\n" + "=" * 62)
    if problems:
        print(f"{BAD} {len(problems)} thing(s) to fix before real posting:")
        for p in problems:
            print(f"     • {p}")
    else:
        print(f"{OK} all preflight checks passed — ready for real posting")
    if not args.online:
        print("\nnext:  python3 live_check.py --online")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
