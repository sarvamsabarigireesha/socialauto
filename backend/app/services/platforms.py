"""Platform clients - FINAL FIXED for Render."""
import random
from datetime import datetime, timezone
import httpx
from..config import settings
from..models import Platform, Account

class PublishResult:
    def __init__(self, ok: bool, platform_post_id: str = "", error: str = "", manual: bool = False):
        self.ok = ok
        self.platform_post_id = platform_post_id
        self.error = error
        self.manual = manual

class FetchResult:
    def __init__(self, comments: list[dict], metrics: dict):
        self.comments = comments
        self.metrics = metrics

class Client:
    async def publish(self, account, caption: str, media_url: str, post_type: str = "feed") -> PublishResult:
        return PublishResult(False, error="not implemented")
    async def fetch(self, account, platform_post_id: str) -> FetchResult:
        return FetchResult([], {})
    async def reply_to_comment(self, account, platform_post_id: str, external_comment_id: str, text: str) -> bool:
        return False

class _MockClient(Client):
    async def publish(self, account, caption: str, media_url: str, post_type: str = "feed") -> PublishResult:
        import asyncio
        await asyncio.sleep(0.05)
        pid = f"mock_{account.platform.value}_{random.randint(10**8, 10**9)}"
        return PublishResult(True, platform_post_id=pid)
    async def fetch(self, account, platform_post_id: str) -> FetchResult:
        import asyncio
        await asyncio.sleep(0.05)
        likes = random.randint(20, 900)
        return FetchResult([], {"likes": likes, "comments_count": 0, "shares": 0, "impressions": likes*8, "reach": likes*5})
    async def reply_to_comment(self, account, platform_post_id, external_comment_id, text) -> bool:
        return True
    async def list_recent_videos(self, account):
        from datetime import timedelta
        now = datetime.now(timezone.utc)
        return [
            {"id": f"mock_{account.id}_v1", "title": "Sabarimala Live", "published_at": (now - timedelta(days=2)).isoformat()},
        ]

class _MetaClient(Client):
    BASE = "https://graph.facebook.com"
    def _v(self):
        return f"{self.BASE}/{settings.META_GRAPH_VERSION}"

    async def publish(self, account, caption: str, media_url: str, post_type: str = "feed") -> PublishResult:
        try:
            async with httpx.AsyncClient(timeout=120) as c:
                token = account.access_token
                v = self._v()
                caption = caption or ""
                media_url = (media_url or "").strip()
                if media_url and not media_url.startswith("http"):
                    base_url = (settings.APP_PUBLIC_URL or "").rstrip("/")
                    if media_url.startswith("/"):
                        media_url = base_url + media_url
                    else:
                        media_url = base_url + "/" + media_url

                if account.platform == Platform.instagram:
                    if not media_url.startswith("http"):
                        return PublishResult(False, error="Instagram needs public https URL")
                    is_video = post_type.lower() in ("video", "reel", "short")
                    if media_url.lower().endswith((".mp4", ".mov", ".m4v", ".webm")):
                        is_video = True
                    if is_video:
                        payload = {
                            "media_type": "REELS" if post_type in ("reel", "short") else "VIDEO",
                            "video_url": media_url,
                            "caption": caption,
                            "access_token": token
                        }
                        if post_type in ("reel", "short"):
                            payload["share_to_feed"] = "true"
                        r1 = await c.post(f"{v}/{account.external_id}/media", data=payload)
                    else:
                        payload = {
                            "image_url": media_url,
                            "caption": caption,
                            "access_token": token
                        }
                        r1 = await c.post(f"{v}/{account.external_id}/media", data=payload)
                    print(f"IG CREATE {r1.status_code}: {r1.text[:2000]}", flush=True)
                    if r1.status_code!= 200:
                        return PublishResult(False, error=f"IG create {r1.status_code}: {r1.text[:800]}")
                    creation_id = r1.json().get("id")
                    if is_video:
                        import asyncio
                        for _ in range(24):
                            rs = await c.get(f"{v}/{creation_id}", params={"fields": "status_code", "access_token": token})
                            sc = rs.json().get("status_code")
                            if sc == "FINISHED":
                                break
                            if sc in ("ERROR", "EXPIRED"):
                                return PublishResult(False, error=f"IG video {sc}")
                            await asyncio.sleep(5)
                    r2 = await c.post(f"{v}/{account.external_id}/media_publish", data={"creation_id": creation_id, "access_token": token})
                    print(f"IG PUBLISH {r2.status_code}: {r2.text[:2000]}", flush=True)
                    if r2.status_code!= 200:
                        return PublishResult(False, error=f"IG publish {r2.status_code}: {r2.text[:800]}")
                    return PublishResult(True, platform_post_id=r2.json().get("id", ""))
                else:
                    if media_url and media_url.startswith("http"):
                        r = await c.post(f"{v}/{account.external_id}/photos", data={"url": media_url, "caption": caption, "access_token": token})
                    else:
                        r = await c.post(f"{v}/{account.external_id}/feed", data={"message": caption, "access_token": token})
                    print(f"FB {r.status_code}: {r.text[:2000]}", flush=True)
                    if r.status_code!= 200:
                        return PublishResult(False, error=f"FB {r.status_code}: {r.text[:800]}")
                    pid = r.json().get("id") or r.json().get("post_id", "")
                    return PublishResult(True, platform_post_id=pid)
        except Exception as e:
            import traceback
            print(traceback.format_exc(), flush=True)
            return PublishResult(False, error=f"Meta error: {e}")

    async def fetch(self, account, platform_post_id: str) -> FetchResult:
        return FetchResult([], {})
    async def reply_to_comment(self, account, platform_post_id: str, external_comment_id: str, text: str) -> bool:
        try:
            async with httpx.AsyncClient(timeout=30) as c:
                r = await c.post(f"{self._v()}/{external_comment_id}/replies", data={"message": text, "access_token": account.access_token})
                return r.status_code == 200
        except Exception:
            return False
    async def list_recent_videos(self, account):
        return []

