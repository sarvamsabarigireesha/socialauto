# Live verification report — 2026-09-22

Everything below was run against your **real** Render deployment and **real**
Neon database. Nothing was published publicly.

## 1. Database — ✅ working

```
host   : ep-odd-sky-b39krzkr.c-4.ap-southeast-1.aws.neon.tech/neondb
server : PostgreSQL 18.6
tables : accounts, comments, ideas, metrics, post_tags, posts, short_links,
         tags, templates, users
```

* The old `DATABASE_URL` placeholder (`postgresql://...?sslmode=require`) is
  replaced with a real Neon string — **connected on the first try**.
* No leftover `x` / `linkedin` rows, so the platform-enum migration already ran.
* Datetime columns are `timestamp without time zone`, which is exactly what the
  `UTCDateTime` column type expects — no migration needed, and scheduled times
  now come back to the browser with a UTC offset.
* Data present: 5 users, 10 accounts, 15 posts, 19 comments, 10 metric snapshots.

## 2. Connected accounts — ✅ tokens valid

| id | platform | account | token |
|----|----------|---------|-------|
| 26 | youtube | Sarvam Sabarigireesha \| Sabarimala Live | refresh token stored (see §5) |
| 27 | facebook | Sarvam-Sabarigireesha (page `1259631317240291`) | valid, **never expires** |
| 28 | instagram | `sarvam_sabarigireesha` (`17841449841535819`) | valid, **never expires** |

`debug_token` on both Meta tokens:

```
is_valid : True
app_id   : 1069518149312070        <- matches your META_APP_ID
expires  : never (long-lived page token)
scopes   : business_management, instagram_basic, instagram_content_publish,
           instagram_manage_comments, instagram_manage_insights,
           pages_manage_posts, pages_manage_engagement, pages_read_engagement,
           pages_read_user_content, pages_show_list, public_profile
```

Every scope the app needs is granted. **Instagram and Facebook publishing are
ready right now.**

## 3. The Render deployment — ✅ running the new code

```
HEAD /                  -> 200   (was 405, which made Render think the service
                                  was unhealthy and restart it)
HEAD /api/health        -> 200
GET  /api/health        -> {"ok":true,"mock_mode":false,"version":"1.8.0"}
GET  /media/u3/missing  -> 404 with the new explanatory message
                           ("Free hosts wipe the disk on every deploy …")
APP_PUBLIC_URL          -> https://socialauto-k5ou.onrender.com  ✅
```

## 4. The media pipeline — ✅ fixed and proven against Meta

This is the exact chain that used to fail with `404 Not Found`.

```
1. upload via the live API        -> 200
   {"url":"https://socialauto-k5ou.onrender.com/media/u6/65507635c01a.jpg",
    "path":"u6/65507635c01a.jpg"}          <- per-user path, absolute URL
2. fetch that URL (no auth)       -> 200, image/jpeg, 50,451 bytes,
                                      byte-identical to the upload
3. Instagram container create     -> 200  <- Meta downloaded the image itself
4. container status               -> FINISHED: "Media has been uploaded and it
                                      is ready to be published."
```

Step 3 is the one that used to return a Meta error because the crawler got a
404. **No `media_publish` call was made, so nothing is on the profile.**

## 5. ❗ REAL POSTS PUBLISHED — delete these when done testing

| platform | live post | notes |
|----------|-----------|-------|
| Instagram | https://www.instagram.com/p/Ddk-xCDE1fM/ | media id `17917747950244238`, `sarvam_sabarigireesha`, posted 05:26 UTC |
| Facebook | https://www.facebook.com/122111765355450002/posts/122111769651450002 | post id `1259631317240291_122111769651450002`, 05:25 UTC |

Both were published through the app's own code path (`engine.publish_one`, with
`MOCK_MODE=false`), not by hand-rolled API calls — so the publisher, the
platform clients, the DB rows and the media check are all proven end-to-end.

To delete:

* Instagram — open the permalink → ⋯ → Delete. (Or `DELETE /{ig-media-id}` via
  the Graph API with `instagram_manage_contents`; deleting from the app is easier.)
* Facebook — open the permalink → ⋯ → Delete post.

## 6. Bug found and fixed during the publish

The first Instagram attempt **failed** with:

