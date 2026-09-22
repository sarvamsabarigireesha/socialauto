"""Platform clients - FINAL FIXED for FB Page + IG Business"""

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

# mock client same as yours - keep it
class _MockClient(Client):
    async def publish(self, account: Account, caption: str, media_url: str, post_type: str = "feed") -> PublishResult:
        await _sleep()
        pid = f"mock_{account.platform.value}_{random.randint(10**8, 10**9)}"
        return PublishResult(True, platform_post_id=pid)
    async def reply_to_comment(self, account, platform_post_id, external_comment_id, text) -> bool:
        await _sleep(); return True
    async def list_recent_videos(self, account):
        from datetime import timedelta
        now = datetime.now(timezone.utc)
        return [
            {"id": f"mock_yt_{account.id}_v1", "title": "Sabarimala Live — latest darshanam 🚩", "published_at": (now - timedelta(days=2)).isoformat()},
            {"id": f"mock_yt_{account.id}_v2", "title": "Ayyappa Swamy devotional songs 🕉", "published_at": (now - timedelta(days=5)).isoformat()},
        ]
    async def fetch(self, account: Account, platform_post_id: str) -> FetchResult:
        await _sleep()
        n = random.randint(0, 4)
        sample = [("priya_99", "This is amazing! 🔥"),("rahul.k", "How do I get this?"),("design_divya", "Love the content ❤")]
        comments = [{"external_id": f"c_{random.randint(10**6,10**7)}", "author": a, "text": t} for (a,t) in random.sample(sample, k=min(n,len(sample)))]
        likes = random.randint(20, 900)
        metrics = {"likes": likes, "comments_count": likes // 30 + n, "shares": random.randint(0, likes // 10), "impressions": likes * 12, "reach": likes * 8}
        return FetchResult(comments, metrics)

async def _sleep():
    import asyncio; await asyncio.sleep(0.05)

# ---------------------------------------------------------------- FIXED META CLIENT
class _MetaClient:
    BASE = "https://graph.facebook.com"
    def _v(self): return f"{self.BASE}/{settings.META_GRAPH_VERSION}"

    async def publish(self, account: Account, caption: str, media_url: str, post_type: str = "feed") -> PublishResult:
        try:
            caption = caption or ""
            media_url = (media_url or "").strip()
            # Fix relative URLs
            if media_url and not media_url.startswith(("http://","https://")):
                media_url = (settings.APP_PUBLIC_URL or "").rstrip("/") + (media_url if media_url.startswith("/") else "/" + media_url)

            async with httpx.AsyncClient(timeout=120) as c:
                # ========== FACEBOOK PAGE ==========
                if account.platform == Platform.facebook:
                    page_id = account.external_id
                    token = account.access_token
                    if media_url and media_url.lower().endswith(('.jpg','.jpeg','.png','.webp')):
                        r = await c.post(f"{self._v()}/{page_id}/photos", data={
                            "url": media_url, "caption": caption, "access_token": token
                        })
                    else:
                        # video or text
                        if media_url and media_url.lower().endswith(('.mp4','.mov')):
                            # Facebook video - needs video upload flow, fallback to feed with link
                            r = await c.post(f"{self._v()}/{page_id}/videos", data={
                                "file_url": media_url, "description": caption, "access_token": token
                            })
                        else:
                            r = await c.post(f"{self._v()}/{page_id}/feed", data={
                                "message": caption, "link": media_url if media_url else "", "access_token": token
                            })
                    print(f"FB PUBLISH {r.status_code}: {r.text[:2000]}", flush=True)
                    r.raise_for_status()
                    return PublishResult(True, platform_post_id=r.json().get("id",""))

                # ========== INSTAGRAM BUSINESS - CORRECT FLOW ==========
                else: # Instagram
                    ig_id = account.external_id
                    token = account.access_token
                    if not media_url:
                        return PublishResult(False, error="Instagram requires a public image/video URL (https://). Text-only not supported.")

                    is_video = post_type.lower() in ('video','reel','short') or media_url.lower().endswith(('.mp4','.mov','.m4v','.webm'))

                    # Step 1: Create container
                    if is_video:
                        media_type = "REELS" if post_type.lower() in ('reel','short') else "VIDEO"
                        payload = {
                            "media_type": media_type,
                            "video_url": media_url,
                            "caption": caption,
                            "access_token": token
                        }
                        if media_type == "REELS":
                            payload["share_to_feed"] = "true"
                        r = await c.post(f"{self._v()}/{ig_id}/media", data=payload)
                    else:
                        r = await c.post(f"{self._v()}/{ig_id}/media", data={
                            "image_url": media_url,
                            "caption": caption,
                            "access_token": token
                        })

                    print(f"IG CREATE {r.status_code}: {r.text[:2000]}", flush=True)
                    if r.status_code!= 200:
                        return PublishResult(False, error=f"IG create failed: {r.text[:1000]}")
                    creation_id = r.json().get("id")
                    if not creation_id:
                        return PublishResult(False, error=f"No creation_id: {r.text[:1000]}")

                    # Step 2: Wait for video
                    if is_video:
                        import asyncio
                        for _ in range(24):
                            rs = await c.get(f"{self._v()}/{creation_id}", params={"fields":"status_code","access_token":token})
                            sc = rs.json().get("status_code")
                            print(f"IG status: {sc}", flush=True)
                            if sc == "FINISHED": break
                            if sc in ("ERROR","EXPIRED"):
                                return PublishResult(False, error=f"IG video processing failed: {rs.text[:800]}")
                            await asyncio.sleep(5)

                    # Step 3: Publish
                    r2 = await c.post(f"{self._v()}/{ig_id}/media_publish", data={
                        "creation_id": creation_id, "access_token": token
                    })
                    print(f"IG PUBLISH {r2.status_code}: {r2.text[:2000]}", flush=True)
                    r2.raise_for_status()
                    return PublishResult(True, platform_post_id=r2.json().get("id",""))

        except httpx.HTTPStatusError as e:
            err_text = e.response.text[:1500] if e.response else str(e)
            print(f"META HTTP ERROR: {err_text}", flush=True)
            return PublishResult(False, error=f"Meta error: {e.response.status_code if e.response else ''} {err_text[:800]}")
        except Exception as e:
            import traceback
            print(traceback.format_exc(), flush=True)
            return PublishResult(False, error=f"Meta error: {e}")

    async def fetch(self, account: Account, platform_post_id: str) -> FetchResult:
        try:
            async with httpx.AsyncClient(timeout=30) as c:
                r = await c.get(f"{self._v()}/{platform_post_id}", params={
                    "fields": "like_count,comments_count,shares,comments{from,text}",
                    "access_token": account.access_token,
                })
                r.raise_for_status()
                d = r.json()
                comments = [{"external_id": cm.get("id",""), "author": (cm.get("from") or {}).get("name","someone"), "text": cm.get("text","")} for cm in d.get("comments",{}).get("data",[])]
                return FetchResult(comments, {"likes": d.get("like_count",0), "comments_count": d.get("comments_count",len(comments)), "shares": 0, "impressions":0, "reach":0})
        except Exception as e:
            return FetchResult([], {"error": str(e)})

    async def reply_to_comment(self, account: Account, platform_post_id: str, external_comment_id: str, text: str) -> bool:
        try:
            async with httpx.AsyncClient(timeout=30) as c:
                r = await c.post(f"{self._v()}/{external_comment_id}/replies", data={"message": text, "access_token": account.access_token})
                r.raise_for_status(); return True
        except: return False

    async def list_recent_videos(self, account: Account) -> list[dict]:
        is_ig = account.platform == Platform.instagram
        try:
            async with httpx.AsyncClient(timeout=30) as c:
                if is_ig:
                    r = await c.get(f"{self._v()}/{account.external_id}/media", params={"fields":"id,caption,media_url,thumbnail_url,timestamp","limit":50,"access_token":account.access_token})
                else:
                    r = await c.get(f"{self._v()}/{account.external_id}/posts", params={"fields":"id,message,full_picture,created_time","limit":50,"access_token":account.access_token})
                if r.status_code!= 200: raise RuntimeError(f"Meta {r.status_code}: {r.text[:200]}")
                out=[]
                for it in r.json().get("data",[]):
                    out.append({"id":it["id"],"title":(it.get("caption") or it.get("message") or "post")[:120],"published_at":it.get("timestamp") or it.get("created_time") or "","thumb":it.get("thumbnail_url") or it.get("full_picture") or ""})
                return out
        except Exception: raise

# Keep your YouTube + Manual clients same as before (copy from your file)
async def _google_refresh_token(account: Account) -> str:
    if not getattr(account, "refresh_token", ""):
        raise RuntimeError("Google session expired - re-connect YouTube")
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post("https://oauth2.googleapis.com/token", data={
            "grant_type": "refresh_token", "refresh_token": account.refresh_token,
            "client_id": settings.GOOGLE_CLIENT_ID, "client_secret": settings.GOOGLE_CLIENT_SECRET})
        if r.status_code!= 200:
            raise RuntimeError(f"Google token refresh failed {r.status_code}: {r.text[:150]}")
        account.access_token = r.json()["access_token"]
        return account.access_token

class _YouTubeClient(Client):
    BASE = "https://www.googleapis.com/youtube/v3"
    UPLOAD = "https://www.googleapis.com/upload/youtube/v3"
    async def _req(self, method: str, url: str, account: Account, retry: bool = True, **kw):
        async with httpx.AsyncClient(timeout=kw.pop("_timeout", 30)) as c:
            r = await c.request(method, url, headers={"Authorization": f"Bearer {account.access_token}"}, **kw)
            if r.status_code in (401, 403) and retry:
                await _google_refresh_token(account)
                return await self._req(method, url, account, retry=False, **kw)
            return r
    async def publish(self, account: Account, caption: str, media_url: str, post_type: str = "feed") -> PublishResult:
        if post_type == "community" or (post_type == "feed" and media_url and not str(media_url).lower().endswith((".mp4",".mov",".m4v",".webm"))):
            return PublishResult(False, manual=True, error="MANUAL: YouTube Community posts can't be published via API. Open studio.youtube.com -> Create post")
        if not media_url:
            return PublishResult(False, error="YouTube: pick a VIDEO file for a Short/Video upload.")
        try:
            title, desc = caption[:100], caption
            if post_type == "short": title = (caption[:90] + " #Shorts")[:100]; desc = caption if "#Shorts" in caption else caption + "\n\n#Shorts"
            import json, os
            from..config import DATA_DIR
            if str(media_url).startswith(("http://","https://")):
                async with httpx.AsyncClient(timeout=180) as c0:
                    v = await c0.get(media_url); v.raise_for_status()
                    video_bytes, ctype = v.content, v.headers.get("content-type","video/mp4")
            else:
                local = str(media_url).split("/media/",1)[-1]
                fpath = DATA_DIR / "media" / local
                if not fpath.exists(): return PublishResult(False, error=f"YouTube: media file missing ({fpath.name})")
                video_bytes = fpath.read_bytes(); ctype="video/mp4"
            async with httpx.AsyncClient(timeout=180) as c:
                init = await c.post(f"{self.UPLOAD}/videos?uploadType=resumable&part=snippet,status", headers={"Authorization": f"Bearer {account.access_token}","Content-Type":"application/json"}, content=json.dumps({"snippet":{"title":title,"description":desc,"categoryId":"22"},"status":{"privacyStatus":"public","selfDeclaredMadeForKids":False}}))
                if init.status_code in (401,403):
                    await _google_refresh_token(account)
                    init = await c.post(f"{self.UPLOAD}/videos?uploadType=resumable&part=snippet,status", headers={"Authorization": f"Bearer {account.access_token}","Content-Type":"application/json"}, content=json.dumps({"snippet":{"title":title,"description":desc,"categoryId":"22"},"status":{"privacyStatus":"public","selfDeclaredMadeForKids":False}}))
                if init.status_code not in (200,201): return PublishResult(False, error=f"YouTube upload init failed ({init.status_code}): {init.text[:300]}")
                up_url = init.headers["location"]
                done = await c.put(up_url, content=video_bytes, headers={"Content-Type": ctype,"Authorization": f"Bearer {account.access_token}"})
                if done.status_code not in (200,201): return PublishResult(False, error=f"YouTube upload failed ({done.status_code}): {done.text[:300]}")
                return PublishResult(True, platform_post_id=done.json()["id"])
        except Exception as e: return PublishResult(False, error=f"YouTube error: {e}")
    async def fetch(self, account: Account, platform_post_id: str) -> FetchResult:
        try:
            r = await self._req("GET", f"{self.BASE}/commentThreads", account, params={"part":"snippet","videoId":platform_post_id,"maxResults":20,"order":"time"})
            if r.status_code!= 200: return FetchResult([], {"error": f"comments {r.status_code}: {r.text[:150]}"})
            comments=[];
            for it in r.json().get("items",[]):
                sn=it["snippet"]["topLevelComment"]["snippet"]
                comments.append({"external_id":it["snippet"]["topLevelComment"]["id"],"author":sn.get("authorDisplayName","viewer"),"avatar":sn.get("authorProfileImageUrl",""),"text":sn.get("textDisplay","")})
            r2 = await self._req("GET", f"{self.BASE}/videos", account, params={"part":"statistics","id":platform_post_id}); r2.raise_for_status()
            st=(r2.json().get("items") or [{}])[0].get("statistics",{}); views=int(st.get("viewCount",0))
            return FetchResult(comments, {"likes":int(st.get("likeCount",0)),"comments_count":int(st.get("commentCount",len(comments))),"shares":0,"impressions":views,"reach":views})
        except Exception as e: return FetchResult([], {"error": str(e)})
    async def reply_to_comment(self, account, platform_post_id, external_comment_id, text):
        try:
            r=await self._req("POST", f"{self.BASE}/comments?part=snippet", account, json={"snippet":{"parentId":external_comment_id,"textOriginal":text}})
            return r.status_code==200
        except: return False
    async def list_recent_videos(self, account):
        r=await self._req("GET", f"{self.BASE}/channels", account, params={"part":"contentDetails,snippet","id":account.external_id})
        if r.status_code!=200: raise RuntimeError(f"channels API {r.status_code}: {r.text[:200]}")
        items=r.json().get("items",[]);
        if not items: raise RuntimeError("No channel found")
        uploads=items[0]["contentDetails"].get("uploadsPlaylistId")
        if not uploads: return []
        out,page_token=[],None
        for _ in range(3):
            params={"part":"snippet","playlistId":uploads,"maxResults":50}
            if page_token: params["pageToken"]=page_token
            r2=await self._req("GET", f"{self.BASE}/playlistItems", account, params=params)
            if r2.status_code!=200: raise RuntimeError(f"playlistItems {r2.status_code}: {r2.text[:200]}")
            data=r2.json()
            for it in data.get("items",[]):
                sn=it["snippet"]; vid=sn.get("resourceId",{}).get("videoId","")
                if vid: out.append({"id":vid,"title":sn.get("title","video"),"published_at":sn.get("publishedAt",""),"thumb":(sn.get("thumbnails",{}) or {}).get("high",{}).get("url","")})
            page_token=data.get("nextPageToken")
            if not page_token: break
        return out

class _ManualHelperClient(Client):
    URLS={"moj":"https://mojapp.in","sharechat":"https://sharechat.com","threads":"https://threads.net"}
    async def publish(self, account: Account, caption: str, media_url: str, post_type: str = "feed")
