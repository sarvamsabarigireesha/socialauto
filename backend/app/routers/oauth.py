"""Social account OAuth connect.

MOCK_MODE (default): /connect returns a mock callback URL — simulating the
full OAuth round trip; a connected account is created immediately.

Real mode: standard OAuth2 code flow per platform.
  Meta:      https://www.facebook.com/v21.0/dialog/oauth (IG/FB share)
  LinkedIn:  https://www.linkedin.com/oauth/v2/authorization
  X (Twt v2): PKCE flow, https://twitter.com/i/oauth2/authorize

After /callback we store the access token + external id as an Account row.
"""
import base64
import hashlib
import os
import secrets
from urllib.parse import urlencode, quote as _ue

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..models import Account, Platform, User
from ..security import get_current_user, create_token, decode_token, JWT_ALG, JWT_SECRET
import jwt as _pyjwt


def _make_state(user_id: int, platform: str) -> str:
    import time
    payload = {"sub": str(user_id), "plat": platform,
               "iat": int(time.time()), "exp": int(time.time()) + 3600}
    return _pyjwt.encode(payload, JWT_SECRET, algorithm=JWT_ALG)


def _parse_state(state: str) -> tuple[int, str]:
    data = _pyjwt.decode(state, JWT_SECRET, algorithms=[JWT_ALG])
    return int(data["sub"]), data.get("plat", "")
from ..schemas import AccountOut

router = APIRouter(prefix="/api/oauth", tags=["oauth"])

REDIRECT_PATH = "/api/oauth/callback"


def _base_url(request: Request) -> str:
    # env override for deployments behind proxies (Render/Cloud Run public URL)
    return os.getenv("APP_PUBLIC_URL", str(request.base_url).rstrip("/"))


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
        if not settings.META_APP_ID:
            raise HTTPException(400, "META_APP_ID not set — real Meta OAuth not configured")
        qs = urlencode({
            "client_id": settings.META_APP_ID,
            "redirect_uri": redirect_uri,
            "state": state,
            "scope": ("public_profile,pages_show_list,pages_read_engagement,"
                      "pages_manage_posts,pages_manage_engagement,"
                      "instagram_basic,instagram_content_publish,"
                      "instagram_manage_comments,instagram_manage_insights"),
            "response_type": "code",
        })
        url = f"https://www.facebook.com/{settings.META_GRAPH_VERSION}/dialog/oauth?{qs}"
        return {"mode": "real", "authorize_url": url}

    if plat == Platform.linkedin:
        if not settings.LINKEDIN_CLIENT_ID:
            raise HTTPException(400, "LINKEDIN_CLIENT_ID not set — real LinkedIn OAuth not configured")
        qs = urlencode({
            "response_type": "code", "client_id": settings.LINKEDIN_CLIENT_ID,
            "redirect_uri": redirect_uri, "state": state,
            "scope": "openid profile w_member_social",
        })
        return {"mode": "real",
                "authorize_url": f"https://www.linkedin.com/oauth/v2/authorization?{qs}"}

    if plat == Platform.x:
        if not settings.X_CLIENT_ID:
            raise HTTPException(400, "X_CLIENT_ID not set — real X OAuth not configured")
        verifier = secrets.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
        # short-lived: stashed via signed state-less token; embed verifier in JWT? keep simple:
        # store in a second jwt-ish token is overkill — use a server-side note via settings? Use token.
        qs = urlencode({
            "response_type": "code", "client_id": settings.X_CLIENT_ID,
            "redirect_uri": redirect_uri, "state": state,
            "scope": "tweet.read tweet.write users.read offline.access",
            "code_challenge": challenge, "code_challenge_method": "S256",
        })
        # verifier needed at callback; pass to frontend via a cookie-ish header is complex,
        # so X uses a simpler fallback: store verifier keyed by state hash in memory.
        _X_PKCE[hashlib.sha256(state.encode()).hexdigest()[:16]] = verifier
        _X_PKCE[state] = verifier  # also keyed by full state (survives)
        return {"mode": "real",
                "authorize_url": f"https://twitter.com/i/oauth2/authorize?{qs}"}

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

    # Threads: official Meta Threads API (same OAuth infra as Meta App)
    # https://developers.facebook.com/docs/threads
    if plat == Platform.threads:
        if not settings.META_APP_ID:
            raise HTTPException(400, "Threads uses your Meta App ID — set META_APP_ID to connect for real")
        qs = urlencode({
            "client_id": settings.META_APP_ID,
            "redirect_uri": redirect_uri,
            "state": state,
            "scope": "threads_basic,threads_content_publish",
            "response_type": "code",
        })
        return {"mode": "real",
                "authorize_url": f"https://threads.net/oauth/authorize?{qs}"}


_X_PKCE: dict[str, str] = {}


# ------------------------------------------------------------------ callback
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
        return RedirectResponse(url="/?oauth_error=" + _ue("Expired or invalid session. Please try connecting again."))
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(401, "Unknown user")

    redirect_uri = _base_url(request) + REDIRECT_PATH

    # ---- MOCK round trip ----
    if mock == "1":
        plat = _require_platform(platform or plat_str)
        names = {"instagram": "@your.instagram", "facebook": "Your Facebook Page",
                 "x": "@your_x_handle", "linkedin": "Your LinkedIn",
                 "youtube": "Your YouTube Channel", "threads": "@your.threads",
                 "moj": "Your Moj account", "sharechat": "Your ShareChat"}
        acc = _upsert_account(db, user, plat, external_id=f"mock_{plat.value}_{user.id}",
                              token="MOCK_OAUTH_TOKEN", display_name=names[plat.value])
        return _finish(acc, ajax)

    if not code and mock != "1":
        return RedirectResponse(url="/?oauth_error=" + _ue("Missing authorization code from provider."))
    if mock == "1":
        pass

    try:
        plat = _require_platform(plat_str)
        return await _real_exchange(plat, code, redirect_uri, db, user, ajax, state)
    except Exception as e:
        import traceback
        print("OAUTH CALLBACK ERROR:", plat, "\n", traceback.format_exc(), flush=True)
        if ajax == "1":
            raise HTTPException(502, f"{plat.value} connect failed: {e}")
        return RedirectResponse(url="/?oauth_error=" + _ue(
            f"{plat.value.capitalize()} connect failed: {str(e)[:180]}"))


