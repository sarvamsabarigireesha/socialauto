"""Contract tests: do our platform clients speak the REAL Meta/Google APIs?

No credentials needed — httpx's MockTransport plays back realistic Graph API
and YouTube Data API responses, so a wrong field name or a wrong endpoint is
caught here instead of during a live post.

Run:  python3 contract_test.py
"""
import asyncio
import json
import sys
import types
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import httpx  # noqa: E402

from app.models import Platform  # noqa: E402
from app.services import platforms  # noqa: E402
from app.config import settings  # noqa: E402

PASS, FAIL = [], []
CALLS = []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  ✅ " if cond else "  ❌ ") + name + (f"   {extra}" if extra and not cond else ""))


def acc(platform, external_id, token="TOKEN"):
    """A stand-in for a DB Account row."""
    return types.SimpleNamespace(
        id=1, user_id=1, platform=platform, external_id=external_id,
        display_name="@test", access_token=token, refresh_token="REFRESH",
        auto_comment=True, comment_template="", posting_slots=[], posting_goal=7)


_real_async_client = httpx.AsyncClient


def install(handler):
    """Route every httpx.AsyncClient through our fake transport."""
    CALLS.clear()

    def factory(*a, **kw):
        kw["transport"] = httpx.MockTransport(handler)
        return _real_async_client(*a, **kw)

    httpx.AsyncClient = factory


def restore():
    httpx.AsyncClient = _real_async_client


# --------------------------------------------------------------- fake backend
def graph_handler(request: httpx.Request) -> httpx.Response:
    path, method = request.url.path, request.method
    CALLS.append((method, path))
    body = request.content.decode()

    if request.url.host == "graph.threads.net":
        return httpx.Response(200, json={"id": "th_1", "access_token": "t"})

    if path.endswith("/media") and method == "POST":
        if "REELS" in body:
            return httpx.Response(200, json={"id": "creation_reel"})
        return httpx.Response(200, json={"id": "creation_img"})
    if "/creation" in path and method == "GET":
        # container status poll — say FINISHED straight away so tests stay fast
        return httpx.Response(200, json={"status_code": "FINISHED"})
    if path.endswith("/media_publish"):
        return httpx.Response(200, json={"id": "17890000000000001"})
    if path.endswith("/feed"):
        return httpx.Response(200, json={"id": "pageid_998877"})
    if path.endswith("/photos"):
        return httpx.Response(200, json={"id": "photoid_1", "post_id": "pageid_1"})

    # fetch(): IG metrics + comments
    if "like_count" in request.url.params.get("fields", ""):
        return httpx.Response(200, json={"like_count": 321, "comments_count": 12,
                                         "timestamp": "2026-08-01T10:00:00+0000"})
    fb_comments = "message" in request.url.params.get("fields", "")
    if path.endswith("/comments") and method == "GET" and not fb_comments:
        return httpx.Response(200, json={"data": [
            {"id": "c1", "username": "aditi", "text": "How much?", "timestamp": "2026-08-01T11:00:00+0000"},
            {"id": "c2", "username": "rahul", "text": "Love it", "timestamp": "2026-08-01T11:05:00+0000"},
        ]})
    if "likes.summary" in request.url.params.get("fields", ""):
        return httpx.Response(200, json={"likes": {"summary": {"total_count": 88}},
                                         "comments": {"summary": {"total_count": 4}},
                                         "shares": {"count": 9}})
    if path.endswith("/comments") and method == "GET" and fb_comments:
        return httpx.Response(200, json={"data": [
            {"id": "fc1", "message": "Nice", "from": {"name": "Priya"}}]})

    # list_recent_videos(): IG media edge
    if path.endswith("/media") and method == "GET":
        return httpx.Response(200, json={"data": [{
            "id": "ig_media_1", "caption": "Old post 🍗", "media_type": "IMAGE",
            "media_url": "https://scontent.example/x.jpg",
            "permalink": "https://www.instagram.com/p/abc/",
            "timestamp": "2026-07-01T09:00:00+0000"}]})
    if path.endswith("/posts") and method == "GET":
        return httpx.Response(200, json={"data": [{
            "id": "fb_post_1", "message": "Old page post",
            "created_time": "2026-07-02T09:00:00+0000",
            "permalink_url": "https://facebook.com/1",
            "full_picture": "https://scontent.example/fb.jpg"}]})
    # token validity probe
    if path.endswith("/12760153"):
        return httpx.Response(200, json={"id": "12760153", "name": "Test Page"})
    return httpx.Response(200, json={"id": "me"})


