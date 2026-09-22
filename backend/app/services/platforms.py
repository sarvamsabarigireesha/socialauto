class _MetaClient:
    BASE = "https://graph.facebook.com"
    def _v(self):
        return f"{self.BASE}/{settings.META_GRAPH_VERSION}"

    async def publish(self, account: Account, caption: str, media_url: str, post_type: str = "feed") -> PublishResult:
        try:
            async with httpx.AsyncClient(timeout=120) as c:
                token = account.access_token
                v = self._v()
                caption = caption or ""
                media_url = (media_url or "").strip()
                
                if media_url and not media_url.startswith(("http://","https://")):
                    media_url = (settings.APP_PUBLIC_URL or "").rstrip("/") + (media_url if media_url.startswith("/") else "/" + media_url)

                # INSTAGRAM
                if account.platform == Platform.instagram:
                    if not media_url.startswith("http"):
                        return PublishResult(False, error="Instagram needs public https image/video URL. Upload via Media Library first.")
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
                    if r1.status_code != 200:
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
                    if r2.status_code != 200:
                        return PublishResult(False, error=f"IG publish {r2.status_code}: {r2.text[:800]}")
                    return PublishResult(True, platform_post_id=r2.json().get("id",""))
                # FACEBOOK
                else:
                    if media_url and media_url.startswith("http"):
                        r = await c.post(f"{v}/{account.external_id}/photos", data={"url": media_url, "caption": caption, "access_token": token})
                    else:
                        r = await c.post(f"{v}/{account.external_id}/feed", data={"message": caption, "access_token": token})
                    print(f"FB {r.status_code}: {r.text[:2000]}", flush=True)
                    if r.status_code != 200:
                        return PublishResult(False, error=f"FB {r.status_code}: {r.text[:800]}")
                    return PublishResult(True, platform_post_id=r.json().get("id") or r.json().get("post_id",""))
        except Exception as e:
            import traceback; print(traceback.format_exc(), flush=True)
            return PublishResult(False, error=f"Meta error: {e}")