async def _real_exchange(plat, code, redirect_uri, db, user, ajax, state=""):
    if plat in (Platform.instagram, Platform.facebook):
        async with httpx.AsyncClient(timeout=30) as c:
            v = settings.META_GRAPH_VERSION
            # 1) code -> user access token
            r = await c.get("https://graph.facebook.com/oauth/access_token", params={
                "client_id": settings.META_APP_ID, "client_secret": settings.META_APP_SECRET,
                "redirect_uri": redirect_uri, "code": code})
            r.raise_for_status()
            user_token = r.json()["access_token"]

            # 2) list the Facebook Pages this user manages
            r = await c.get(f"https://graph.facebook.com/{v}/me/accounts",
                            params={"access_token": user_token,
                                    "fields": "id,name,access_token,instagram_business_account"})
            r.raise_for_status()
            pages = r.json().get("data", [])
            if not pages:
                raise HTTPException(400,
                    "No Facebook Page found. Create a Page (and link an IG Business account) first.")

            first_acc = None
            for pg in pages:
                # Facebook page account
                fb = _upsert_account(db, user, Platform.facebook,
                                     external_id=pg["id"], token=pg.get("access_token", user_token),
                                     display_name=pg.get("name", "Facebook Page"))
                first_acc = first_acc or fb
                # linked Instagram business account
                ig = pg.get("instagram_business_account")
                if ig and ig.get("id"):
                    first_acc = _upsert_account(
                        db, user, Platform.instagram,
                        external_id=ig["id"], token=pg.get("access_token", user_token),
                        display_name=f"{pg.get('name','IG')} (Instagram)")
        # browser redirect -> back to app; AJAX (mock-like test) returns an account
        return _finish(first_acc, ajax)

    if plat == Platform.linkedin:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post("https://www.linkedin.com/oauth/v2/accessToken", data={
                "grant_type": "authorization_code", "code": code,
                "client_id": settings.LINKEDIN_CLIENT_ID,
                "client_secret": settings.LINKEDIN_CLIENT_SECRET,
                "redirect_uri": redirect_uri})
            r.raise_for_status()
            token = r.json()["access_token"]
            me = await c.get("https://api.linkedin.com/v2/userinfo",
                            headers={"Authorization": f"Bearer {token}"})
            me.raise_for_status()
            d = me.json()
        acc = _upsert_account(db, user, Platform.linkedin,
                              external_id=d.get("sub", ""), token=token,
                              display_name=d.get("name", "LinkedIn User"))
        return _finish(acc, ajax)

    if plat == Platform.x:
        sig = hashlib.sha256(state.encode()).hexdigest()[:16]
        verifier = _X_PKCE.pop(state, None) or _X_PKCE.pop(sig, None)
        if not verifier:
            raise HTTPException(400, "PKCE verifier lost — restart connect")
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post("https://api.twitter.com/2/oauth/token", data={
                "grant_type": "authorization_code", "code": code,
                "redirect_uri": redirect_uri, "code_verifier": verifier,
                "client_id": settings.X_CLIENT_ID},
                auth=(settings.X_CLIENT_ID, settings.X_CLIENT_SECRET))
            r.raise_for_status()
            token = r.json()["access_token"]
            me = await c.get("https://api.twitter.com/2/users/me",
                            headers={"Authorization": f"Bearer {token}"})
            me.raise_for_status()
            d = me.json()["data"]
        acc = _upsert_account(db, user, Platform.x, external_id=d["id"], token=token,
                              display_name="@" + d["username"])
        return _finish(acc, ajax)

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
        return _finish(acc, ajax)

    if plat == Platform.youtube:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post("https://oauth2.googleapis.com/token", data={
                "grant_type": "authorization_code", "code": code,
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "redirect_uri": redirect_uri})
            r.raise_for_status()
            token = r.json()["access_token"]
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
                              display_name=ch["snippet"]["title"] + " (YouTube)")
        return _finish(acc, ajax)


_REDIRECT_PLATFORM: dict[str, Platform] = {}


def _require_platform(p: str) -> Platform:
    try:
        return Platform(p)
    except ValueError:
        raise HTTPException(404, f"Unknown platform '{p}'")


def _detect_platform_from_code(code: str):  # pragma: no cover - placeholder
    return None


def _upsert_account(db: Session, user: User, plat: Platform, external_id: str,
                    token: str, display_name: str) -> Account:
    acc = (db.query(Account)
           .filter(Account.user_id == user.id, Account.platform == plat,
                   Account.external_id == external_id).first())
    if not acc:
        acc = Account(user_id=user.id, platform=plat, external_id=external_id,
                      access_token=token, display_name=display_name, auto_comment=True)
        db.add(acc)
    else:
        acc.access_token = token
        acc.display_name = display_name
    db.commit()
    db.refresh(acc)
    return acc


def _finish(acc: Account, ajax: str | None):
    """AJAX (mock flow from SPA) -> JSON; browser redirect (real OAuth) -> back to app."""
    if ajax == "1":
        from ..schemas import AccountOut
        return AccountOut.model_validate(acc)
    return RedirectResponse(url="/?oauth=connected")