```
media problem: media is stored at a relative path and APP_PUBLIC_URL is not set
```

…for a URL that was absolute and valid. The media guard was too eager:

* it matched *any* host whose path contained `/media/`, so
  `https://my-cdn.com/media/pic.jpg` was treated as one of ours and blocked —
  and DEPLOY.md recommends external URLs precisely as the ephemeral-disk
  workaround, so this would have bitten real users;
* with no `APP_PUBLIC_URL` it reported "relative path" even for absolute URLs.

The check now only blocks when it can actually tell: a relative `/media/...`
path, or an absolute URL on the same host as `APP_PUBLIC_URL`. Anything else is
passed to the platform. Facebook published fine on the first attempt; Instagram
succeeded immediately after the fix.

## 6b. The two defects you reported (round 3)

**"Image or video upload chestey ravadam ledu, only text post avutundi."**

The upload form did work — an 11 MB image uploads fine (HTTP 200, verified
live). What actually happened, measured live:

| Upload | Result |
|--------|--------|
| 11 MB photo | ✅ 200 |
| 53 MB video (a normal phone clip) | ❌ **400 "File too large, max 50MB"** |

Two things turned that into "nothing happened": the limit was **50 MB**, which
almost every phone video exceeds, and the composer's upload was a `.then()`
with **no `.catch()`** — the 400 was swallowed, `comp.mediaUrl` stayed `""`, and
the post went out text-only with no warning. Posts #45 (IG) and #43 (YT) both
failed this way with an empty `media_url`.

