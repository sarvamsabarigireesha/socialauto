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
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..models import Account, Platform, User
from ..security import get_current_user, create_token, decode_token
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
    state = create_token(user.id)          # signed JWT carrying user id
    redirect_uri = _base_url(request) + REDIRECT_PATH
    sig = hashlib.sha256(state.encode()).hexdigest()[:16]
    _REDIRECT_PLATFORM[sig] = plat

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
            "scope": "instagram_basic,pages_show_list,pages_manage_posts,public_profile",
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


_X_PKCE: dict[str, str] = {}


# ------------------------------------------------------------------ callback
@router.get("/callback", response_model=AccountOut)
async def callback(request: Request, code: str | None = None, state: str | None = None,
                   mock: str | None = None, platform: str | None = None,
                   ajax: str | None = None,
                   db: Session = Depends(get_db)):
    if not state:
        raise HTTPException(400, "Missing state")
    user_id = decode_token(state)
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(401, "Unknown user")

    redirect_uri = _base_url(request) + REDIRECT_PATH

    # ---- MOCK round trip ----
    if mock == "1":
        plat = _require_platform(platform)
        names = {"instagram": "@your.instagram", "facebook": "Your Facebook Page",
                 "x": "@your_x_handle", "linkedin": "Your LinkedIn",
                 "youtube": "Your YouTube Channel"}
        acc = _upsert_account(db, user, plat, external_id=f"mock_{plat.value}_{user.id}",
                              token="MOCK_OAUTH_TOKEN", display_name=names[plat.value])
        return _finish(acc, ajax)

    plat_hint = _detect_platform_from_code(code or "")   # real: caller passes ?platform too via state? no.
    # Platform in real flow: Meta/LinkedIn/X all hit same callback; distinguish via state? We set
    # state per connect; embed platform in JWT? decode_token only gives uid. Accept platform via query.
    # Frontend appends nothing (provider does) — so store platform at /connect time keyed by state hash.
    sig = hashlib.sha256(state.encode()).hexdigest()[:16]
    plat = _REDIRECT_PLATFORM.pop(sig, None)
    if not plat:
        raise HTTPException(400, "Unknown OAuth session — restart connect")
    if not code:
        raise HTTPException(400, "Missing authorization code")

    # ---- REAL exchanges ----
    if plat in (Platform.instagram, Platform.facebook):
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get("https://graph.facebook.com/oauth/access_token", params={
                "client_id": settings.META_APP_ID, "client_secret": settings.META_APP_SECRET,
                "redirect_uri": redirect_uri, "code": code})
            r.raise_for_status()
            token = r.json()["access_token"]
            me = await c.get(f"https://graph.facebook.com/{settings.META_GRAPH_VERSION}/me",
                             params={"access_token": token, "fields": "id,name"})
            me.raise_for_status()
            d = me.json()
        acc = _upsert_account(db, user, plat, external_id=d["id"], token=token,
                              display_name=d.get("name", "FB Page"))
        return _finish(acc, ajax)

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
        verifier = _X_PKCE.pop(sig, None)
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
            me.raise_for_status()
            items = me.json().get("items", [])
            if not items:
                raise HTTPException(400, "No YouTube channel found on this Google account")
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
