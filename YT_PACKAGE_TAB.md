# 🪔 YT Package tab — SocialAuto integration

Adds a **YouTube packaging + season planner** to the SocialAuto dashboard, for the
Sarvam Sabarigireesha channel. One nav tab, one lazy iframe, one FastAPI router,
zero new dependencies, zero DB tables, no secrets.

## What you get
| Piece | Path | What it does |
|---|---|---|
| Dashboard tab | `frontend/index.html` (nav item + `view-ytpackage` section) | 🪔 **YT Package** in the side-nav; iframe lazy-loads on first click |
| Tool UI | `frontend/yt-package.html` | Scanner · Generator · Hook Lab · Viral Lab · Season/Audit · Rules |
| Shared rules (JS) | `frontend/yt-rules.js` | `window.YtRules` — same ruleset, callable from the composer |
| Rules engine (Py) | `backend/app/services/ytrules.py` | `analyze / auto_clean / viral_score / trend_plan` — stdlib only |
| API | `backend/app/routers/yt.py` | 5 endpoints under `/api/yt/*`, behind their existing `get_current_user` |
| Tests | `backend/tests/test_ytrules.py` | 12 tests, fixtures = real channel metadata |

## Apply
```bash
git checkout -b feat/yt-package-tab
git apply yt-package-tab.patch          # or: git am < yt-package-tab.patch (after commit)
cd backend && python -m pytest tests/test_ytrules.py -q      # 12 passed
uvicorn app.main:app --host 0.0.0.0 --port 8000              # MOCK_MODE=true default
# open http://localhost:8000 → log in (demo@socialauto.app / demo1234) → 🪔 YT Package
```

## API (all authenticated, same bearer token as the rest of SocialAuto)
```
POST /api/yt/check     {title, description, tags, format}   → {score, grade, issues[]}
POST /api/yt/clean     same                                  → {title, description, tags, removedLines}
POST /api/yt/package   + {event_date, lead_days[]}           → {report, cleaned, publishable, schedule}
GET  /api/yt/checklist                                        → {items[12], threshold:85}
GET  /api/yt/trend?event=2026-11-16&lead=21,14                → {daysOut, rows[9]}
```
`grade`: `ready` (≥85) · `minor` (70–84) · `fix` (<70 → don't publish).

## Rules it enforces (why each exists)
- **Keyword dumps** (`🔎 SEO Keywords:`, `Long-Tail SEO Keywords:`, comma lists, 5+ line latin runs) → `err` — YouTube ignores them, they read as spam.
- **Hashtags > 3** and duplicates → `warn`.
- **Hashtags / `trending` / `viral` / "WhatsApp Status" in the title** → `warn`/`err` — kills CTR, no search intent.
- **Date-first title** → `warn` (auto_clean moves the date to the end).
- **No Telugu in title/description** → `warn` — this channel's audience searches Telugu-first.
- **Tags**: >12 or >500 chars → `warn`/`err` (Studio limits); generic tags → `warn`; brand tag missing → `info`.
- **Long-form/live**: no `0:00` chapters → `warn`; no playlist link → `info`.
- **Seva videos** (annadanam/donation words) without a "మేము డొనేషన్స్ తీసుకోం / we don't collect" statement → `warn`.
  It matches the *statement*, not the word "donation" — keyword lists don't fool it.
- **Bhakti videos** without an "ఇది అధికారిక ఆలయ చానల్ కాదు" note → `info` (impersonation-complaint shield).

## Suggested next step: gate the composer (10 lines, not in this patch)
`frontend/index.html` — inside the composer's save handler, when the selected account's
platform is `youtube`, validate before queueing:
```js
if (acc.platform === 'youtube' && window.YtRules) {
  const r = YtRules.analyze({title: capTitle?.value || '', description: caption.value, tags: ytTags?.value || '', format: 'short'});
  if (r.grade === 'fix') { toast('YT Package: ' + r.issues[0].head + ' — fix before queueing'); }
  else if (r.issues.length) toast('YT Package: ' + r.issues.length + ' suggestion(s), score ' + r.score);
}
```
Or server-side (blocks the API too, useful for bulk CSV): in `backend/app/routers/posts.py`
`create_post`, when `platform == Platform.youtube`, call
`ytrules.analyze(...)` and reject with `HTTPException(422, detail=json.dumps(report["issues"]))`
only when `grade == "fix"` — keep it a warning if you'd rather not block publishing.

## Notes / gotchas found while wiring this up
1. **Static paths.** SocialAuto mounts `frontend/` at **`/static`** and serves `index.html`,
   `sw.js`, `manifest.webmanifest`, `offline` through explicit handlers. So the tab must be
   `/static/yt-package.html`, **not** `/yt-package.html` (that 404s — caught in testing).
2. **`TITLES[view]` is unguarded** in `switchView()` (`TITLES[view][0]`). Any new `data-view`
   **must** get a `TITLES` entry or the whole dashboard throws. The patch adds it.
3. **PWA cache.** `sw.js` PRECACHE got both new paths and `CACHE` bumped `v1.9.8 → v1.9.9`,
   otherwise phones keep the old shell and the tab never appears until a manual refresh.
4. **FastAPI route listing.** On recent FastAPI, `app.include_router` is lazy
   (`_IncludedRouter`), so `app.routes` looks empty in tests — verify with `TestClient`
   (which runs startup) instead of introspecting `app.routes`.
5. **No secrets here.** The tab stores nothing server-side; all UI state is `localStorage`.
   Nothing to add to `.env`. (Their README's own note about plaintext `access_token` at
   rest still applies to the platform tokens — unrelated to this feature.)
6. **Mobile:** the tool page is responsive and offline-capable; through the PWA it works in
   the installed app like the rest of SocialAuto.

## Verified (in this workspace, against a real clone at commit 08716c0)
- `pytest tests/test_ytrules.py` → **12 passed**
- End-to-end `TestClient` against their app: **11 passed** — 401 without token, demo login,
  `/api/yt/check` blocks their real dirty Annadanam description (score 40), `/clean` strips
  the dump to exactly 3 hashtags, `/package` returns report+cleaned+9-step schedule
  (`publishable: false`), their new 7 Oct Short passes (score 97), dashboard contains the
  nav item + section + loader, `/static/yt-package.html` + `/static/yt-rules.js` → 200,
  `/yt-package.html` → 404 (expected), `sw.js` precache + version bump.
- JS/Python rule parity: 8 real-metadata cases → identical scores + identical issue codes.
- Syntax: patched inline `<script>` and `yt-rules.js` pass `node --check`; no duplicate DOM ids.
- Not tested: real browser click-through of the iframe (no GUI here) and YouTube API publish
  path (needs live credentials) — run `LIVE_TESTING.md` steps if you wire the server-side gate.
