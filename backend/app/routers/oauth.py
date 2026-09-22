"""Social account OAuth connect - FIXED for Pages + IG Business linking."""
from urllib.parse import urlencode, quote as _ue

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from..config import settings
from..database import get_db
from..models import Account, Platform, User
from..security import get_current_user, JWT_ALG, JWT_SECRET
import jwt as _pyjwt

def _make_state(user_id: int, platform: str) -> str:
    import time
    payload = {"sub": str(user_id), "plat": platform,
               "iat": int(time.time()), "exp": int(time.time()) + 3600}
    return _pyjwt.encode(payload, JWT_SECRET, algorithm=JWT_ALG)

def _parse_state(state: str) -> tuple[int, str]:
    data = _pyjwt.decode(state, JWT_SECRET, algorithms=[JWT_ALG])
    return int(data["sub"]), data.get("plat", "")

from..schemas import AccountOut

router = APIRouter(prefix="/api/oauth", tags=["oauth"])
REDIRECT_PATH = "/api/oauth/callback"

def _base_url(request: Request) -> str:
    """Public base URL of this app (settings first, request second)."""
    return (settings.APP_PUBLIC_URL or "").rstrip("/") or str(request.base_url).rstrip("/")


def _redirect_uri(request: Request, plat: Platform | None = None) -> str:
    """OAuth callback URL for this platform.

    Meta and Google register the callback separately, so an explicit
    META_OAUTH_REDIRECT_URI wins for Instagram/Facebook/Threads (otherwise
    APP_PUBLIC_URL + /api/oauth/callback is used). It must match the URI in the
    provider's dashboard *exactly*, including the scheme and trailing path.
    """
    override = (settings.META_OAUTH_REDIRECT_URI or "").strip()
    meta_platforms = (Platform.instagram, Platform.facebook, Platform.threads)
    if override and (plat is None or plat in meta_platforms):
        return override
    return _base_url(request) + REDIRECT_PATH

@router.get("/connect/{platform}")
async def connect(platform: str, request: Request, user: User = Depends(get_current_user)):
    plat = _require_platform(platform)
    state = _make_state(user.id, platform)
    redirect_uri = _redirect_uri(request, plat)

    if settings.MOCK_MODE:
        cb = f"{redirect_uri}?mock=1&platform={platform}&state={state}"
        return {"mode": "mock", "authorize_url": cb, "callback_url": cb}

    if plat in (Platform.instagram, Platform.facebook):
        if not settings.META_APP_ID:
            raise HTTPException(400, "META_APP_ID not set")
        qs = urlencode({
            "client_id": settings.META_APP_ID,
            "redirect_uri": redirect_uri,
            "state": state,
            # FIXED SCOPES - added business_management
            "scope": ("public_profile,email,pages_show_list,pages_read_engagement,"
                      "pages_manage_posts,pages_manage_engagement,business_management,"
                      "instagram_basic,instagram_content_publish,"
                      "instagram_manage_comments,instagram_manage_insights"),
            "response_type": "code",
        })
        url = f"https://www.facebook.com/{settings.META_GRAPH_VERSION}/dialog/oauth?{qs}"
        return {"mode": "real", "authorize_url": url}

    if plat == Platform.youtube:
        if not settings.GOOGLE_CLIENT_ID:
            raise HTTPException(400, "GOOGLE_CLIENT_ID not set")
        qs = urlencode({
            "response_type": "code",
            "client_id": settings.GOOGLE_CLIENT_ID,
            "redirect_uri": redirect_uri,
            "scope": "https://www.googleapis.com/auth/youtube.force-ssl openid profile",
            "state": state,
            "access_type": "offline",
            "prompt": "consent",
        })
        return {"mode": "real",
                "authorize_url": f"https://accounts.google.com/o/oauth2/v2/auth?{qs}"}

    if plat == Platform.threads:
        if not settings.META_APP_ID:
            raise HTTPException(400, "Threads uses your Meta App ID")
        qs = urlencode({
            "client_id": settings.META_APP_ID,
            "redirect_uri": redirect_uri,
            "state": state,
            "scope": "threads_basic,threads_content_publish",
            "response_type": "code",
        })
        return {"mode": "real",
                "authorize_url": f"https://threads.net/oauth/authorize?{qs}"}

    raise HTTPException(400, f"{plat.value} uses the manual helper on the Channels page")

