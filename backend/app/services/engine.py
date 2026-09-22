import httpx
from ...config import settings
from ...models import Account

class Result:
    def __init__(self, ok, platform_post_id="", error=""):
        self.ok = ok
        self.platform_post_id = platform_post_id
        self.error = error

async def publish_post(account: Account, caption: str, media_url: str, post_type: str = "feed") -> Result:
    ig_id = account.external_id
    token = account.access_token
    v = settings.META_GRAPH_VERSION
    caption = caption or ""
    media_url = (media_url or "").strip()

    if not media_url.startswith("http"):
        return Result(False, error="Instagram requires a public https:// image/video URL. Text-only posts are not supported by Instagram API.")

    is_video = post_type.lower() in ('video','reel','short') or media_url.lower().endswith(('.mp4','.mov','.m4v'))

    async with httpx.AsyncClient(timeout=120) as c:
        try:
            # Step 1: Create container
            if is_video:
                data = {
                    "media_type": "REELS" if post_type.lower() in ('reel','short') else "VIDEO",
                    "video_url": media_url,
                    "caption": caption,
                    "access_token": token
                }
                if data["media_type"] == "REELS":
                    data["share_to_feed"] = "true"
                
                r1 = await c.post(f"https://graph.facebook.com/{v}/{ig_id}/media", data=data)
            else:
                r1 = await c.post(f"https://graph.facebook.com/{v}/{ig_id}/media", data={
                    "image_url": media_url,
                    "caption": caption,
                    "access_token": token
                })

            print(f"IG CREATE {r1.status_code}: {r1.text[:3000]}", flush=True)
            if r1.status_code != 200:
                return Result(False, error=f"Meta error: IG create failed {r1.status_code}: {r1.text[:800]}")
            
            creation_id = r1.json().get("id")
            if not creation_id:
                return Result(False, error=f"No creation_id: {r1.text}")

            # Step 2: Wait for video processing
            if is_video:
                import asyncio
                for _ in range(24): # 2 min wait
                    rs = await c.get(f"https://graph.facebook.com/{v}/{creation_id}", params={
                        "fields": "status_code", "access_token": token
                    })
                    sc = rs.json().get("status_code")
                    print(f"IG status check: {sc}", flush=True)
                    if sc == "FINISHED":
                        break
                    if sc in ("ERROR","EXPIRED"):
                        return Result(False, error=f"IG video processing failed: {rs.text[:800]}")
                    await asyncio.sleep(5)

            # Step 3: Publish
            r2 = await c.post(f"https://graph.facebook.com/{v}/{ig_id}/media_publish", data={
                "creation_id": creation_id,
                "access_token": token
            })
            print(f"IG PUBLISH {r2.status_code}: {r2.text[:3000]}", flush=True)
            if r2.status_code != 200:
                return Result(False, error=f"IG publish failed {r2.status_code}: {r2.text[:800]}")

            return Result(True, platform_post_id=r2.json().get("id",""))

        except Exception as e:
            import traceback
            print(traceback.format_exc(), flush=True)
            return Result(False, error=f"Instagram exception: {e}")

# For import
async def list_recent_videos(account: Account):
    return []

async def fetch_post(account: Account, platform_post_id: str):
    class R:
        comments = []
        metrics = {}
    return R()

def get_client(p): return None
async def reply_to_comment(*a, **k): return False
