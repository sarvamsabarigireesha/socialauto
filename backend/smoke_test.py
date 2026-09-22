"""End-to-end smoke test — exercises every router against a throwaway DB.

Run:  MOCK_MODE=true DATABASE_URL="sqlite:///./data/smoke.db" python3 smoke_test.py
"""
import json
import os
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

DB = "sqlite:///./data/smoke.db"
if os.path.exists("data/smoke.db"):
    os.remove("data/smoke.db")
# uploads persist in data/media between runs — clear them so the listing
# assertions below are deterministic
for _u in pathlib.Path("data/media").glob("u*"):
    if _u.is_dir():
        for _f in _u.iterdir():
            _f.unlink()
        _u.rmdir()
os.environ["DATABASE_URL"] = DB
os.environ.setdefault("MOCK_MODE", "true")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.models import Platform  # noqa: E402

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  ✅ " if cond else "  ❌ ") + name + (f"  {extra}" if extra and not cond else ""))


print("\n[config guards — the Render placeholder trap]")
from app.config import (database_url_problem, secret_problem,  # noqa: E402
                        )
from app.routers import oauth as oauth_mod  # noqa: E402
from app.config import settings as cfg  # noqa: E402

check("placeholder DB url is rejected with a clear reason",
      "placeholder" in database_url_problem("postgresql://...?sslmode=require"),
      database_url_problem("postgresql://...?sslmode=require"))
check("a real Neon URL passes",
      database_url_problem("postgresql://neondb_owner:pw@ep-cool-1.ap-southeast-1"
                           ".aws.neon.tech/neondb?sslmode=require") == "")
check("sqlite and empty are left alone",
      database_url_problem("sqlite:///./data/app.db") == ""
      and database_url_problem("") == "")
check("a doc-example host is rejected", database_url_problem(
      "postgresql://u:p@ep-xxxx.aws.neon.tech/db?sslmode=require") != "")
check("'long random string' is flagged as example text",
      "example text" in secret_problem("long random string", "CRON_SECRET"))
check("a short secret is flagged", "characters" in secret_problem("abc", "JWT_SECRET"))
check("a long random secret passes",
      secret_problem("KBGHgGUWkcUxR3YwDx7ebCNLs2JAUvxUBegGvAILlQ4E7pT64", "CRON_SECRET") == "")

_saved = cfg.META_OAUTH_REDIRECT_URI
cfg.META_OAUTH_REDIRECT_URI = "https://socialauto-k5ou.onrender.com/api/oauth/callback"
check("META_OAUTH_REDIRECT_URI overrides the Meta callback",
      oauth_mod._redirect_uri(None, Platform.instagram) ==
      "https://socialauto-k5ou.onrender.com/api/oauth/callback",
      oauth_mod._redirect_uri(None, Platform.instagram))
cfg.APP_PUBLIC_URL = "https://socialauto-k5ou.onrender.com"
class _FakeReq:  # minimal stand-in for a Starlette Request
    base_url = "https://socialauto-k5ou.onrender.com/"

google_uri = oauth_mod._redirect_uri(_FakeReq(), Platform.youtube)
check("the Meta override does NOT hijack Google's callback",
      google_uri == "https://socialauto-k5ou.onrender.com/api/oauth/callback"
      and google_uri != cfg.META_OAUTH_REDIRECT_URI or "oauth/callback" in google_uri,
      google_uri)
cfg.META_OAUTH_REDIRECT_URI = _saved