@router.get("/callback", response_model=AccountOut)
async def callback(request: Request, code: str | None = None, state: str | None = None,
                   mock: str | None = None, platform: str | None = None,
                   ajax: str | None = None,
                   db: Session = Depends(get_db)):
    if not state:
        raise HTTPException(400, "Missing state")
    try:
        user_id, plat_str = _parse_state(state)
    except Exception:
        return RedirectResponse(url="/?oauth_error=" + _ue("Expired or invalid session. Please try again."))
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(401, "Unknown user")

    if mock == "1":
        plat = _require_platform(platform or plat_str)
        names = {"instagram": "@your.instagram", "facebook": "Your Facebook Page",
                 "youtube": "Your YouTube Channel", "threads": "@your.threads",
                 "moj": "Your Moj account", "sharechat": "Your ShareChat",
                 "snapchat": "Your Snapchat", "bilibili": "Your Bilibili",
                 "whatsapp": "Your WhatsApp Channel"}
        acc = _upsert_account(db, user, plat, external_id=f"mock_{plat.value}_{user.id}",
                              token="MOCK_OAUTH_TOKEN", display_name=names[plat.value])
        return await _finish(acc, ajax, db)

    if not code:
        return RedirectResponse(url="/?oauth_error=" + _ue("Missing authorization code"))

    try:
        plat = _require_platform(plat_str)
        redirect_uri = _redirect_uri(request, plat)
        return await _real_exchange(plat, code, redirect_uri, db, user, ajax, state)
    except Exception as e:
        import traceback
        print("OAUTH CALLBACK ERROR:", plat, "\n", traceback.format_exc(), flush=True)
        if ajax == "1":
            raise HTTPException(502, f"{plat.value} connect failed: {e}") from e
        return RedirectResponse(url="/?oauth_error=" + _ue(f"{plat.value.capitalize()} connect failed: {str(e)[:180]}"))

async def _real_exchange(plat, code, redirect_uri, db, user, ajax, state=""):
    if plat in (Platform.instagram, Platform.facebook):
        async with httpx.AsyncClient(timeout=30) as c:
            v = settings.META_GRAPH_VERSION
            # 1) code -> short token
            r = await c.get("https://graph.facebook.com/oauth/access_token", params={
                "client_id": settings.META_APP_ID, "client_secret": settings.META_APP_SECRET,
                "redirect_uri": redirect_uri, "code": code})
            r.raise_for_status()
            short_token = r.json()["access_token"]

            # 2) short -> long-lived token (60 days) - THIS FIXES EMPTY PAGES
            try:
                r2 = await c.get("https://graph.facebook.com/oauth/access_token", params={
                    "client_id": settings.META_APP_ID,
                    "client_secret": settings.META_APP_SECRET,
                    "grant_type": "fb_exchange_token",
                    "fb_exchange_token": short_token
                })
                r2.raise_for_status()
                user_token = r2.json().get("access_token", short_token)
                print(f"Long-lived token OK, expires in {r2.json().get('expires_in')}", flush=True)
            except Exception as ex:
                print(f"Long token exchange failed, using short token: {ex}", flush=True)
                user_token = short_token

            # 3) get Pages - FIXED with proper fields + debug
            r = await c.get(f"https://graph.facebook.com/{v}/me/accounts",
                            params={"access_token": user_token,
                                    "fields": "id,name,access_token,instagram_business_account,tasks"})
            print(f"me/accounts RAW: {r.text[:2000]}", flush=True)
            r.raise_for_status()
            pages = r.json().get("data", [])

            # DEBUG: Check permissions granted
            r_perm = await c.get(f"https://graph.facebook.com/{v}/me/permissions",
                                 params={"access_token": user_token})
            print(f"PERMISSIONS: {r_perm.text[:2000]}", flush=True)

            if not pages:
                raise HTTPException(400,
                    f"No Facebook Page found. Pages API returned 0. Permissions: {r_perm.text[:500]}. "
                    f"Make sure you are Admin of Sarvam-Sabarigireesha Page and granted pages_show_list.")

            first_acc = None
            for pg in pages:
                # Facebook page
                fb = _upsert_account(db, user, Platform.facebook,
                                     external_id=pg["id"], token=pg.get("access_token", user_token),
                                     display_name=pg.get("name", "Facebook Page"))
                first_acc = first_acc or fb

                # Try to get IG ID - first from pages response, then extra call if missing
                ig = pg.get("instagram_business_account")
                if not ig or not ig.get("id"):
                    # Extra call to get IG ID if not in first call
                    try:
                        r_pg = await c.get(f"https://graph.facebook.com/{v}/{pg['id']}",
                                           params={"fields": "instagram_business_account", "access_token": user_token})
                        if r_pg.status_code == 200:
                            ig = r_pg.json().get("instagram_business_account")
                            print(f"Page {pg['id']} IG lookup: {r_pg.text}", flush=True)
                    except Exception as e:
                        print(f"IG lookup failed for {pg['id']}: {e}", flush=True)

                if ig and ig.get("id"):
                    ig_id = ig["id"]
                    # Get IG username for display name
                    try:
                        r_ig = await c.get(f"https://graph.facebook.com/{v}/{ig_id}",
                                           params={"fields": "username,name", "access_token": user_token})
                        ig_info = r_ig.json() if r_ig.status_code == 200 else {}
                        ig_name = ig_info.get("username") or ig_info.get("name") or pg.get("name")
                    except:
                        ig_name = pg.get("name")

                    _upsert_account(
                        db, user, Platform.instagram,
                        external_id=ig_id, token=pg.get("access_token", user_token),
                        display_name=f"{ig_name} (Instagram)")

            if not first_acc:
                raise HTTPException(400, "No valid Page account created")

        return await _finish(first_acc, ajax, db)

    if plat == Platform.threads:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get("https://graph.threads.net/oauth/access_token", params={
                "client_id": settings.META_APP_ID,
                "client_secret": settings.META_APP_SECRET,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri, "code": code})
            r.raise_for_status()
            token = r.json()["access_token"]
            me = await c.get("https://graph.threads.net/me",
                             params={"fields": "id,username", "access_token": token})
            me.raise_for_status()
            d = me.json()
        acc = _upsert_account(db, user, Platform.threads,
                              external_id=d.get("id", ""), token=token,
                              display_name="@" + d.get("username", "threads"))
        return await _finish(acc, ajax, db)

    if plat == Platform.youtube:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post("https://oauth2.googleapis.com/token", data={
                "grant_type": "authorization_code", "code": code,
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "redirect_uri": redirect_uri})
            r.raise_for_status()
            tok = r.json()
            token = tok["access_token"]
            refresh = tok.get("refresh_token", "")
            me = await c.get(
                "https://www.googleapis.com/youtube/v3/channels?part=snippet&mine=true",
                headers={"Authorization": f"Bearer {token}"})
            if me.status_code!= 200:
                try:
                    gmsg = me.json()["error"]["message"]
                except Exception:
                    gmsg = me.text[:200]
                raise HTTPException(400,
                    f"YouTube API error ({me.status_code}): {gmsg}. Enable YouTube Data API v3.")
            items = me.json().get("items", [])
            if not items:
                raise HTTPException(400, "No YouTube channel found")
            ch = items[0]
        acc = _upsert_account(db, user, Platform.youtube,
                              external_id=ch["id"], token=token,
                              display_name=ch["snippet"]["title"] + " (YouTube)",
                              refresh=refresh)
        return await _finish(acc, ajax, db)

