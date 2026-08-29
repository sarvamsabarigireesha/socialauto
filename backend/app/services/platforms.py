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
    def __init__(self, ok: bool, platform_post_id: str = "", error: str = ""):
        self.ok = ok
        self.platform_post_id = platform_post_id
        self.error = error


class FetchResult:
    def __init__(self, comments: list[dict], metrics: dict):
        self.comments = comments          # [{"external_id","author","text"}]
        self.metrics = metrics            # {likes, comments_count, shares, impressions, reach}


# ---------------------------------------------------------------- mock clients
class _MockClient:
    """Simulates a social platform with random but realistic data."""

    async def publish(self, account: Account, caption: str, media_url: str) -> PublishResult:
        await _sleep()
        pid = f"mock_{account.platform.value}_{random.randint(10**8, 10**9)}"
        return PublishResult(True, platform_post_id=pid)

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

    async def publish(self, account: Account, caption: str, media_url: str) -> PublishResult:
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


class _XClient:
    """X (Twitter) API v2."""
    async def publish(self, account: Account, caption: str, media_url: str) -> PublishResult:
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


class _LinkedInClient:
    async def publish(self, account: Account, caption: str, media_url: str) -> PublishResult:
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


_CLIENTS = {
    Platform.instagram: _MetaClient,
    Platform.facebook: _MetaClient,
    Platform.x: _XClient,
    Platform.linkedin: _LinkedInClient,
}


def get_client(platform: Platform):
    if settings.MOCK_MODE:
        return _MockClient()
    return _CLIENTS[platform]()


async def publish_post(account: Account, caption: str, media_url: str) -> PublishResult:
    return await get_client(account.platform).publish(account, caption, media_url)


async def fetch_post(account: Account, platform_post_id: str) -> FetchResult:
    return await get_client(account.platform).fetch(account, platform_post_id)
