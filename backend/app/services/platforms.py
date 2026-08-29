"""Platform clients.

MOCK_MODE (default): every call is simulated locally so the whole app
works with zero API credentials. Set MOCK_MODE=false + tokens to go live.

Real publishing uses the official APIs:
  - Instagram/Facebook: Graph API media container -> publish flow
  - X: POST /2/tweets
  - LinkedIn: POST /rest/posts
"""
import random
from datetime import datetime, timezone

import httpx

from ..config import settings
from ..models import Platform, Account


class PublishResult:
    def __init__(self, ok: bool, platform_post_id: str = "", error: str = "",
                 manual: bool = False):
        self.ok = ok
        self.platform_post_id = platform_post_id
        self.error = error
        self.manual = manual  # API cannot post this — needs manual app action


class FetchResult:
    def __init__(self, comments: list[dict], metrics: dict):
        self.comments = comments          # [{"external_id","author","text"}]
        self.metrics = metrics            # {likes, comments_count, shares, impressions, reach}


class Client:
    """Base interface every platform client implements."""
    async def publish(self, account, caption: str, media_url: str,
                      post_type: str = "feed") -> PublishResult:
        return PublishResult(False, error="not implemented")

    async def fetch(self, account, platform_post_id: str) -> FetchResult:
        return FetchResult([], {})

    async def reply_to_comment(self, account, platform_post_id: str,
                               external_comment_id: str, text: str) -> bool:
        return False


