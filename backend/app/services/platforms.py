"""Platform clients - FIXED for Render deploy."""
import random
from datetime import datetime, timezone
import httpx
from..config import settings
from..models import Platform, Account # <-- FIX: Account import added

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
        import asyncio; await asyncio.sleep(0.05)
        pid = f"mock_{account.platform.value}_{random.randint(10**8, 10**9)}"
        return PublishResult(True, platform_post_id=pid)
    async def reply_to_comment(self, account, platform_post_id, external_comment_id, text) -> bool:
        import asyncio; await asyncio.sleep(0.05); return True
    async def list_recent_videos(self, account):
        from datetime import timedelta
        now = datetime.now(timezone.utc)
        return [
            {"id": f"mock_yt_{account.id}_v1", "title": "Sabarimala Live — latest darshanam 🚩", "published_at": (now - timedelta(days=2)).isoformat()},
            {"id": f"mock_yt_{account.id}_v2", "title": "Ayyappa Swamy devotional songs 🕉", "published_at": (now - timedelta(days=5)).isoformat()},
        ]
    async def fetch(self, account, platform_post_id: str) -> FetchResult:
        import asyncio; await asyncio.sleep(0.05)
        n = random.randint(0, 2)
        comments = [{"external_id": f"c_{random.randint(10**6,10**7)}", "author": "priya_99", "text": "This is amazing! 🔥"} for _ in range(n)]
        likes = random.randint(20, 900)
        return FetchResult(comments, {"likes": likes, "comments_count": likes // 30 + n, "shares": 0, "impressions": likes*8, "reach": likes*5})

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
                if media_url and not media_url.startswith(("http://","https://")):
                    media_url = (settings.APP_PUBLIC_URL or "").rstrip("/") + (media_url if media_url.startswith("/") else "/" + media_url)

                if account.platform == Platform.instagram:
                    if not media_url.startswith("http"):
                        return PublishResult(False, error="Instagram requires public https image/video URL. Upload via Media Library first.")
                    is_video = post_type.lower() in ('video','reel','short') or media_url.lower().endswith(('.mp4','.mov','.m4v','.webm'))
                    if is_video:
                        r1 = await c.post(f"{v}/{account.external_id}/media", data={
                            "media_type": "REELS" if post_type in ('reel','short') else "VIDEO",
                            "video_url": media_url, "caption": caption, "access_token": token,
                            **({"share_to_feed":"true"} if post_type in ('reel','short') else {})
                        })
                    else:
                        r1 = await c.post(f"{v}/{account.external_id}/media", data={
                            "image_url": media_url, "caption": caption, "access_token": token,
                        })
                    print(f"IG CREATE {r1.status_code}: {r1.text[:2000]}", flush=True)
                    if r1.status_code!= 200:
                        return PublishResult(False, error=f"IG create {r1.status_code}: {r1.text[:800]}")
                    creation_id = r1.json().get("id")
                    if is_video:
                        import asyncio
                        for _ in range(24):
                            rs = await c.get(f"{v}/{creation_id}", params={"fields":"status_code","access_token":token})
                            sc = rs.json().get("status_code")
                            if sc == "FINISHED": break
                            if sc in ("ERROR","EXPIRED"): return PublishResult(False, error=f"IG video {sc}: {rs.text[:500]}")
                            await asyncio.sleep(5)
                    r2 = await c.post(f"{v}/{account.external_id}/media_publish", data={"creation_id": creation_id, "access_token": token})
                    print(f"IG PUBLISH {r2.status_code}: {r2.text[:2000]}", flush=True)
                    if r2.status_code!= 200:
                        return PublishResult(False, error=f"IG publish {r2.status_code}: {r2.text[:800]}")
                    return PublishResult(True, platform_post_id=r2.json().get("id",""))
                else:
                    if media_url and media_url.startswith("http"):
                        r = await c.post(f"{v}/{account.external_id}/photos", data={"url": media_url, "caption": caption, "access_token": token})
                    else:
                        r = await c.post(f"{v}/{account.external_id}/feed", data={"message": caption, "access_token": token})
                    print(f"FB {r.status_code}: {r.text[:2000]}", flush=True)
                    if r.status_code!= 200:
                        return PublishResult(False, error=f"FB {r.status_code}: {r.text[:800]}")
                    return PublishResult(True, platform_post_id=r.json().get("id") or r.json().get("post_id",""))
        except Exception as e:
            import traceback; print(traceback.format_exc(), flush=True)
            return PublishResult(False, error=f"Meta error: {e}")

    async def fetch(self, account, platform_post_id: str) -> FetchResult:
        try:
            async with httpx.AsyncClient(timeout=30) as c:
                r = await c.get(f"{self._v()}/{platform_post_id}", params={"fields": "like_count,comments_count,shares,comments{from,text}", "access_token": account.access_token})
                r.raise_for_status()
                d = r.json()
                comments = [{"external_id": cm.get("id",""), "author": (cm.get("from") or {}).get("name","someone"), "text": cm.get("text","")} for cm in d.get("comments",{}).get("data",[])]
                return FetchResult(comments, {"likes": d.get("like_count",0), "comments_count": d.get("comments_count", len(comments)), "shares": 0, "impressions": 0, "reach": 0})
        except Exception as e:
            return FetchResult([], {"error": str(e)})
    async def reply_to_comment(self, account, platform_post_id: str, external_comment_id: str, text: str) -> bool:
        try:
            async with httpx.AsyncClient(timeout=30) as c:
                r = await c.post(f"{self._v()}/{external_comment_id}/replies", data={"message": text, "access_token": account.access_token})
                r.raise_for_status(); return True
        except Exception: return False
    async def list_recent_videos(self, account):
        is_ig = account.platform == Platform.instagram
        try:
            async with httpx.AsyncClient(timeout=30) as c:
                if is_ig:
                    r = await c.get(f"{self._v()}/{account.external_id}/media", params={"fields": "id,caption,media_url,thumbnail_url,timestamp", "limit": 50, "access_token": account.access_token})
                else:
                    r = await c.get(f"{self._v()}/{account.external_id}/posts", params={"fields": "id,message,full_picture,created_time", "limit": 50, "access_token": account.access_token})
                if r.status_code!= 200: raise RuntimeError(f"Meta {r.status_code}: {r.text[:200]}")
                out = []
                for it in r.json().get("data", []):
                    out.append({"id": it["id"], "title": (it.get("caption") or it.get("message") or "post")[:120], "published_at": it.get("timestamp") or it.get("created_time") or "", "thumb": it.get("thumbnail_url") or it.get("full_picture") or ""})
                return out
        except Exception: raise

async def _google_refresh_token(account) -> str:
    if not getattr(account, "refresh_token", ""):
        raise RuntimeError("Google session expired, re-connect YouTube.")
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post("https://oauth2.googleapis.com/token", data={"grant_type": "refresh_token", "refresh_token": account.refresh_token, "client_id": settings.GOOGLE_CLIENT_ID, "client_secret": settings.G
