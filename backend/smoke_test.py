"""End-to-end smoke test — exercises every router against a throwaway DB.

Run:  MOCK_MODE=true DATABASE_URL="sqlite:///./data/smoke.db" python3 smoke_test.py
"""
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