# ---------------------------------------------------------------- mock clients
class _MockClient(Client):
    """Simulates a social platform with random but realistic data."""

    async def publish(self, account: Account, caption: str, media_url: str,
                      post_type: str = "feed") -> PublishResult:
        await _sleep()
        pid = f"mock_{account.platform.value}_{random.randint(10**8, 10**9)}"
        return PublishResult(True, platform_post_id=pid)

    async def reply_to_comment(self, account, platform_post_id, external_comment_id, text) -> bool:
        await _sleep()
        return True

    async def list_recent_videos(self, account):
        from datetime import datetime, timedelta, timezone
        await _sleep()
        now = datetime.now(timezone.utc)
        return [
            {"id": f"mock_yt_{account.id}_v1",
             "title": "Sabarimala Live — latest darshanam 🚩",
             "published_at": (now - timedelta(days=2)).isoformat()},
            {"id": f"mock_yt_{account.id}_v2",
             "title": "Ayyappa Swamy devotional songs 🕉",
             "published_at": (now - timedelta(days=5)).isoformat()},
        ]

    async def fetch(self, account: Account, platform_post_id: str) -> FetchResult:
        await _sleep()
        # random number of NEW comments (0-4) on each poll
        n = random.randint(0, 4)
        sample = [
            ("priya_99", "This is amazing! 🔥"),
            ("rahul.k", "How do I get this?"),
            ("design_divya", "Love the content ❤️"),
            ("startup_sai", "DM sent, check please"),
            ("fitwithneha", "Need this ASAP"),
            ("tech_tarun", "Great work, following now"),
            ("meera_writes", "Can you share more details?"),
        ]
        comments = [
            {"external_id": f"c_{random.randint(10**6,10**7)}",
             "author": a, "text": t}
            for (a, t) in random.sample(sample, k=min(n, len(sample)))
        ]
        likes = random.randint(20, 900)
        metrics = {
            "likes": likes,
            "comments_count": likes // 30 + n,
            "shares": random.randint(0, likes // 10),
            "impressions": likes * random.randint(5, 12),
            "reach": likes * random.randint(3, 8),
        }
        return FetchResult(comments, metrics)


async def _sleep():
    import asyncio
    await asyncio.sleep(0.05)


# ---------------------------------------------------------------- real clients
class _MetaClient:
    """Instagram Graph API / Facebook Pages API."""
    BASE = "https://graph.facebook.com"

    def _v(self):
        return f"{self.BASE}/{settings.META_GRAPH_VERSION}"

    async def publish(self, account: Account, caption: str, media_url: str,
                      post_type: str = "feed") -> PublishResult:
        try:
            async with httpx.AsyncClient(timeout=30) as c:
                if media_url:
                    # Instagram: 1) create media container  2) publish
                    r = await c.post(f"{self._v()}/{account.external_id}/media", data={
                        "image_url": media_url, "caption": caption,
                        "access_token": account.access_token,
                    })
                    r.raise_for_status()
                    creation_id = r.json()["id"]
                    r2 = await c.post(f"{self._v()}/{account.external_id}/media_publish", data={
                        "creation_id": creation_id,
                        "access_token": account.access_token,
                    })
                    r2.raise_for_status()
                    return PublishResult(True, platform_post_id=r2.json()["id"])
                else:
                    # Facebook page feed post
                    r = await c.post(f"{self._v()}/{account.external_id}/feed", data={
                        "message": caption, "access_token": account.access_token,
                    })
                    r.raise_for_status()
                    return PublishResult(True, platform_post_id=r.json()["id"])
        except Exception as e:
            return PublishResult(False, error=f"Meta error: {e}")

    async def fetch(self, account: Account, platform_post_id: str) -> FetchResult:
        try:
            async with httpx.AsyncClient(timeout=30) as c:
                r = await c.get(f"{self._v()}/{platform_post_id}", params={
                    "fields": "like_count,comments_count,shares,insights,comments{from,text}",
                    "access_token": account.access_token,
                })
                r.raise_for_status()
                d = r.json()
                comments = [
                    {"external_id": cm.get("id", ""),
                     "author": (cm.get("from") or {}).get("name", "someone"),
                     "text": cm.get("text", "")}
                    for cm in d.get("comments", {}).get("data", [])
                ]
                return FetchResult(comments, {
                    "likes": d.get("like_count", 0),
                    "comments_count": d.get("comments_count", len(comments)),
                    "shares": d.get("shares", {}).get("count", 0) if isinstance(d.get("shares"), dict) else 0,
                    "impressions": 0, "reach": 0,
                })
        except Exception as e:
            return FetchResult([], {"error": str(e)})

    async def reply_to_comment(self, account: Account, platform_post_id: str,
                               external_comment_id: str, text: str) -> bool:
        """Graph API: POST /{comment_id}/replies?message=..."""
        try:
            async with httpx.AsyncClient(timeout=30) as c:
                r = await c.post(f"{self._v()}/{external_comment_id}/replies", data={
                    "message": text, "access_token": account.access_token})
                r.raise_for_status()
                return True
        except Exception:
            return False


class _YouTubeClient(Client):
    """YouTube Data API v3 (Google Cloud free tier)."""

    async def publish(self, account: Account, caption: str, media_url: str,
                      post_type: str = "feed") -> PublishResult:
        # YouTube Community posts (image/text polls) have NO public API —
        # Google never opened it. Reminder mode like Buffer/Later do.
        if post_type == "community":
            return PublishResult(False, manual=True,
                error=("MANUAL: YouTube Community posts can't be published via API. "
                       "Open studio.youtube.com → Create → Create post (or your channel "
                       "→ Posts tab), paste the caption and upload the image, then post."))
        # video | short | feed — all upload a video file
        if not media_url:
            return PublishResult(False, error=("YouTube needs a video file/URL to upload "
                                               f"for a {post_type}. For text-only posts use "
                                               "a Community post (manual reminder)."))
        try:
            title = caption[:100]
            desc = caption
            if post_type == "short":
                title = (title[:90] + " #Shorts")[:100]
                desc = caption if "#Shorts" in caption else caption + "\n\n#Shorts"
            # Download the video, upload to YouTube.
            async with httpx.AsyncClient(timeout=180) as c:
                vid = await c.get(media_url)
                vid.raise_for_status()
                r = await c.post(
                    "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=multipart",
                    headers={"Authorization": f"Bearer {account.access_token}"},
                    files={"metadata": (None,
                            __import__("json").dumps({
                                "snippet": {"title": title, "description": desc,
                                            "categoryId": "22"},
                                "status": {"privacyStatus": "public",
                                           "selfDeclaredMadeForKids": False}}),
                            "application/json"),
                            "media": ("video.mp4", vid.content, "video/mp4")})
                if r.status_code != 200:
                    return PublishResult(False,
                        error=f"YouTube upload failed ({r.status_code}): {r.text[:300]}")
                return PublishResult(True, platform_post_id=r.json()["id"])
        except Exception as e:
            return PublishResult(False, error=f"YouTube error: {e}")

    async def fetch(self, account: Account, platform_post_id: str) -> FetchResult:
        try:
            async with httpx.AsyncClient(timeout=30) as c:
                h = {"Authorization": f"Bearer {account.access_token}"}
                # comments
                r = await c.get("https://www.googleapis.com/youtube/v3/commentThreads",
                                params={"part": "snippet", "videoId": platform_post_id,
                                        "maxResults": 20, "order": "time"}, headers=h)
                r.raise_for_status()
                comments = []
                for it in r.json().get("items", []):
                    sn = it["snippet"]["topLevelComment"]["snippet"]
                    comments.append({
                        "external_id": it["snippet"]["topLevelComment"]["id"],
                        "author": sn.get("authorDisplayName", "viewer"),
                        "text": sn.get("textDisplay", "")})
                # stats
                r2 = await c.get("https://www.googleapis.com/youtube/v3/videos",
                                 params={"part": "statistics", "id": platform_post_id}, headers=h)
                r2.raise_for_status()
                st = (r2.json().get("items") or [{}])[0].get("statistics", {})
                views = int(st.get("viewCount", 0))
                return FetchResult(comments, {
                    "likes": int(st.get("likeCount", 0)),
                    "comments_count": int(st.get("commentCount", len(comments))),
                    "shares": 0,
                    "impressions": views, "reach": views})
        except Exception as e:
            return FetchResult([], {"error": str(e)})

    async def reply_to_comment(self, account: Account, platform_post_id: str,
                               external_comment_id: str, text: str) -> bool:
        try:
            import json
            async with httpx.AsyncClient(timeout=30) as c:
                r = await c.post(
                    "https://www.googleapis.com/youtube/v3/comments?part=snippet",
                    headers={"Authorization": f"Bearer {account.access_token}",
                             "Content-Type": "application/json"},
                    json={"snippet": {"parentId": external_comment_id, "textOriginal": text}})
                r.raise_for_status()
                return True
        except Exception:
            return False

    async def list_recent_videos(self, account: Account) -> list[dict]:
        """Fetch the channel's most recent uploads (from live YouTube channel id)."""
        try:
            async with httpx.AsyncClient(timeout=30) as c:
                h = {"Authorization": f"Bearer {account.access_token}"}
                r = await c.get("https://www.googleapis.com/youtube/v3/channels",
                                params={"part": "contentDetails", "id": account.external_id},
                                headers=h)
                r.raise_for_status()
                uploads = (r.json()["items"][0]["contentDetails"]
                           .get("uploadsPlaylistId"))
                if not uploads:
                    return []
                out = []
                page_token = None
                for _ in range(3):  # up to ~150 recent videos
                    params = {"part": "snippet", "playlistId": uploads,
                              "maxResults": 50}
                    if page_token:
                        params["pageToken"] = page_token
                    r2 = await c.get("https://www.googleapis.com/youtube/v3/playlistItems",
                                     params=params, headers=h)
                    r2.raise_for_status()
                    data = r2.json()
                    for it in data.get("items", []):
                        sn = it["snippet"]
                        vid = sn.get("resourceId", {}).get("videoId", "")
                        if vid:
                            out.append({"id": vid, "title": sn.get("title", "video"),
                                        "published_at": sn.get("publishedAt", ""),
                                        "thumb": (sn.get("thumbnails", {}) or {}).get("high", {})
                                                  .get("url", "")})
                    page_token = data.get("nextPageToken")
                    if not page_token:
                        break
                return out
        except Exception:
            return []


class _XClient(Client):
    """X (Twitter) API v2."""
    async def publish(self, account: Account, caption: str, media_url: str,
                      post_type: str = "feed") -> PublishResult:
        try:
            async with httpx.AsyncClient(timeout=30) as c:
                r = await c.post(
                    "https://api.twitter.com/2/tweets",
                    json={"text": caption[:280]},
                    headers={"Authorization": f"Bearer {settings.X_BEARER_TOKEN}"},
                )
                r.raise_for_status()
                return PublishResult(True, platform_post_id=r.json()["data"]["id"])
        except Exception as e:
            return PublishResult(False, error=f"X error: {e}")

    async def fetch(self, account: Account, platform_post_id: str) -> FetchResult:
        # Real impl: GET /2/tweets/:id?expansions=attachments... + public metrics
        return FetchResult([], {"likes": 0, "comments_count": 0, "shares": 0,
                                "impressions": 0, "reach": 0})


class _LinkedInClient(Client):
    async def reply_to_comment(self, account: Account, platform_post_id, external_comment_id, text) -> bool:
        # LinkedIn Social Actions API — implement with POST /socialActions/{urn}/comments
        return True

    async def publish(self, account: Account, caption: str, media_url: str,
                      post_type: str = "feed") -> PublishResult:
        try:
            async with httpx.AsyncClient(timeout=30) as c:
                headers = {"Authorization": f"Bearer {settings.LINKEDIN_ACCESS_TOKEN}",
                           "X-Restli-Protocol-Version": "2.0.0"}
                r = await c.post("https://api.linkedin.com/v2/ugcPosts", headers=headers, json={
                    "author": f"urn:li:person:{account.external_id}",
                    "lifecycleState": "PUBLISHED",
                    "specificContent": {"com.linkedin.ugc.ShareContent": {
                        "shareCommentary": {"text": caption},
                        "shareMediaCategory": "NONE"}},
                    "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"},
                })
                r.raise_for_status()
                return PublishResult(True, platform_post_id=r.headers.get("x-restli-id", "li_post"))
        except Exception as e:
            return PublishResult(False, error=f"LinkedIn error: {e}")

    async def fetch(self, account: Account, platform_post_id: str) -> FetchResult:
        return FetchResult([], {"likes": 0, "comments_count": 0, "shares": 0,
                                "impressions": 0, "reach": 0})


