"""Social account OAuth connect.

MOCK_MODE (default): /connect returns a mock callback URL — simulating the
full OAuth round trip; a connected account is created immediately.

Real mode: standard OAuth2 code flow per platform.
  Meta:      https://www.facebook.com/{version}/dialog/oauth (IG/FB share)
  Google:    https://accounts.google.com/o/oauth2/v2/auth (YouTube)
  Threads:   https://threads.net/oauth/authorize

After /callback we store a long-lived page token + external id as an Account.
"""
from urllib.parse import urlencode, quote as _ue

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from .. import meta_store
from ..config import settings
from ..database import get_db
from ..models import Account, Platform, User
from ..schemas import AccountOut
from ..security import get_current_user, JWT_ALG, JWT_SECRET
import jwt as _pyjwt


def _make_state(user_id: int, platform: str) -> str:
    import time
    payload = {"sub": str(user_id), "plat": platform,
               "iat": int(time.time()), "exp": int(time.time()) + 3600}
    return _pyjwt.encode(payload, JWT_SECRET, algorithm=JWT_ALG)


def _parse_state(state: str) -> tuple[int, str]:
    data = _pyjwt.decode(state, JWT_SECRET, algorithms=[JWT_ALG])
    return int(data["sub"]), data.get("plat", "")


router = APIRouter(prefix="/api/oauth", tags=["oauth"])

REDIRECT_PATH = "/api/oauth/callback"


def _base_url(request: Request) -> str:
    return (settings.APP_PUBLIC_URL or str(request.base_url).rstrip("/")).rstrip("/")


def _graph_error(resp: httpx.Response) -> str:
    try:
        err = resp.json().get("error") or {}
        msg = err.get("message") or resp.text[:240]
        code = err.get("code")
        return f"{msg}" + (f" (code {code})" if code else "")
    except Exception:
        return resp.text[:240]


# ------------------------------------------------------------------ start
@router.get("/connect/{platform}")
async def connect(platform: str, request: Request, user: User = Depends(get_current_user)):
    """Begin OAuth. Returns {authorize_url} (real) or {mock_callback} (demo)."""
    plat = _require_platform(platform)
    state = _make_state(user.id, platform)
    redirect_uri = _base_url(request) + REDIRECT_PATH

    if settings.MOCK_MODE:
        cb = f"{redirect_uri}?mock=1&platform={platform}&state={state}"
        return {"mode": "mock", "authorize_url": cb, "callback_url": cb}

    if plat in (Platform.instagram, Platform.facebook):
        if not settings.META_APP_ID or not settings.META_APP_SECRET:
            raise HTTPException(400, {
                "code": "meta_not_configured",
                "message": "Meta App ID / Secret missing. Open Channels → Meta App setup, "
                           "paste credentials from developers.facebook.com, then try again.",
            })
        params = {
            "client_id": settings.META_APP_ID,
            "redirect_uri": redirect_uri,
            "state": state,
            "response_type": "code",
            "auth_type": "rerequest",
        }
        config_id = meta_store.meta_config_id()
        if config_id:
            # New Meta dashboard (Facebook Login for Business configurations)
            params["config_id"] = config_id
        else:
            params["scope"] = meta_store.META_SCOPES
        qs = urlencode(params)
        url = f"https://www.facebook.com/{settings.META_GRAPH_VERSION}/dialog/oauth?{qs}"
        return {"mode": "real", "authorize_url": url}

    if plat == Platform.youtube:
        if not settings.GOOGLE_CLIENT_ID:
            raise HTTPException(400, "GOOGLE_CLIENT_ID not set — Google/YouTube OAuth not configured")
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
            raise HTTPException(400, {
                "code": "meta_not_configured",
                "message": "Threads uses your Meta App ID — set it in Channels → Meta App setup.",
            })
        qs = urlencode({
            "client_id": settings.META_APP_ID,
            "redirect_uri": redirect_uri,
            "state": state,
            "scope": meta_store.THREADS_SCOPES,
            "response_type": "code",
        })
        return {"mode": "real",
                "authorize_url": f"https://threads.net/oauth/authorize?{qs}"}

    raise HTTPException(400, f"{plat.value} does not use OAuth — use the manual/helper connect flow")