def yt_handler(request: httpx.Request) -> httpx.Response:
    path, method = request.url.path, request.method
    CALLS.append((method, path))
    u = str(request.url)

    if path.endswith("/channels"):
        return httpx.Response(200, json={"items": [{
            "id": "UC_test", "snippet": {"title": "Foodie Tube"},
            "contentDetails": {"relatedPlaylists": {"uploads": "UU_test"}}}]})
    if path.endswith("/playlistItems"):
        return httpx.Response(200, json={"items": [{
            "snippet": {"title": "Sabarimala Live 🎥", "publishedAt": "2026-07-03T09:00:00Z",
                        "thumbnails": {"high": {"url": "https://i.ytimg.com/vi/abc/hq.jpg"}},
                        "resourceId": {"videoId": "abc123"}},
            "contentDetails": {"videoId": "abc123"}}]})
    if path.endswith("/videos") and method == "GET":
        return httpx.Response(200, json={"items": [{"id": "abc123", "statistics": {
            "viewCount": "1500", "likeCount": "120", "commentCount": "17"}}]})
    if path.endswith("/commentThreads"):
        thread = {"snippet": {"topLevelComment": {
            "id": "Ugx1",
            "snippet": {"authorDisplayName": "Meghana",
                        "textDisplay": "Super anna",
                        "publishedAt": "2026-07-04T09:00:00Z"}}}}
        return httpx.Response(200, json={"items": [thread]})
    if path.endswith("/comments") and method == "POST":
        return httpx.Response(200, json={"id": "reply_1"})
    if "/upload/youtube/v3/videos" in u and method == "POST":
        return httpx.Response(200, headers={"Location": "https://upload.example/session1"})
    if u.startswith("https://upload.example/session1") and method == "PUT":
        return httpx.Response(200, json={"id": "yt_video_42",
                                         "snippet": {"title": "test"}})
    return httpx.Response(200, json={})


def error_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(400, json={"error": {
        "message": "Invalid OAuth access token.", "type": "OAuthException", "code": 190}})


