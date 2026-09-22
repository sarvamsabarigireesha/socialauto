# Code review + fixes (2026-09-22)

Repo was reviewed end-to-end. It did **not** boot at all — 4 blocking bugs plus
2 correctness bugs were found and fixed. A full API smoke test was added.

## Blocking bugs (app crashed on startup / on request)

| # | Where | Problem | Fix |
|---|-------|---------|-----|
| 1 | `backend/app/services/engine.py:2-3` | `from ...config import settings` — 3 dots escapes the top-level package → `ImportError: attempted relative import beyond top-level package`. `/api/posts`, cron, analytics, community were all dead. | Changed to `from ..config` / `from ..models`. |
| 2 | `backend/app/services/engine.py` | The module was **truncated**: `_aware`, `next_slot_for`, `reorder_queue`, `publish_one`, `publish_due_posts`, `analytics_summary`, `auto_import_all`, `import_channel_content`, `simulate_incoming_comment`, `sync_comments`, `sync_metrics` were called by routers but never defined (`posts.py` couldn't even import). | Rebuilt the whole engine layer on top of `services/platforms.py` (slot scheduler, publisher with atomic claim, comment sync + auto-reply, metrics sync, channel import, analytics aggregation). |
| 3 | `backend/app/routers/media.py` | `main.py` does `from .routers.media import MEDIA_DIR`, but the constant was never defined (only a local variable inside the upload handler). | Added module-level `MEDIA_DIR` (+ `mkdir`) and reused it in the handler. |
| 4 | `cloudflare/worker.js:14` | The doc comment contained `crons = ["*/15 * * * *"]` — the `*/` closed the block comment early → **JS SyntaxError**, the cron Worker could never deploy. | Rewrote as `["0,15,30,45 * * * *"]` (same schedule, no `*/`). |

## Correctness bugs

**Timezone shifting every scheduled post (models.py).**
SQLite/Postgres `TIMESTAMP WITHOUT TIME ZONE` drop the offset, so the API
returned naive datetimes like `2026-09-22T09:00:00`. The browser then parsed
that as *local* time, so every scheduled/published time in the UI was off by
the IST offset (and "publish due" comparisons were fragile). Added a
`UTCDateTime` column type (stores naive UTC, returns tz-aware UTC) and applied
it to all 12 datetime columns. No migration needed — existing rows read back
correctly.

**Background import used a dead DB session (oauth.py).**
`_finish()` did `asyncio.create_task(engine.auto_import_all(db, …))` with the
request-scoped session, which `get_db()` closes as soon as the response is
sent → the "import my existing content" task always failed silently. It now
runs on its own `SessionLocal()` session.

## Features that were wired but not implemented (real mode)

`platforms.py` stubbed out the read side, so "Import existing content",
"Comment sync" and "Analytics" did nothing on a real account:

* `_MetaClient.list_recent_videos` → IG `/{id}/media`, FB `/{page}/posts`
* `_MetaClient.fetch` → likes/comments/shares + `/{post}/comments`
* `_YouTubeClient.list_recent_videos` → uploads playlist (1 quota unit, not `search.list`'s 100)
* `_YouTubeClient.fetch` → video `statistics` + `commentThreads`
* `_YouTubeClient.reply_to_comment` → real `comments.insert` (was hardcoded `False`)

## Housekeeping

* unused imports removed (`os`, `func`, `Account`, `Platform`, `create_token`, `decode_token`)
* `raise ... from exc` on the 6 exception chains ruff flagged (B904)
* `backend/smoke_test.py` added — 75 assertions covering every router

## Verification

```
$ python3 -m ruff check backend --select F,B904      # All checks passed!
$ MOCK_MODE=true python3 smoke_test.py               # PASSED: 75   FAILED: 0
```

Covers: auth + password reset, accounts, slots, tags, posts (create / queue /
per-account variants / draft / bulk / CSV / reorder / publish-now / mark-done),
comments + simulate, community inbox (reply, resolve, import, bootstrap-sync),
analytics + CSV export, cron tick + secret guard, ideas, templates, links,
media upload, AI endpoints, Meta webhook verification, dashboard HTML.