# ------------------------------------------------------------------ callback
@router.get("/callback")
async def callback(request: Request, code: str | None = None, state: str | None = None,
                   mock: str | None = None, platform: str | None = None,
                   ajax: str | None = None,
                   db: Session = Depends(get_db)):
    if not state:
        raise HTTPException(400, "Missing state")
    try:
        user_id, plat_str = _parse_state(state)
    except Exception:
        return RedirectResponse(url="/?oauth_error=" + _ue(
            "Expired or invalid session. Please try connecting again."))
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(401, "Unknown user")

    redirect_uri = _base_url(request) + REDIRECT_PATH

    if mock == "1":
        plat = _require_platform(platform or plat_str)
        names = {"instagram": "@your.instagram", "facebook": "Your Facebook Page",
                 "youtube": "Your YouTube Channel", "threads": "@your.threads",
                 "moj": "Your Moj account", "sharechat": "Your ShareChat",
                 "snapchat": "Your Snapchat", "bilibili": "Your Bilibili"}
        acc = _upsert_account(db, user, plat, external_id=f"mock_{plat.value}_{user.id}",
                              token="MOCK_OAUTH_TOKEN", display_name=names[plat.value])
        return await _finish(acc, ajax, db)

    if not code:
        return RedirectResponse(url="/?oauth_error=" + _ue(
            "Missing authorization code from provider."))

    try:
        plat = _require_platform(plat_str)
        return await _real_exchange(plat, code, redirect_uri, db, user, ajax)
    except HTTPException as e:
        msg = e.detail if isinstance(e.detail, str) else (
            (e.detail or {}).get("message") if isinstance(e.detail, dict) else str(e.detail))
        if ajax == "1":
            raise
        return RedirectResponse(url="/?oauth_error=" + _ue(str(msg)[:180]))
    except Exception as e:
        import traceback
        print("OAUTH CALLBACK ERROR:", plat_str, "\n", traceback.format_exc(), flush=True)
        if ajax == "1":
            raise HTTPException(502, f"{plat_str} connect failed: {e}")
        return RedirectResponse(url="/?oauth_error=" + _ue(
            f"{plat_str.capitalize()} connect failed: {str(e)[:180]}"))


async def _exchange_long_lived(c: httpx.AsyncClient, short_token: str) -> str:
    """Short-lived user token (~1h) → long-lived (~60 days). Page tokens
    minted from a long-lived user token do not expire."""
    r = await c.get(f"https://graph.facebook.com/{settings.META_GRAPH_VERSION}/oauth/access_token",
                    params={
                        "grant_type": "fb_exchange_token",
                        "client_id": settings.META_APP_ID,
                        "client_secret": settings.META_APP_SECRET,
                        "fb_exchange_token": short_token,
                    })
    if r.status_code == 200 and r.json().get("access_token"):
        return r.json()["access_token"]
    return short_token


async def _subscribe_page(c: httpx.AsyncClient, page_id: str, page_token: str) -> None:
    try:
        await c.post(
            f"https://graph.facebook.com/{settings.META_GRAPH_VERSION}/{page_id}/subscribed_apps",
            data={"subscribed_fields": "feed,mention,comments",
                  "access_token": page_token},
        )
    except Exception:
        pass


async def _ig_display_name(c: httpx.AsyncClient, ig_id: str, token: str, fallback: str) -> str:
    try:
        r = await c.get(
            f"https://graph.facebook.com/{settings.META_GRAPH_VERSION}/{ig_id}",
            params={"fields": "username,name", "access_token": token},
        )
        if r.status_code == 200:
            d = r.json()
            uname = d.get("username") or d.get("name")
            if uname:
                return uname if str(uname).startswith("@") else f"@{uname}"
    except Exception:
        pass
    return f"{fallback} (Instagram)"