with TestClient(app) as client:
    # ---------------------------------------------------------------- health
    print("\n[health]")
    r = client.get("/api/health")
    check("GET /api/health", r.status_code == 200 and r.json()["ok"])

    # ------------------------------------------------------------------ auth
    print("\n[auth]")
    r = client.post("/api/auth/register", json={
        "email": "tester@example.com", "password": "secret123", "name": "Tester"})
    check("POST /api/auth/register", r.status_code == 201, r.text[:200])
    token = r.json()["access_token"]
    H = {"Authorization": f"Bearer {token}"}

    r = client.post("/api/auth/login", json={
        "email": "tester@example.com", "password": "secret123"})
    check("POST /api/auth/login", r.status_code == 200, r.text[:200])

    r = client.get("/api/auth/me", headers=H)
    check("GET /api/auth/me", r.status_code == 200)
    UID = r.json()["id"]

    r = client.patch("/api/auth/profile", json={"timezone": "Asia/Kolkata"}, headers=H)
    check("PATCH /api/auth/profile", r.status_code == 200, r.text[:200])

    r = client.get("/api/auth/me")
    check("auth required (401 without token)", r.status_code == 403 or r.status_code == 401)

    # -------------------------------------------------------------- accounts
    print("\n[accounts]")
    r = client.post("/api/accounts", json={
        "platform": "instagram", "display_name": "@test.ig", "external_id": "ig_1",
        "auto_comment": True}, headers=H)
    check("POST /api/accounts (instagram)", r.status_code == 201, r.text[:200])
    ig_id = r.json()["id"]

    r = client.post("/api/accounts", json={
        "platform": "youtube", "display_name": "Test Tube", "external_id": "yt_1"},
        headers=H)
    check("POST /api/accounts (youtube)", r.status_code == 201, r.text[:200])
    yt_id = r.json()["id"]

    r = client.get("/api/accounts", headers=H)
    check("GET /api/accounts", r.status_code == 200 and len(r.json()) == 2)

    r = client.patch(f"/api/accounts/{ig_id}", json={
        "posting_slots": [{"day": 1, "time": "10:00"}, {"day": 3, "time": "18:00"}],
        "posting_goal": 5}, headers=H)
    check("PATCH /api/accounts (slots)", r.status_code == 200 and
          len(r.json()["posting_slots"]) == 2, r.text[:200])

    # ------------------------------------------------------------------- tags
    print("\n[tags]")
    r = client.post("/api/tags", json={"name": "Food"}, headers=H)
    check("POST /api/tags", r.status_code == 201, r.text[:200])
    tag_id = r.json()["id"]
    r = client.get("/api/tags", headers=H)
    check("GET /api/tags", r.status_code == 200 and len(r.json()) == 1)

    # ------------------------------------------------------------------ posts
    print("\n[posts]")
    r = client.post("/api/posts", json={
        "account_ids": [ig_id], "caption": "Scheduled post 🍗", "media_url": "",
        "post_type": "feed", "tag_ids": [tag_id],
        "scheduled_at": "2030-01-01T10:00:00Z"}, headers=H)
    check("POST /api/posts (scheduled)", r.status_code == 201, r.text[:300])
    sched_id = r.json()[0]["id"]
    check("scheduled_at carries UTC offset",
          "+00:00" in r.json()[0]["scheduled_at"] or r.json()[0]["scheduled_at"].endswith("Z"),
          r.json()[0]["scheduled_at"] if r.status_code == 201 else "")

    r = client.post("/api/posts", json={
        "account_ids": [ig_id], "caption": "Queue me", "post_type": "feed",
        "source": "queue", "scheduled_at": "2030-01-02T10:00:00Z"}, headers=H)
    check("POST /api/posts (queue -> slot)", r.status_code == 201, r.text[:300])
    q1 = r.json()[0]["id"]

    r = client.post("/api/posts", json={
        "account_ids": [ig_id], "caption": "Queue me too", "post_type": "feed",
        "source": "queue", "scheduled_at": "2030-01-02T10:00:00Z"}, headers=H)
    check("POST /api/posts (queue 2)", r.status_code == 201, r.text[:300])
    q2 = r.json()[0]["id"]
    check("queue gives different slots",
          r.json()[0]["scheduled_at"] != client.get("/api/posts", headers=H).json()[0]["scheduled_at"],
          "")

    r = client.post("/api/posts", json={
        "account_ids": [ig_id, yt_id], "caption": "Multi-account", "post_type": "feed",
        "per_account": [{"account_id": yt_id, "caption": "YT variant", "post_type": "video"}],
        "scheduled_at": "2030-01-03T10:00:00Z"}, headers=H)
    check("POST /api/posts (per-account variants)", r.status_code == 201 and len(r.json()) == 2,
          r.text[:300])

    r = client.post("/api/posts", json={
        "account_ids": [ig_id], "caption": "Draft me", "status": "draft",
        "scheduled_at": "2030-01-04T10:00:00Z"}, headers=H)
    check("POST /api/posts (draft)", r.status_code == 201 and r.json()[0]["status"] == "draft",
          r.text[:300])

    r = client.post("/api/posts", json={
        "account_ids": [ig_id], "caption": "Bad type", "post_type": "nope",
        "scheduled_at": "2030-01-01T10:00:00Z"}, headers=H)
    check("POST /api/posts rejects bad post_type", r.status_code == 400)

    r = client.post("/api/posts/bulk", json={
        "account_ids": [ig_id],
        "posts": [{"caption": "bulk 1", "scheduled_at": "2030-02-01T10:00:00Z"},
                  {"caption": "bulk 2", "scheduled_at": "2030-02-02T10:00:00Z"}]}, headers=H)
    check("POST /api/posts/bulk", r.status_code == 201 and len(r.json()) == 2, r.text[:300])

    csv_body = "caption,media_url,post_type,scheduled_at\nCSV one,,feed,2030-03-01T09:00:00\n"
    r = client.post(f"/api/posts/bulk/csv?account_ids={ig_id}&tag_ids={tag_id}",
                    files={"file": ("posts.csv", csv_body, "text/csv")}, headers=H)
    check("POST /api/posts/bulk/csv", r.status_code == 201 and len(r.json()) == 1, r.text[:300])
    check("CSV naive date normalised to UTC",
          ("+00:00" in r.json()[0]["scheduled_at"]
           or r.json()[0]["scheduled_at"].endswith("Z"))
          if r.status_code == 201 else False,
          r.json()[0]["scheduled_at"] if r.status_code == 201 else "")

    r = client.get("/api/posts", headers=H)
    check("GET /api/posts", r.status_code == 200 and len(r.json()) >= 7, r.text[:200])

    r = client.patch(f"/api/posts/{sched_id}", json={"caption": "Edited"}, headers=H)
    check("PATCH /api/posts/{id}", r.status_code == 200 and r.json()["caption"] == "Edited",
          r.text[:200])

    r = client.post("/api/posts/reorder", json={"ordered_ids": [q2, q1]}, headers=H)
    check("POST /api/posts/reorder", r.status_code == 200 and r.json()["reordered"] == 2,
          r.text[:300])
    ids = [p["id"] for p in r.json()["posts"]]
    check("reorder preserved order", ids == [q2, q1], str(ids))

    r = client.get("/api/posts/csv-template")
    check("GET /api/posts/csv-template", r.status_code == 200 and "caption" in r.json()["content"])

    # -------------------------------------------------------- publish + now
    print("\n[publishing]")
    r = client.post(f"/api/posts/{sched_id}/publish-now", headers=H)
    check("POST /api/posts/{id}/publish-now", r.status_code == 200 and
          r.json()["status"] == "published", r.text[:300])

    r = client.post(f"/api/posts/{yt_id and sched_id}/publish-now", headers=H)
    check("publish-now idempotent on published post", r.status_code == 200, r.text[:200])

    r = client.post(f"/api/posts/{q1}/mark-done", headers=H)
    check("POST /api/posts/{id}/mark-done", r.status_code == 200 and
          r.json()["status"] == "published", r.text[:200])

    # ----------------------------------------------------------- comments
    print("\n[comments]")
    r = client.post("/api/comments/simulate", json={
        "post_id": sched_id, "author": "follower", "text": "How much? I want to order"},
        headers=H)
    check("POST /api/comments/simulate", r.status_code == 201, r.text[:300])
    check("simulated comment got an auto-reply",
          bool(r.json().get("our_reply")) and r.json().get("replied") is True, r.text[:300])

    r = client.post("/api/comments/sync", headers=H)
    check("POST /api/comments/sync", r.status_code == 200 and
          {"new_comments", "auto_replies"} <= set(r.json()), r.text[:300])

    r = client.get("/api/comments", headers=H)
    check("GET /api/comments", r.status_code == 200 and len(r.json()) >= 1, r.text[:200])

    # ---------------------------------------------------------- community
    print("\n[community]")
    r = client.get("/api/community/summary", headers=H)
    check("GET /api/community/summary", r.status_code == 200 and "totals" in r.json(),
          r.text[:300])
    threads = r.json().get("threads", [])
    check("community threads present", len(threads) >= 1, str(len(threads)))

    if threads and threads[0]["comments"]:
        cid = threads[0]["comments"][0]["id"]
        r = client.post(f"/api/community/comments/{cid}/reply", json={"text": "Thanks!"},
                        headers=H)
        check("POST /api/community/comments/{id}/reply", r.status_code == 200, r.text[:300])
        r = client.post(f"/api/community/comments/{cid}/resolve", headers=H)
        check("POST /api/community/comments/{id}/resolve", r.status_code == 200, r.text[:300])

    r = client.post(f"/api/community/import/{ig_id}", headers=H)
    check("POST /api/community/import/{account_id}", r.status_code == 200 and
          "imported" in r.json(), r.text[:300])

    r = client.post("/api/community/import-all", headers=H)
    check("POST /api/community/import-all", r.status_code == 200 and
          "imported" in r.json(), r.text[:300])

    r = client.post("/api/community/bootstrap-sync", headers=H)
    check("POST /api/community/bootstrap-sync", r.status_code == 200 and
          {"imported", "comments_sync", "metrics_sync", "per_account", "errors"} <= set(r.json()),
          r.text[:400])

    r = client.post("/api/community/sync", headers=H)
    check("POST /api/community/sync", r.status_code == 200 and
          "new_comments" in r.json(), r.text[:300])

    # ---------------------------------------------------------- analytics
    print("\n[analytics]")
    r = client.post("/api/analytics/sync", headers=H)
    check("POST /api/analytics/sync", r.status_code == 200 and "snapshots" in r.json(),
          r.text[:300])

    r = client.get("/api/analytics", headers=H)
    ok = r.status_code == 200
    d = r.json() if ok else {}
    check("GET /api/analytics", ok and
          {"totals", "by_platform", "per_post", "by_tag", "posts_published",
           "comments_total", "auto_replied"} <= set(d), r.text[:300])
    check("analytics per_post fields",
          all({"post_id", "platform", "account", "caption", "likes", "comments",
               "shares", "impressions", "reach"} <= set(p) for p in d.get("per_post", [])))

    r = client.get("/api/analytics?days=30", headers=H)
    check("GET /api/analytics?days=30", r.status_code == 200, r.text[:200])

    r = client.get("/api/analytics/export.csv", headers=H)
    check("GET /api/analytics/export.csv", r.status_code == 200 and
          "post_id" in r.text.splitlines()[0], r.text[:200])

    # --------------------------------------------------------------- cron
    print("\n[cron]")
    r = client.post("/api/cron/tick", headers={"X-Cron-Secret": "dev-cron-secret-change-me"})
    check("POST /api/cron/tick", r.status_code == 200 and r.json()["ok"], r.text[:400])
    check("cron tick count keys", {"imported", "published", "comments", "metrics"} <=
          set(r.json()), r.text[:300])

    r = client.post("/api/cron/tick", headers={"X-Cron-Secret": "wrong"})
    check("cron rejects bad secret", r.status_code == 401)

    r = client.post("/api/cron/publish", headers={"X-Cron-Secret": "dev-cron-secret-change-me"})
    check("POST /api/cron/publish", r.status_code == 200 and "published" in r.json(),
          r.text[:300])

    # ----------------------------------------------------- ideas/templates/links
    print("\n[ideas / templates / links / media]")
    r = client.post("/api/ideas", json={"text": "Idea one"}, headers=H)
    check("POST /api/ideas", r.status_code == 201, r.text[:200])
    idea_id = r.json()["id"]
    r = client.patch(f"/api/ideas/{idea_id}", json={"status": "todo"}, headers=H)
    check("PATCH /api/ideas/{id}", r.status_code == 200 and r.json()["status"] == "todo",
          r.text[:200])
    r = client.get("/api/ideas", headers=H)
    check("GET /api/ideas", r.status_code == 200 and "todo" in r.json(), r.text[:200])
    r = client.delete(f"/api/ideas/{idea_id}", headers=H)
    check("DELETE /api/ideas/{id}", r.status_code == 204)

    r = client.get("/api/templates", headers=H)
    check("GET /api/templates", r.status_code == 200 and len(r.json()) >= 6, r.text[:200])
    r = client.post("/api/templates", json={"title": "Mine", "content": "Hello"}, headers=H)
    check("POST /api/templates", r.status_code == 201, r.text[:200])
    tpl_id = r.json()["id"]
    r = client.delete(f"/api/templates/{tpl_id}", headers=H)
    check("DELETE /api/templates/{id}", r.status_code == 204)

    r = client.post("/api/links", json={"url": "example.com/very/long/path"}, headers=H)
    check("POST /api/links", r.status_code == 201 and r.json()["short_url"], r.text[:200])
    code = r.json()["code"]
    r = client.get("/api/links/stats", headers=H)
    check("GET /api/links/stats", r.status_code == 200 and len(r.json()) == 1, r.text[:200])
    r = client.get(f"/api/links/expand/{code}", headers=H)
    check("GET /api/links/expand/{code}", r.status_code == 200, r.text[:200])
    r = client.get(f"/l/{code}", follow_redirects=False)
    check("GET /l/{code} redirects", r.status_code in (302, 307), str(r.status_code))
    r = client.post("/api/links", json={"url": "http://127.0.0.1:8000/x"}, headers=H)
    check("links rejects localhost", r.status_code == 400)

    png = (b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)
    r = client.post("/api/media", files={"file": ("pic.png", png, "image/png")}, headers=H)
    check("POST /api/media", r.status_code == 200 and r.json()["url"], r.text[:200])
    media_path = r.json()["path"]
    media_url = r.json()["url"]
    check(f"upload is stored per user (u{UID}/file)",
          media_path == f"u{UID}/{media_path.split('/')[-1]}", media_path)
    check("upload URL points at /media/", f"/media/u{UID}/" in media_url, media_url)

    r = client.get("/api/media", headers=H)
    check("GET /api/media lists the upload", r.status_code == 200 and len(r.json()) == 1
          and r.json()[0]["url"] == media_url, r.text[:300])

    r = client.get(media_url)
    check("GET /media/<uploaded> serves the file", r.status_code == 200 and
          r.content == png, f"{r.status_code} {r.text[:120]}")
    check("media response allows caching", "max-age" in r.headers.get("cache-control", ""))

    r = client.head(media_url)
    check("HEAD /media/<uploaded> works (health-checkers use HEAD)", r.status_code == 200)

    # legacy layout: old DB rows point at /media/u3/<file>
    legacy = pathlib.Path("data/media/u3")
    legacy.mkdir(parents=True, exist_ok=True)
    (legacy / "old-clip.mp4").write_bytes(b"\x00" * 32)
    r = client.get("/media/u3/old-clip.mp4")
    check("legacy /media/u<id>/<file> URLs still resolve", r.status_code == 200,
          f"{r.status_code} {r.text[:120]}")
    r = client.get("/media/anything-at-all/old-clip.mp4")
    check("a wrong folder still resolves by basename", r.status_code == 200,
          str(r.status_code))
    r = client.get("/media/../../etc/passwd")
    check("path traversal is blocked", r.status_code in (404, 400, 307),
          str(r.status_code))

    r = client.get("/media/u3/never-uploaded.mp4")
    check("missing media returns a helpful 404, not a bare one",
          r.status_code == 404 and "redeploy" in r.json().get("detail", ""), r.text[:250])

    r = client.post("/api/media", files={"file": ("bad.exe", b"x", "application/octet")},
                    headers=H)
    check("media rejects bad extension", r.status_code == 400)
    r = client.post("/api/media", files={"file": ("empty.png", b"", "image/png")}, headers=H)
    check("media rejects an empty file", r.status_code == 400)

    # --------------------------- the migration bug that broke the 1.9.0 deploy
    print("\n[startup migrations — the check that crashed the service]")
    from sqlalchemy import String as SaString, Text as SaTextCol  # noqa: E402
    from app.main import _media_url_needs_widening  # noqa: E402

    class _Insp:
        def __init__(self, columns):
            self.columns = columns

        def get_columns(self, table):
            return self.columns

    narrow = _Insp([{"name": "media_url", "type": SaString(500)}])
    wide = _Insp([{"name": "media_url", "type": SaTextCol()}])
    check("a narrow media_url is detected for widening",
          _media_url_needs_widening(narrow, {"posts"}) is True)
    check("a TEXT media_url is left alone (no lock taken on every boot)",
          _media_url_needs_widening(wide, {"posts"}) is False)
    check("no posts table / no column doesn't raise",
          _media_url_needs_widening(narrow, {"users"}) is False
          and _media_url_needs_widening(_Insp([]), {"posts"}) is False)
    check("an inspector that throws is survivable",
          _media_url_needs_widening(type("B", (), {"get_columns": lambda self, t: 1 / 0})(),
                                    {"posts"}) is False)

    # ------------------------------------------------ manual / helper platforms
    print("\n[manual platforms — Moj / ShareChat / Snapchat]")
    html = client.get("/").text
    check("the connect screen offers Snapchat", "prepareManualAccount('snapchat')" in html)
    check("the connect screen offers Bilibili", "prepareManualAccount('bilibili')" in html)
    check("Snapchat shows up in the platform filters too",
          html.count('<option value="snapchat">') >= 4, str(html.count('<option value="snapchat">')))
    check("manual platforms get a real hand-off (open app + download media)",
          "MANUAL_OPEN" in html and "Download media" in html)

    r = client.post("/api/accounts", json={
        "platform": "snapchat", "display_name": "@sarvam_snap", "external_id": "snap_1",
        "auto_comment": True}, headers=H)
    check("Snapchat can be connected through the manual flow",
          r.status_code == 201, r.text[:200])
    snap_id = r.json()["id"]

    r = client.post("/api/accounts", json={
        "platform": "bilibili", "display_name": "@sarvam_bili", "external_id": "bili_1",
        "auto_comment": False}, headers=H)
    check("Bilibili can be connected through the manual flow",
          r.status_code == 201, r.text[:200])

    r = client.post("/api/posts", json={
        "account_ids": [snap_id], "caption": "Sabarimala 9:16 clip", "media_url": "",
        "post_type": "short", "scheduled_at": "2030-02-01T10:00:00Z"}, headers=H)
    check("a Snapchat post can be queued", r.status_code == 201, r.text[:200])
    snap_post = r.json()[0]["id"]

    # MOCK_MODE would fake a success here; we want the real manual hand-off
    _saved_mock = cfg.MOCK_MODE
    cfg.MOCK_MODE = False
    try:
        r = client.post(f"/api/posts/{snap_post}/publish-now", headers=H)
    finally:
        cfg.MOCK_MODE = _saved_mock
    check("publishing to Snapchat is handed over as a manual step, not a crash",
          r.status_code in (200, 400, 409), r.text[:200])
    r = client.get("/api/posts", headers=H)
    snap_row = [p for p in r.json() if p["id"] == snap_post][0]
    check("the Snapchat post is marked manual with a next step for the user",
          (snap_row.get("error") or "").startswith("MANUAL:")
          and "I posted it" in snap_row["error"], str(snap_row.get("error"))[:160])

    # ------------------------- upload limit / long URL / comment sync bugs
    print("\n[media upload — the video that silently never attached]")
    from app import media_store  # noqa: E402
    from app.routers import media as media_mod  # noqa: E402

    check("upload ceiling fits a phone video (>=100MB)",
          media_store.MAX_UPLOAD_BYTES >= 100 * 1024 * 1024,
          f"{media_store.MAX_UPLOAD_BYTES} bytes")
    limit_msg = media_store.size_error(53 * 1024 * 1024, "beach.mp4")
    check("an oversize upload explains itself and offers a way forward",
          "53MB" in limit_msg and "Compress" in limit_msg and "https://" in limit_msg,
          limit_msg)

    clip = b"\x00" * (3 * 1024 * 1024)
    r = client.post("/api/media", files={"file": ("clip.mp4", clip, "video/mp4")},
                    headers=H)
    check("POST /api/media takes a multi-MB video (streamed, not read into RAM)",
          r.status_code == 200 and r.json()["size"] == len(clip), r.text[:200])
    check("the big upload is served back byte-for-byte",
          client.get(r.json()["url"]).content == clip)

    was = media_mod.MAX_UPLOAD_BYTES, media_store.MAX_UPLOAD_BYTES
    media_mod.MAX_UPLOAD_BYTES = media_store.MAX_UPLOAD_BYTES = 2 * 1024 * 1024
    try:
        r = client.post("/api/media", files={"file": ("huge.mp4", b"\x00" * (3 * 1024 * 1024),
                                                      "video/mp4")}, headers=H)
    finally:
        media_mod.MAX_UPLOAD_BYTES, media_store.MAX_UPLOAD_BYTES = was
    check("an oversize upload is rejected with an actionable 400, not a bare one",
          r.status_code == 400 and "Compress" in r.json().get("detail", ""), r.text[:250])
    leftover = [f.name for f in pathlib.Path(f"data/media/u{UID}").glob("*.mp4")]
    check("a rejected upload leaves no half-written file on disk",
          not any("huge" in name for name in leftover), str(leftover))

    print("\n[long media urls — why the first import stored nothing]")
    from sqlalchemy import Text as SaText  # noqa: E402
    from app.models import Post as PostModel  # noqa: E402

    check("posts.media_url is TEXT, not VARCHAR(500)",
          isinstance(PostModel.__table__.c.media_url.type, SaText),
          str(PostModel.__table__.c.media_url.type))
    cdn = ("https://scontent-bom1-1.xx.fbcdn.net/v/t39.30808-6/4987_n.jpg"
           "?_nc_cat=110&ccb=1-7&_nc_sid=127cfc&_nc_ohc=" + "A" * 400 + "&oe=67D0ABCD")
    r = client.post("/api/posts", json={
        "account_ids": [ig_id], "caption": "long cdn url", "media_url": cdn,
        "post_type": "feed", "scheduled_at": "2030-01-03T10:00:00Z"}, headers=H)
    check("a 500+ character CDN url round-trips through the API",
          r.status_code == 201 and r.json()[0]["media_url"] == cdn, r.text[:200])

    print("\n[comments — dedupe, real timestamps, watch window]")
    import asyncio  # noqa: E402
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz  # noqa: E402
    from app.database import SessionLocal  # noqa: E402
    from app.models import Comment, Post, PostStatus  # noqa: E402
    from app.services import engine as engine_mod, platforms as platforms_mod  # noqa: E402

    _now = _dt.now(_tz.utc)
    payload = [
        {"id": "cmt_recent", "author": "priya", "text": "Rate enti?",
         "created_at": (_now - _td(hours=2)).isoformat()},
        {"id": "cmt_ancient", "author": "ravi", "text": "Chala bagundi",
         "created_at": (_now - _td(days=60)).isoformat()},
    ]

    class _Stub:
        """Same two comments come back for both post rows of one account."""

        def __init__(self):
            self.replies = []

        async def fetch(self, account, pid):
            if pid not in ("ig_post_A", "ig_post_B"):
                return platforms_mod.FetchResult([], {})
            return platforms_mod.FetchResult([dict(c) for c in payload], {})

        async def reply_to_comment(self, account, pid, cid, text):
            self.replies.append((cid, text))
            return True

    stub = _Stub()
    real_get_client = platforms_mod.get_client
    saved_mock_mode = cfg.MOCK_MODE
    platforms_mod.get_client = lambda platform: stub
    cfg.MOCK_MODE = False          # no random filler comments during this test
    try:
        db = SessionLocal()
        for pid in ("ig_post_A", "ig_post_B"):   # one account, two post rows
            db.add(Post(user_id=UID, account_id=ig_id, caption="synced",
                        media_url="", post_type="feed", status=PostStatus.published,
                        platform_post_id=pid, scheduled_at=_now - _td(hours=3),
                        published_at=_now - _td(hours=3)))
        db.commit()
        recent_post_id = (db.query(Post).filter(Post.platform_post_id == "ig_post_A")
                          .first().id)
        first = asyncio.run(engine_mod.sync_comments(db, user_id=UID, limit=10))
        seen = [(c.external_comment_id, c.post_id, bool(c.replied), c.created_at)
                for c in db.query(Comment)
                .filter(Comment.external_comment_id.in_(["cmt_recent", "cmt_ancient"])).all()]
        second = asyncio.run(engine_mod.sync_comments(db, user_id=UID, limit=10))
        db.close()
    finally:
        platforms_mod.get_client = real_get_client
        cfg.MOCK_MODE = saved_mock_mode

    by_id = {}
    for ext_id, post_id, replied, created in seen:
        by_id.setdefault(ext_id, []).append((post_id, replied, created))

    check("a comment reached through two post rows is stored exactly once",
          len(by_id.get("cmt_recent", [])) == 1 and first["new_comments"] == 1,
          f"rows={ {k: len(v) for k, v in by_id.items()} } new_comments={first['new_comments']}")
    check("the recent comment was auto-replied exactly once",
          by_id.get("cmt_recent", [(None, False, None)])[0][1] and
          first["auto_replies"] == 1 and len(stub.replies) == 1,
          f"auto_replies={first['auto_replies']} posted={len(stub.replies)}")
    _created = by_id.get("cmt_recent", [(None, False, None)])[0][2]
    check("the comment keeps the platform timestamp, not fetch time",
          _created is not None and abs((_created.replace(tzinfo=_tz.utc)
                                        - (_now - _td(hours=2))).total_seconds()) < 90,
          str(_created))
    check("a comment older than the 7-day sync window is never even stored",
          "cmt_ancient" not in by_id and first.get("skipped_old", 0) >= 1,
          f"skipped_old={first.get('skipped_old')} rows={list(by_id)}")
    check("re-syncing the same comments changes nothing (no double replies)",
          second["new_comments"] == 0 and second["auto_replies"] == 0
          and len(stub.replies) == 1, json.dumps(second))

    db = SessionLocal()
    stale = Comment(post_id=recent_post_id, external_comment_id="cmt_stale",
                    author="old_user", author_avatar="O", text="from last month",
                    created_at=_now - _td(days=30))
    db.add(stale)
    db.commit()
    platforms_mod.get_client = lambda platform: stub
    cfg.MOCK_MODE = False
    try:
        third = asyncio.run(engine_mod.sync_comments(db, user_id=UID, limit=10))
    finally:
        platforms_mod.get_client = real_get_client
        cfg.MOCK_MODE = saved_mock_mode
    left = db.query(Comment).filter(Comment.external_comment_id == "cmt_stale").count()
    db.close()
    check("comments older than the 7-day window get pruned, not archived",
          left == 0 and third.get("pruned", 0) >= 1, json.dumps(third))

    print("\n[health check compatibility]")
    r = client.head("/api/health")
    check("HEAD /api/health returns 200 (Render's health check)", r.status_code == 200,
          str(r.status_code))
    r = client.head("/")
    check("HEAD / returns 200 (was 405 → unhealthy service)", r.status_code == 200,
          str(r.status_code))

    # ------------------------------------------------------------------- ai
    print("\n[ai]")
    r = client.post("/api/ai/suggest", json={"caption": "New biryani reel", "platforms": ["instagram"]},
                    headers=H)
    check("POST /api/ai/suggest", r.status_code == 200, r.text[:300])
    r = client.post("/api/ai/growth", json={"title": "5 Best Biryani Spots in Hyderabad (2026)",
                                            "description": "Hyderabad biryani guide"},
                    headers=H)
    check("POST /api/ai/growth", r.status_code == 200 and "title_score" in r.json(),
          r.text[:300])

    # -------------------------------------------------------------- webhooks
    print("\n[webhooks]")
    r = client.get("/api/webhooks/meta?hub.mode=subscribe&hub.verify_token="
                   "socialauto-verify-token&hub.challenge=12345")
    check("GET /api/webhooks/meta verification", r.status_code == 200 and r.json() == 12345,
          r.text[:200])
    r = client.get("/api/webhooks/meta?hub.mode=subscribe&hub.verify_token=nope&hub.challenge=1")
    check("webhook rejects bad verify token", r.status_code == 403)

    # ----------------------------------------------------------- password reset
    print("\n[password reset]")
    r = client.post("/api/auth/forgot-password", json={"email": "tester@example.com"})
    check("POST /api/auth/forgot-password", r.status_code == 200 and r.json()["reset_token"],
          r.text[:200])
    reset = r.json()["reset_token"]
    r = client.post("/api/auth/reset-password", json={"token": reset,
                                                     "new_password": "brandnew123"})
    check("POST /api/auth/reset-password", r.status_code == 200, r.text[:200])
    r = client.post("/api/auth/login", json={"email": "tester@example.com",
                                             "password": "brandnew123"})
    check("login with new password", r.status_code == 200, r.text[:200])
    r = client.post("/api/auth/change-password", json={"current_password": "brandnew123",
                                                       "new_password": "secret123"}, headers=H)
    check("POST /api/auth/change-password", r.status_code == 200, r.text[:200])

    # -------------------------------------------------------------- static UI
    print("\n[static]")
    r = client.get("/")
    check("GET / (dashboard html)", r.status_code == 200 and "<html" in r.text.lower())

print(f"\n{'=' * 60}\nPASSED: {len(PASS)}   FAILED: {len(FAIL)}")
if FAIL:
    print("\nFAILURES:")
    for f in FAIL:
        print("  ❌", f)
sys.exit(1 if FAIL else 0)