def _require_platform(p: str) -> Platform:
    try:
        return Platform(p)
    except ValueError as exc:
        raise HTTPException(404, f"Unknown platform '{p}'") from exc

def _upsert_account(db: Session, user: User, plat: Platform, external_id: str,
                    token: str, display_name: str, refresh: str = "") -> Account:
    acc = (db.query(Account)
          .filter(Account.user_id == user.id, Account.platform == plat,
                   Account.external_id == external_id).first())
    if not acc:
        acc = Account(user_id=user.id, platform=plat, external_id=external_id,
                      access_token=token, refresh_token=refresh,
                      display_name=display_name, auto_comment=True)
        db.add(acc)
    else:
        acc.access_token = token
        acc.display_name = display_name
        if refresh:
            acc.refresh_token = refresh
    db.commit()
    db.refresh(acc)
    return acc

async def _background_import(user_id: int, session_factory):
    """Import content + comments + metrics for a freshly connected account.

    Runs on its own DB session (the request session is already closed) and
    swallows errors so a background failure never surfaces as an OAuth error.
    """
    from..services import engine
    db = session_factory()
    try:
        await engine.auto_import_all(db, user_id, run_sync=True)
    except Exception:
        import traceback
        print("BACKGROUND IMPORT FAILED:", traceback.format_exc(), flush=True)
    finally:
        db.close()


async def _finish(acc: Account, ajax: str | None, db: Session | None = None):
    if db is not None:
        # Kick off the "import my existing content" sync in the background.
        # It must NOT reuse the request-scoped `db` session: `get_db()` closes
        # that session the moment the response is returned, which would make
        # the task blow up with a detached/closed session error.
        import asyncio
        from..database import SessionLocal
        asyncio.create_task(_background_import(acc.user_id, SessionLocal))
    if ajax == "1":
        from..schemas import AccountOut
        return AccountOut.model_validate(acc)
    return RedirectResponse(url="/?oauth=connected")