async def _real_exchange(plat, code, redirect_uri, db, user, ajax):
    if plat in (Platform.instagram, Platform.facebook):
        async with httpx.AsyncClient(timeout=30) as c:
            v = settings.META_GRAPH_VERSION
            r = await c.get("https://graph.facebook.com/oauth/access_token", params={
                "client_id": settings.META_APP_ID, "client_secret": settings.META_APP_SECRET,
                "redirect_uri": redirect_uri, "code": code})
            if r.status_code != 200:
                raise HTTPException(400, f"Meta token exchange failed: {_graph_error(r)}")
            user_token = r.json().get("access_token")
            if not user_token:
                raise HTTPException(400, "Meta did not return an access token")
            user_token = await _exchange_long_lived(c, user_token)

            r = await c.get(f"https://graph.facebook.com/{v}/me/accounts",
                            params={"access_token": user_token,
                                    "fields": "id,name,access_token,instagram_business_account{id,username,name}"})
            if r.status_code != 200:
                raise HTTPException(400, f"Could not list Facebook Pages: {_graph_error(r)}")
            pages = r.json().get("data", [])
            if not pages:
                raise HTTPException(400,
                    "No Facebook Page found. Create a Page, link your Instagram Professional "
                    "account to it (IG → Edit profile → Page), then try Connect again. "
                    "Also tick every Page on the Meta permission screen.")

            first_acc = None
            found_ig = False
            for pg in pages:
                page_token = pg.get("access_token") or user_token
                fb = _upsert_account(db, user, Platform.facebook,
                                     external_id=str(pg["id"]), token=page_token,
                                     display_name=pg.get("name", "Facebook Page"))
                first_acc = first_acc or fb
                await _subscribe_page(c, str(pg["id"]), page_token)

                ig = pg.get("instagram_business_account") or {}
                if ig.get("id"):
                    found_ig = True
                    ig_name = ig.get("username") or ig.get("name")
                    if ig_name:
                        display = ig_name if str(ig_name).startswith("@") else f"@{ig_name}"
                    else:
                        display = await _ig_display_name(c, str(ig["id"]), page_token,
                                                         pg.get("name", "IG"))
                    first_acc = _upsert_account(
                        db, user, Platform.instagram,
                        external_id=str(ig["id"]), token=page_token,
                        display_name=display) or first_acc

        warn = ""
        if plat == Platform.instagram and not found_ig:
            warn = ("Facebook Page connected, but no Instagram Professional account is linked. "
                    "IG → Settings → Account type → Professional, then link a Facebook Page.")
        return await _finish(first_acc, ajax, db, warn=warn)

    if plat == Platform.threads:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post("https://graph.threads.net/oauth/access_token", data={
                "client_id": settings.META_APP_ID,
                "client_secret": settings.META_APP_SECRET,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri, "code": code})
            if r.status_code != 200:
                raise HTTPException(400, f"Threads token exchange failed: {_graph_error(r)}")
            token = r.json().get("access_token")
            if not token:
                raise HTTPException(400, "Threads did not return an access token")
            # long-lived Threads token
            try:
                ll = await c.get("https://graph.threads.net/access_token", params={
                    "grant_type": "th_exchange_token",
                    "client_secret": settings.META_APP_SECRET,
                    "access_token": token,
                })
                if ll.status_code == 200 and ll.json().get("access_token"):
                    token = ll.json()["access_token"]
            except Exception:
                pass
            me = await c.get("https://graph.threads.net/me",
                             params={"fields": "id,username", "access_token": token})
            if me.status_code != 200:
                raise HTTPException(400, f"Threads profile failed: {_graph_error(me)}")
            d = me.json()
        acc = _upsert_account(db, user, Platform.threads,
                              external_id=str(d.get("id", "")), token=token,
                              display_name="@" + d.get("username", "threads"))
        return await _finish(acc, ajax, db)

    if plat == Platform.youtube:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post("https://oauth2.googleapis.com/token", data={
                "grant_type": "authorization_code", "code": code,
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "redirect_uri": redirect_uri})
            if r.status_code != 200:
                raise HTTPException(400, f"Google token exchange failed: {r.text[:200]}")
            tok = r.json()
            token = tok["access_token"]
            refresh = tok.get("refresh_token", "")
            me = await c.get(
                "https://www.googleapis.com/youtube/v3/channels?part=snippet&mine=true",
                headers={"Authorization": f"Bearer {token}"})
            if me.status_code != 200:
                try:
                    gmsg = me.json()["error"]["message"]
                except Exception:
                    gmsg = me.text[:200]
                raise HTTPException(400,
                    f"YouTube API error ({me.status_code}): {gmsg}. "
                    f"Enable YouTube Data API v3 in Google Cloud console.")
            items = me.json().get("items", [])
            if not items:
                raise HTTPException(400, "No YouTube channel found on this Google account — create one at youtube.com")
            ch = items[0]
        acc = _upsert_account(db, user, Platform.youtube,
                              external_id=ch["id"], token=token,
                              display_name=ch["snippet"]["title"] + " (YouTube)",
                              refresh=refresh)
        return await _finish(acc, ajax, db)

    raise HTTPException(400, f"No OAuth handler for {plat}")


def _require_platform(p: str) -> Platform:
    try:
        return Platform(p)
    except ValueError:
        raise HTTPException(404, f"Unknown platform '{p}'")


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


async def _finish(acc: Account, ajax: str | None, db: Session | None = None, warn: str = ""):
    """AJAX (mock flow from SPA) -> JSON; browser redirect (real OAuth) -> back to app.
    Fire-and-forget: auto-import the channel's existing content so comments and
    analytics appear without the user pressing anything."""
    if db is not None:
        import asyncio
        from ..services import engine
        try:
            asyncio.create_task(engine.auto_import_all(db, acc.user_id))
        except Exception:
            pass
    if ajax == "1":
        return AccountOut.model_validate(acc)
    qs = "oauth=connected"
    if warn:
        qs += "&oauth_warn=" + _ue(warn)
    return RedirectResponse(url=f"/?{qs}")