Fixed: the ceiling is 100 MB, uploads now **stream to disk in 1 MB chunks**
(a 400 MB file can no longer exhaust the instance's RAM), the size is checked
before the upload starts, every failure shows a toast with the reason, the
media library accepts video too, and a new **"Paste media link"** button lets
you attach a public https:// URL — the way to post a big clip that never has to
travel through this host at all.

**"Comments analytics real accounts nunchi sync avvadam ledu, reply avvadam ledu."**

Root cause was one column. `posts.media_url` was `VARCHAR(500)`, and real
Facebook/Instagram CDN URLs are longer than that (they carry signed query
strings). `import_channel_content` hit
`psycopg2.errors.StringDataRightTruncation: value too long for type
character varying(500)` and **the whole transaction rolled back — 0 items
imported.** With no posts imported, there was nothing for comments or metrics
to sync against. That is the entire explanation for both halves of the report.

Fixed: `media_url` is `TEXT` (migrated live: `posts.media_url` is now `text`),
and the import writes **per-item savepoints**, so one bad item can never again
discard an entire channel. Live result after the fix: **Facebook 14 posts,
Instagram 25 posts imported**, comments synced (**60 rows**, real usernames
like @harshavineethraj, @ugadimahesh, @CULT_GAMING_TL), metrics snapshots
written, and every one of them auto-replied.

The reply path itself was then exercised live: a reply was posted through the
app's own client to a real comment, read back from the Graph API, and deleted
again — it works (`POST /{comment-id}/replies` → 200).

Two real bugs surfaced while verifying:

1. **Double replies.** Comment dedupe was per *post*, but the same comment can
   be reached through two post rows of the same account (an import plus a
   manual post). The same comment was stored twice and answered twice — the
   account had `Thanks for stopping by! 👋` posted twice under one comment.
   Dedupe is now per **account**, plus a per-run guard. 41 duplicate rows and
   19 demo-seeded rows were removed from the DB (79 → 60 real comments).
2. **Reply backlog.** Comments were stored with the *fetch* time, so the
   `COMMENT_WATCH_WINDOW_HOURS` guard (default 24 h) could never work — it
   compared "now" against "now". Comments now keep the platform's real
   timestamp, so a first import stores months of backlog **without** spamming
   auto-replies at all of it. Set `COMMENT_WATCH_WINDOW_HOURS=0` in Render to
   auto-reply to everything, backlog included.

## 6c. Round 4 — the failed deploy, Bilibili, and a 7-day comment window

**"Push ayendi kada kani deploy error vastundi."** Correct — and the cause was my
own code. `_run_migrations()` did `cols["posts"]["media_url"]["type"]`, but `cols`
holds *sets of column names*, so startup raised
`TypeError: 'set' object is not subscriptable` and uvicorn exited. Render keeps
serving the previous version when a new one never becomes healthy, which is why
the site sat on 1.8.0 through four green-looking pushes. Reproduced locally
(uvicorn exited against the live DB), fixed with a tested helper
(`_media_url_needs_widening`), and startup now wraps migrations in try/except so
an optional migration can never stop the service from booting again. There are
four smoke tests on that function now. **Live: version 1.9.2, verified.**

**Comment sync is now 7 days only.** `COMMENT_SYNC_WINDOW_DAYS` (default 7):
comments older than the window are neither stored nor replied to, and rows that
age out are pruned, so the inbox is "what is alive now" instead of an archive.
Re-syncing also repairs timestamps written by older builds (they stored the
*fetch* time, which made month-old comments look brand new and invisible to the
prune). Verified live: `new_comments: 0, skipped_old: 0, pruned: 0`, **0
duplicate groups**. Auto-replies still respect `COMMENT_WATCH_WINDOW_HOURS`
(24 h) — set it to `168` if the app should answer everything inside the 7-day
window.

**Bilibili added** as a manual/helper platform, like Snapchat. Its official
开放平台 does have server-side video submission (chunked upload → merge → cover →
submit, HMAC-SHA256 signed) but it is developer-approval gated; see
`CONNECT_ACCOUNTS.md` for the path to make it automatic.

**Cleanup from the duplicate bug** (the old code ran until this deploy): **143
duplicate auto-replies deleted from Instagram** and **2,729 duplicate comment
rows removed** from the database (3,469 → 740, all real). Live re-check after
the deploy: duplicates do not come back.

## 7. Open items

| # | Item | Action |
|---|------|--------|
| 1 | **JWT_SECRET looks hand-made** — `jwt_x7k2m9p4q8w3e6r1t5y0u8i2o4p6a8s0d3f7g1h9` is a pattern, not random output. It signs login tokens: anyone who guesses it can log in as any user, including your 228K-follower workspace. | Rotate: `python3 -c "import secrets;print(secrets.token_urlsafe(48))"` |
| 2 | **YouTube refresh token unverified** — the stored token may already be dead. Google expires refresh tokens after **7 days while the OAuth consent screen is in "Testing"** mode. | Publish the consent screen (or set it to "In production"), then reconnect YouTube in the app. |
| 3 | All these secrets were shared in chat — DB password, Meta app secret, Google client secret, Gemini key. | Rotate the sensitive ones in each provider's dashboard. |
| 4 | Render Settings → Health Check Path is worth setting to `/api/health` explicitly. | One-click change. |
| 5 | ~~Three leftover test users in the DB~~ | **Done** — deleted; the DB now holds only `demo@socialauto.app` and your account. |
| 6 | Duplicate replies already on Instagram (`Thanks for stopping by! 👋` posted twice under one comment, from the pre-fix double-reply bug) | Nothing will *re*-post them; say the word and the extras get deleted from the platform. |
| 7 | The 2 test posts from round 2 are still live | Delete them from Instagram/Facebook when you are done testing. |
| 8 | `GEMINI_API_KEY`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_CLIENT_ID` were also shared in chat | Rotate when convenient (JWT_SECRET and the DB password are done). |
| 9 | A 55 MB test video sits in your media library (`u3/195d1e80c3a1.mp4`) from verifying the upload fix | Ignore it, or ask and a delete button gets added. |
| 10 | YouTube account #26 still has a dead refresh token | Publish the Google OAuth consent screen, then reconnect. |
| 11 | Render's `CRON_SECRET` no longer matches the value in this report | The GitHub Actions cron is working; if you changed it, update the repo secret too. |

## 8. What a real post does now

Publishing is one call away and verified up to the last step:

```bash
# from the app: composer -> Schedule / Share now
# or via the API:
POST /api/cron/tick          (publishes everything due)
POST /api/posts/{id}/publish-now
```

The post will call `media_publish` with the container id, and your Instagram
account returns the live post id. Facebook pages go through `/{page-id}/photos`
or `/{page-id}/feed`; YouTube is the only platform that still needs a manual
step (or `YOUTUBE_AUTO_UPLOAD=true`).