async def run():
    print("\n[Instagram — publish]")
    install(graph_handler)
    ig = acc(Platform.instagram, "IGID")
    res = await platforms.get_client(Platform.instagram).publish(
        ig, "Hello world 🌍", "https://cdn.example/pic.jpg")
    check("IG image publish succeeds", res.ok, res.error)
    check("IG returns the published media id", res.platform_post_id == "17890000000000001",
          res.platform_post_id)
    check("IG called /media then /media_publish",
          ("POST", "/v21.0/IGID/media") in CALLS and
          ("POST", "/v21.0/IGID/media_publish") in CALLS, str(CALLS))

    res = await platforms.get_client(Platform.instagram).publish(
        ig, "Reel time 🎬", "https://cdn.example/clip.mp4", post_type="short")
    check("IG reel publish succeeds (container + status poll + publish)", res.ok, res.error)
    check("IG reel polled the container status",
          any(c == ("GET", "/v21.0/creation_reel") for c in CALLS), str(CALLS))

    res = await platforms.get_client(Platform.instagram).publish(ig, "text only", "")
    check("IG rejects a text-only post with a helpful error",
          (not res.ok) and "public https" in res.error.lower(), res.error)

    print("\n[Meta — errors]")
    install(error_handler)
    res = await platforms.get_client(Platform.instagram).publish(
        ig, "x", "https://cdn.example/pic.jpg")
    check("Meta 400 surfaces the API message", (not res.ok) and
          "Invalid OAuth access token" in res.error, res.error)

    print("\n[Facebook — publish]")
    install(graph_handler)
    fb = acc(Platform.facebook, "PAGEID")
    res = await platforms.get_client(Platform.facebook).publish(fb, "Page post", "")
    check("FB text post uses /feed", res.ok and ("POST", "/v21.0/PAGEID/feed") in CALLS,
          res.error)
    res = await platforms.get_client(Platform.facebook).publish(
        fb, "Photo post", "https://cdn.example/p.jpg")
    check("FB photo post uses /photos", res.ok and ("POST", "/v21.0/PAGEID/photos") in CALLS,
          res.error)

    print("\n[Meta — read back]")
    install(graph_handler)
    fr = await platforms.get_client(Platform.instagram).fetch(ig, "POSTID")
    check("IG metrics parsed", fr.metrics.get("likes") == 321 and
          fr.metrics.get("comments_count") == 12, json.dumps(fr.metrics))
    check("IG comments parsed", len(fr.comments) == 2 and
          fr.comments[0]["author"] == "aditi", json.dumps(fr.comments[:1]))
    check("IG parser exposes text without parsing HTML",
          fr.comments[0]["text"] == "How much?", fr.comments[0]["text"])

    fr = await platforms.get_client(Platform.facebook).fetch(fb, "POSTID")
    check("FB metrics parsed", fr.metrics.get("likes") == 88 and
          fr.metrics.get("shares") == 9, json.dumps(fr.metrics))
    check("FB comments parsed", len(fr.comments) == 1)

    igc = platforms.get_client(Platform.instagram)
    vids = await igc.list_recent_videos(ig)
    check("IG existing content imported", len(vids) == 1 and
          vids[0]["id"] == "ig_media_1" and "Old post" in vids[0]["title"], str(vids))
    fbc = platforms.get_client(Platform.facebook)
    vids = await fbc.list_recent_videos(fb)
    check("FB existing content imported", len(vids) == 1 and vids[0]["id"] == "fb_post_1",
          str(vids))

    print("\n[YouTube — read back]")
    install(yt_handler)
    yt = acc(Platform.youtube, "UC_test")
    ytc = platforms.get_client(Platform.youtube)
    vids = await ytc.list_recent_videos(yt)
    check("YT uploads playlist parsed", len(vids) == 1 and vids[0]["id"] == "abc123",
          str(vids))
    check("YT thumbnail + date extracted",
          vids[0]["media_url"].startswith("https://i.ytimg.com") and
          vids[0]["published_at"] == "2026-07-03T09:00:00Z", str(vids[0]))
    check("YT used playlistItems, not the 100-unit search.list",
          any("/playlistItems" in p for _, p in CALLS) and
          not any("/search" in p for _, p in CALLS), str(CALLS))

    fr = await ytc.fetch(yt, "abc123")
    check("YT statistics parsed", fr.metrics.get("likes") == 120 and
          fr.metrics.get("impressions") == 1500, json.dumps(fr.metrics))
    check("YT commentThreads parsed", len(fr.comments) == 1 and
          fr.comments[0]["author"] == "Meghana", str(fr.comments))

    ok = await ytc.reply_to_comment(yt, "abc123", "Ugx1", "Thanks!")
    check("YT comment reply posts comments.insert", ok is True)

    print("\n[YouTube — upload]")
    settings.YOUTUBE_AUTO_UPLOAD = False
    res = await ytc.publish(yt, "Manual please", "https://cdn.example/v.mp4")
    check("YT stays manual when auto-upload is off", (not res.ok) and res.manual, res.error)

    def video_host(request):
        if request.url.host == "cdn.example":
            return httpx.Response(200, content=b"\x00" * 2048,
                                  headers={"content-type": "video/mp4"})
        return yt_handler(request)

    install(video_host)
    settings.YOUTUBE_AUTO_UPLOAD = True
    res = await ytc.publish(yt, "My new video 🎬\n\nFull description here",
                            "https://cdn.example/v.mp4")
    check("YT resumable upload succeeds", res.ok, res.error)
    check("YT returns the new video id", res.platform_post_id == "yt_video_42",
          res.platform_post_id)
    check("YT opened a resumable session then PUT it",
          any("upload/youtube/v3/videos" in p and m == "POST" for m, p in CALLS) and
          any(p.startswith("/session1") and m == "PUT" for m, p in CALLS), str(CALLS))
    settings.YOUTUBE_AUTO_UPLOAD = False

    print("\n[Meta — missing media]")
    install(graph_handler)
    before = len(CALLS)
    saved_public = settings.APP_PUBLIC_URL
    settings.APP_PUBLIC_URL = "https://socialauto.onrender.com"

    res = await platforms.get_client(Platform.instagram).publish(
        ig, "wiped", "/media/u3/75bb14f21a47.mp4")
    check("a wiped local media file fails fast with an actionable error",
          (not res.ok) and "missing on this server" in res.error, res.error)
    check("no HTTP call was made for the dead URL", len(CALLS) == before, str(CALLS))
    check("the error explains the ephemeral-disk cause",
          "redeploy" in res.error and "/media/" in res.error, res.error)

    res = await platforms.get_client(Platform.instagram).publish(
        ig, "wiped", "https://socialauto.onrender.com/media/u3/gone.jpg")
    check("the same check works for an absolute URL of our own host",
          (not res.ok) and "missing on this server" in res.error, res.error)

    settings.APP_PUBLIC_URL = ""
    res = await platforms.get_client(Platform.instagram).publish(
        ig, "wiped", "/media/u3/75bb14f21a47.mp4")
    check("without APP_PUBLIC_URL it says exactly that instead",
          (not res.ok) and "APP_PUBLIC_URL is not set" in res.error, res.error)
    settings.APP_PUBLIC_URL = saved_public

    res = await platforms.get_client(Platform.instagram).publish(
        ig, "external", "https://cdn.example/real.jpg")
    check("an external media URL is not blocked by the local check", res.ok, res.error)

    print("\n[Threads / manual platforms]")
    install(graph_handler)
    th = acc(Platform.threads, "TH1")
    res = await platforms.get_client(Platform.threads).publish(th, "hi", "")
    check("Threads marked manual (no publish API in this build)", (not res.ok) and res.manual)
    mj = acc(Platform.moj, "MJ1")
    res = await platforms.get_client(Platform.moj).publish(mj, "hi", "")
    check("Moj marked manual", (not res.ok) and res.manual)


def main():
    print("SocialAuto — platform API contract tests")
    print("=" * 62)
    try:
        asyncio.run(run())
    finally:
        restore()
    print(f"\n{'=' * 62}\nPASSED: {len(PASS)}   FAILED: {len(FAIL)}")
    if FAIL:
        print("\nFAILURES:")
        for f in FAIL:
            print("  ❌", f)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