async def _google_refresh_token(account) -> str:
    if not getattr(account, "refresh_token", ""):
        raise RuntimeError("Google session expired")
    async with httpx.AsyncClient(timeout=30) as c:
        data = {
            "grant_type": "refresh_token",
            "refresh_token": account.refresh_token,
            "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET
        }
        r = await c.post("https://oauth2.googleapis.com/token", data=data)
        if r.status_code!= 200:
            raise RuntimeError(f"Google refresh failed {r.status_code}")
        account.access_token = r.json()["access_token"]
        return account.access_token

class _YouTubeClient(Client):
    BASE = "https://www.googleapis.com/youtube/v3"
    UPLOAD = "https://www.googleapis.com/upload/youtube/v3"
    async def publish(self, account, caption: str, media_url: str, post_type: str = "feed") -> PublishResult:
        return PublishResult(False, manual=True, error="MANUAL: YouTube needs video file")
    async def fetch(self, account, platform_post_id: str) -> FetchResult:
        return FetchResult([], {})
    async def reply_to_comment(self, account, platform_post_id: str, external_comment_id: str, text: str) -> bool:
        return False
    async def list_recent_videos(self, account):
        return []

class _ManualHelperClient(Client):
    async def publish(self, account, caption: str, media_url: str, post_type: str = "feed") -> PublishResult:
        return PublishResult(False, manual=True, error=f"MANUAL: {account.platform.value} no API")

_CLIENTS = {
    Platform.instagram: _MetaClient,
    Platform.facebook: _MetaClient,
    Platform.youtube: _YouTubeClient,
    Platform.threads: _ManualHelperClient,
    Platform.moj: _ManualHelperClient,
    Platform.sharechat: _ManualHelperClient
}

def get_client(platform: Platform):
    if settings.MOCK_MODE:
        return _MockClient()
    return _CLIENTS[platform]()

async def publish_post(account, caption: str, media_url: str, post_type: str = "feed") -> PublishResult:
    return await get_client(account.platform).publish(account, caption, media_url, post_type=post_type)

async def fetch_post(account, platform_post_id: str) -> FetchResult:
    return await get_client(account.platform).fetch(account, platform_post_id)
