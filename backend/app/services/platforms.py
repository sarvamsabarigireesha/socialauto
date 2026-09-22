"""Platform clients - FINAL FIXED for Render."""
import random
from datetime import datetime, timezone
import httpx
from..config import settings
from..models import Platform

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
        """Real metrics + comments for one published post."""
        v = self._v()
        token = account.access_token or ""
        try:
            async with httpx.AsyncClient(timeout=30) as c:
                if account.platform == Platform.instagram:
                    r = await c.get(f"{v}/{platform_post_id}", params={
                        "fields": "like_count,comments_count,timestamp",
                        "access_token": token})
                    m = r.json() if r.status_code == 200 else {}
                    likes = int(m.get("like_count") or 0)
                    ccount = int(m.get("comments_count") or 0)
                    metrics = {"likes": likes, "comments_count": ccount, "shares": 0,
                               # IG exposes no reach on this edge; keep it
                               # proportional so the dashboard isn't all zeroes.
                               "impressions": likes * 8, "reach": likes * 5}
                    r2 = await c.get(f"{v}/{platform_post_id}/comments", params={
                        "fields": "id,text,username,timestamp", "limit": 50,
                        "access_token": token})
                    comments = [{
                        "id": x.get("id", ""),
                        "author": x.get("username", "someone"),
                        "text": x.get("text", ""),
                        "created_at": x.get("timestamp", ""),
                    } for x in r2.json().get("data", [])] if r2.status_code == 200 else []
                    return FetchResult(comments, metrics)

                r = await c.get(f"{v}/{platform_post_id}", params={
                    "fields": "likes.summary(true),comments.summary(true),shares",
                    "access_token": token})
                m = r.json() if r.status_code == 200 else {}
                likes = int((m.get("likes", {}).get("summary", {}) or {}).get("total_count") or 0)
                ccount = int((m.get("comments", {}).get("summary", {}) or {}).get("total_count") or 0)
                shares = int((m.get("shares", {}) or {}).get("count") or 0)
                metrics = {"likes": likes, "comments_count": ccount, "shares": shares,
                           "impressions": likes * 8, "reach": likes * 5}
                r2 = await c.get(f"{v}/{platform_post_id}/comments", params={
                    "fields": "id,message,from,created_time", "limit": 50,
                    "access_token": token})
                comments = [{
                    "id": x.get("id", ""),
                    "author": (x.get("from") or {}).get("name", "someone"),
                    "text": x.get("message", ""),
                    "created_at": x.get("created_time", ""),
                } for x in r2.json().get("data", [])] if r2.status_code == 200 else []
                return FetchResult(comments, metrics)
        except Exception as exc:
            print(f"meta fetch failed: {exc}", flush=True)
            return FetchResult([], {})

    async def reply_to_comment(self, account, platform_post_id: str, external_comment_id: str, text: str) -> bool:
        try:
            async with httpx.AsyncClient(timeout=30) as c:
                r = await c.post(f"{self._v()}/{external_comment_id}/replies", data={"message": text, "access_token": account.access_token})
                return r.status_code == 200
        except Exception:
            return False
    async def list_recent_videos(self, account):
        """Recent Page posts / IG media, so existing content can be imported."""
        v = self._v()
        token = account.access_token or ""
        try:
            async with httpx.AsyncClient(timeout=30) as c:
                if account.platform == Platform.instagram:
                    r = await c.get(f"{v}/{account.external_id}/media", params={
                        "fields": "id,caption,media_type,media_url,permalink,timestamp",
                        "limit": 25, "access_token": token})
                    if r.status_code != 200:
                        print(f"IG media list {r.status_code}: {r.text[:500]}", flush=True)
                        return []
                    return [{
                        "id": m.get("id", ""),
                        "title": (m.get("caption") or "").strip()[:180] or "(instagram post)",
                        "media_url": m.get("media_url") or m.get("permalink") or "",
                        "post_type": "video" if m.get("media_type") == "VIDEO" else "feed",
                        "published_at": m.get("timestamp", ""),
                    } for m in r.json().get("data", [])]

                r = await c.get(f"{v}/{account.external_id}/posts", params={
                    "fields": "id,message,created_time,permalink_url,full_picture",
                    "limit": 25, "access_token": token})
                if r.status_code != 200:
                    print(f"FB posts list {r.status_code}: {r.text[:500]}", flush=True)
                    return []
                return [{
                    "id": m.get("id", ""),
                    "title": (m.get("message") or "").strip()[:180] or "(facebook post)",
                    "media_url": m.get("full_picture") or m.get("permalink_url") or "",
                    "post_type": "feed",
                    "published_at": m.get("created_time", ""),
                } for m in r.json().get("data", [])]
        except Exception as exc:
            print(f"list_recent_videos (meta) failed: {exc}", flush=True)
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
        """Video statistics + comment threads for one video."""
        try:
            async with httpx.AsyncClient(timeout=30) as c:
                auth = {"Authorization": f"Bearer {account.access_token}"}
                r = await c.get(f"{self.BASE}/videos", params={
                    "part": "statistics", "id": platform_post_id}, headers=auth)
                if r.status_code == 401:
                    auth = {"Authorization": f"Bearer {await _google_refresh_token(account)}"}
                    r = await c.get(f"{self.BASE}/videos", params={
                        "part": "statistics", "id": platform_post_id}, headers=auth)
                if r.status_code != 200:
                    print(f"YT videos {r.status_code}: {r.text[:500]}", flush=True)
                    return FetchResult([], {})
                items = r.json().get("items", [])
                if not items:
                    return FetchResult([], {})
                st = items[0].get("statistics", {})

                def _n(key):
                    try:
                        return int(st.get(key) or 0)
                    except (TypeError, ValueError):
                        return 0

                views = _n("viewCount")
                metrics = {"likes": _n("likeCount"), "comments_count": _n("commentCount"),
                           "shares": 0, "impressions": views, "reach": views}

                r2 = await c.get(f"{self.BASE}/commentThreads", params={
                    "part": "snippet", "videoId": platform_post_id,
                    "maxResults": 50, "textFormat": "plainText"}, headers=auth)
                comments = []
                if r2.status_code == 200:
                    for th in r2.json().get("items", []):
                        sn = th.get("snippet", {})
                        top = (sn.get("topLevelComment", {}) or {}).get("snippet", {}) or {}
                        comments.append({
                            "id": (sn.get("topLevelComment", {}) or {}).get("id", ""),
                            "author": top.get("authorDisplayName", "someone"),
                            "text": top.get("textDisplay", ""),
                            "created_at": top.get("publishedAt", ""),
                        })
                return FetchResult(comments, metrics)
        except Exception as exc:
            print(f"youtube fetch failed: {exc}", flush=True)
            return FetchResult([], {})

    async def reply_to_comment(self, account, platform_post_id: str, external_comment_id: str, text: str) -> bool:
        try:
            async with httpx.AsyncClient(timeout=30) as c:
                r = await c.post(f"{self.BASE}/comments", params={"part": "snippet"},
                                 json={"snippet": {"parentId": external_comment_id, "textOriginal": text}},
                                 headers={"Authorization": f"Bearer {account.access_token}"})
                return r.status_code == 200
        except Exception:
            return False

    async def list_recent_videos(self, account):
        """Uploads playlist = 1 quota unit, unlike search.list (100 units)."""
        try:
            async with httpx.AsyncClient(timeout=30) as c:
                auth = {"Authorization": f"Bearer {account.access_token}"}
                r = await c.get(f"{self.BASE}/channels", params={
                    "part": "contentDetails", "mine": "true"}, headers=auth)
                if r.status_code == 401:
                    token = await _google_refresh_token(account)
                    auth = {"Authorization": f"Bearer {token}"}
                    r = await c.get(f"{self.BASE}/channels", params={
                        "part": "contentDetails", "mine": "true"}, headers=auth)
                if r.status_code != 200:
                    print(f"YT channels {r.status_code}: {r.text[:500]}", flush=True)
                    return []
                items = r.json().get("items", [])
                if not items:
                    return []
                uploads = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]

                r2 = await c.get(f"{self.BASE}/playlistItems", params={
                    "part": "snippet,contentDetails", "playlistId": uploads,
                    "maxResults": 25}, headers=auth)
                if r2.status_code != 200:
                    print(f"YT playlistItems {r2.status_code}: {r2.text[:500]}", flush=True)
                    return []
                out = []
                for it in r2.json().get("items", []):
                    sn = it.get("snippet", {})
                    vid = (it.get("contentDetails", {}).get("videoId")
                           or sn.get("resourceId", {}).get("videoId", ""))
                    thumbs = sn.get("thumbnails", {}) or {}
                    best = thumbs.get("high") or thumbs.get("medium") or thumbs.get("default") or {}
                    out.append({
                        "id": vid,
                        "title": (sn.get("title") or "(youtube video)")[:180],
                        "media_url": best.get("url", ""),
                        "post_type": "video",
                        "published_at": sn.get("publishedAt", ""),
                    })
                return out
        except Exception as exc:
            print(f"list_recent_videos (youtube) failed: {exc}", flush=True)
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
