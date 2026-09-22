"""In-app Meta (Facebook / Instagram) app setup.

GET  /api/settings/meta        status + copy-paste URLs for the Meta dashboard
POST /api/settings/meta        save App ID / Secret / verify token / mock toggle
POST /api/settings/meta/test   ping Graph API with the saved (or posted) credentials
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from .. import meta_store
from ..config import settings
from ..models import User
from ..security import get_current_user

router = APIRouter(prefix="/api/settings", tags=["settings"])


class MetaSaveIn(BaseModel):
    app_id: str | None = Field(None, max_length=80)
    app_secret: str | None = Field(None, max_length=200)
    verify_token: str | None = Field(None, max_length=120)
    mock_mode: bool | None = None
    app_public_url: str | None = Field(None, max_length=400)
    config_id: str | None = Field(None, max_length=80)


def _base(request: Request) -> str:
    return (settings.APP_PUBLIC_URL or str(request.base_url).rstrip("/")).rstrip("/")


def _status_payload(request: Request) -> dict:
    base = _base(request)
    configured = meta_store.meta_configured()
    return {
        "configured": configured,
        "mock_mode": settings.MOCK_MODE,
        "app_id": settings.META_APP_ID,
        "has_secret": bool(settings.META_APP_SECRET),
        "verify_token": settings.META_VERIFY_TOKEN,
        "graph_version": settings.META_GRAPH_VERSION,
        "config_id": meta_store.meta_config_id(),
        "app_public_url": base,
        "redirect_uri": base + "/api/oauth/callback",
        "webhook_url": base + "/api/webhooks/meta",
        "scopes": meta_store.META_SCOPES,
        "live_ready": configured and not settings.MOCK_MODE,
        "steps": [
            {
                "id": 1,
                "title": "Create a Meta Developer app",
                "body": (
                    "Open developers.facebook.com → My Apps → Create App. "
                    "Use case: Other → App type: Business. Name it SocialAuto."
                ),
            },
            {
                "id": 2,
                "title": "Add products",
                "body": (
                    "Add Facebook Login for Business, Instagram (Graph API), and Webhooks. "
                    "In Facebook Login → Settings paste the OAuth redirect URI below."
                ),
            },
            {
                "id": 3,
                "title": "Add yourself as admin/tester",
                "body": (
                    "App roles → Add People → your Facebook account as Administrator. "
                    "Development mode is enough for YOUR Pages and IG Professional account — "
                    "App Review is only needed when other people connect."
                ),
            },
            {
                "id": 4,
                "title": "Paste App ID + Secret here",
                "body": (
                    "App settings → Basic → copy App ID and App Secret. Save below, "
                    "turn MOCK MODE off, then click Connect Instagram / Facebook."
                ),
            },
        ],
        "permissions": [
            "pages_show_list",
            "pages_read_engagement",
            "pages_manage_posts",
            "pages_manage_engagement",
            "pages_manage_metadata",
            "instagram_basic",
            "instagram_content_publish",
            "instagram_manage_comments",
            "instagram_manage_insights",
        ],
    }


@router.get("/meta")
def get_meta(request: Request, user: User = Depends(get_current_user)):
    return _status_payload(request)


@router.post("/meta")
def save_meta(data: MetaSaveIn, request: Request, user: User = Depends(get_current_user)):
    kwargs = {}
    if data.app_id is not None:
        kwargs["app_id"] = data.app_id
    if data.app_secret is not None:
        # empty string means "leave existing secret"
        if data.app_secret.strip():
            kwargs["app_secret"] = data.app_secret.strip()
    if data.verify_token is not None:
        kwargs["verify_token"] = data.verify_token
    if data.mock_mode is not None:
        kwargs["mock_mode"] = data.mock_mode
    if data.app_public_url is not None:
        kwargs["app_public_url"] = data.app_public_url.rstrip("/")
    if not kwargs:
        raise HTTPException(400, "Nothing to save")
    meta_store.save_overlay(**kwargs)
    out = _status_payload(request)
    out["saved"] = True
    return out


@router.post("/meta/test")
async def test_meta(data: MetaSaveIn | None = None, user: User = Depends(get_current_user)):
    """Hit Graph API with app-token (app_id|app_secret) to prove credentials work."""
    import httpx

    app_id = (data.app_id.strip() if data and data.app_id else "") or settings.META_APP_ID
    app_secret = (data.app_secret.strip() if data and data.app_secret else "") or settings.META_APP_SECRET
    if not app_id or not app_secret:
        raise HTTPException(400, "App ID and App Secret are required")
    version = settings.META_GRAPH_VERSION
    token = f"{app_id}|{app_secret}"
    url = f"https://graph.facebook.com/{version}/{app_id}"
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.get(url, params={"fields": "id,name", "access_token": token})
    except Exception as e:
        raise HTTPException(502, f"Could not reach Meta Graph API: {e}")
    body = {}
    try:
        body = r.json()
    except Exception:
        body = {"raw": r.text[:300]}
    if r.status_code != 200 or body.get("error"):
        err = (body.get("error") or {})
        msg = err.get("message") or r.text[:240]
        raise HTTPException(400, f"Meta rejected the credentials: {msg}")
    return {
        "ok": True,
        "app_id": body.get("id", app_id),
        "app_name": body.get("name", ""),
        "graph_version": version,
        "message": f"Credentials work — Meta app “{body.get('name') or app_id}” is reachable.",
    }