class _ManualHelperClient(Client):
    """Platforms with NO public posting API (Moj, ShareChat) or API gated
    behind Meta app review (Threads). Posts become ready-to-publish reminders:
    caption + media copied, one click opens the app to finish manually."""

    URLS = {"moj": "https://mojapp.in",
            "sharechat": "https://sharechat.com",
            "threads": "https://threads.net"}

    async def publish(self, account: Account, caption: str, media_url: str,
                      post_type: str = "feed") -> PublishResult:
        url = self.URLS.get(account.platform.value, "")
        return PublishResult(False, manual=True, error=(
            f"MANUAL: {account.platform.value.capitalize()} has no public posting API. "
            f"Open {url or 'the app'} → create post, paste this caption and attach the "
            f"{'video' if post_type in ('video','short') else 'media'}, then publish. "
            "SocialAuto keeps it here so your calendar/stats stay in one place."))

    async def fetch(self, account: Account, platform_post_id: str) -> FetchResult:
        return FetchResult([], {})


_CLIENTS = {
    Platform.instagram: _MetaClient,
    Platform.facebook: _MetaClient,
    Platform.x: _XClient,
    Platform.linkedin: _LinkedInClient,
    Platform.youtube: _YouTubeClient,
    Platform.threads: _ManualHelperClient,
    Platform.moj: _ManualHelperClient,
    Platform.sharechat: _ManualHelperClient,
}


def get_client(platform: Platform):
    if settings.MOCK_MODE:
        return _MockClient()
    return _CLIENTS[platform]()


async def publish_post(account: Account, caption: str, media_url: str,
                        post_type: str = "feed") -> PublishResult:
    return await get_client(account.platform).publish(
        account, caption, media_url, post_type=post_type)


async def fetch_post(account: Account, platform_post_id: str) -> FetchResult:
    return await get_client(account.platform).fetch(account, platform_post_id)
