# ⚡ SocialAuto — Free-Tier Social Media Automation Webapp (Publer-style)

**Calendar view · Rich composer with live per-platform previews · Media library · Bulk CSV scheduling · Auto-comments (intent-based smart replies) · Analytics** — across **Instagram, Facebook, YouTube** (plus manual-helper support for Threads, Moj, ShareChat). Runs 100% on free tiers. Works in **MOCK MODE** with zero credentials so you can demo it instantly.

### Dashboard features (like Publer)
- 📅 **Monthly calendar** — color-coded posts per platform; click a day to create, click a post to edit
- ✏️ **Composer modal** — multi-account selector, live platform preview cards, per-platform character counters (IG 2200 / FB 2200), attach media, schedule or *Publish now*
- 🖼 **Media library** — upload images once (drag & drop), reuse in any post; demo images pre-seeded
- ✏️ **Edit / delete / publish-now** any scheduled post (`PATCH /api/posts/:id`)
- 📦 **Bulk CSV** upload — hundreds of posts × multiple accounts in one request
- 💬 **Auto-comment inbox** with intent-based replies (question / praise / purchase / support)
- 📊 **Analytics** — likes, comments, shares, impressions, reach per platform and per post

## 🏗 Architecture

```
                         ┌──────────────────────────────────────────────┐
                         │            FREE SCHEDULERS (pick any)         │
                         │  GitHub Actions cron  */15  (2000 min/mo)     │
                         │  Cloudflare Worker cron (100k req/day)        │
                         │  n8n self-hosted (free, visual workflow)      │
                         └───────────────────┬──────────────────────────┘
                                             │ POST /api/cron/tick
                                             │ header: X-Cron-Secret
                                             ▼
   Browser ──────►  ┌─────────────────────────────────────────────┐
   (dashboard)      │           FastAPI app (Cloud Run free /      │
                    │           Fly.io / Render / GCP free tier)   │
                    │                                              │
                    │  /api/posts     schedule + bulk CSV upload   │
                    │  /api/comments  inbox + auto-reply engine    │
                    │  /api/analytics aggregated dashboard stats   │
                    │  /api/accounts  connect social accounts      │
                    │  /api/cron/tick protected scheduler endpoint │
                    │                                              │
                    │  Services layer:                             │
                    │   • publisher   (due posts → platform APIs)  │
                    │   • autocomment (intent detection → replies) │
                    │   • analytics   (metrics snapshots)          │
                    └───────┬──────────────────────┬───────────────┘
                            │                      │
                            ▼                      ▼
              ┌────────────────────┐   ┌─────────────────────────┐
              │  SQLite / Turso /  │   │  Platform APIs (free):  │
              │  Neon Postgres     │   │  Meta Graph (IG/FB)     │
              │  (posts, comments, │   │  Meta Graph (IG/FB)     │
              │   metrics)         │   │  YouTube Data API v3    │
              └────────────────────┘   └─────────────────────────┘
```

### Cron tick = one call does everything
`POST /api/cron/tick` runs 3 jobs in order:
1. **Publish** every scheduled post whose time has arrived
2. **Sync comments** on recent posts → run auto-comment engine on each new comment
3. **Sync analytics** → store a metrics snapshot (likes/comments/shares/impressions/reach)

## 🤖 Auto-comment engine (`app/services/autocomment.py`)

Rule-based intent detection — swap `generate_reply()` for an LLM (free Gemini/Groq tier) later, same signature:

| Intent | Trigger words | Reply style |
|---|---|---|
| `question` | how, what, when, ? | "Great question! DMing you details 🙌" |
| `praise` | love, amazing, 🔥❤️ | "Thank you! Means a lot ❤️" |
| `purchase_intent` | price, want, buy, link, DM | "Sent you the link in DM 🛍" |
| `support` | refund, problem, not working | "Sorry! Let's fix it — DM sent 🙏" |
| `generic` | anything else | "Thanks for commenting! 👋" |

Per-account override: set a **fixed reply template** and every comment gets that.

## 🚀 Run locally

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
# open http://localhost:8000  — demo data auto-seeds in MOCK_MODE
```

## 📦 Bulk scheduling

- **UI:** Bulk/CSV tab → drag-drop a CSV → each row posts to every selected account
- CSV format: `caption,media_url,scheduled_at` (template downloadable in the UI)
- **API:** `POST /api/posts/bulk` (JSON rows) or `POST /api/posts/bulk/csv?account_ids=1,2` (multipart file)
- 500 rows × 4 accounts = 2,000 posts in one request

## ☁️ Free-tier deployment (₹0/month)

| Piece | Service | Free allowance |
|---|---|---|
| App | Google Cloud Run / Fly.io / Render | 2M requests/mo |
| Scheduler | GitHub Actions (`.github/workflows/cron.yml`) | 2,000 min/mo private, ∞ public |
| Edge cron | Cloudflare Worker (`cloudflare/worker.js`) | 100k requests/day |
| No-code | n8n self-hosted (`n8n/socialauto-workflow.json`) | open source, free |
| Database | Turso (libSQL) / Neon Postgres | 9GB / 0.5GB free |
| APIs | Meta Developer, Google Cloud (YouTube) | free (Meta needs app review for advanced perms) |

**Go live:**
```bash
# 1. set env vars (see .env.example): MOCK_MODE=false, CRON_SECRET, platform tokens
# 2. deploy container
gcloud run deploy socialauto --source . --region asia-south1 --allow-unauthenticated \
  --set-env-vars MOCK_MODE=false,CRON_SECRET=your_long_secret
# 3. GitHub repo → Settings → Secrets: APP_URL, CRON_SECRET
#    Actions cron then publishes/auto-replies every 15 minutes
```

## 🗂 Project structure

```
socialauto/
├── backend/
│   ├── app/
│   │   ├── main.py            # FastAPI app + demo seeding + static hosting
│   │   ├── config.py          # env-driven settings (MOCK_MODE, tokens, secrets)
│   │   ├── models.py          # Account, Post, Comment, Metric
│   │   ├── schemas.py         # pydantic I/O
│   │   ├── routers/           # accounts, posts, comments, analytics, cron
│   │   └── services/
│   │       ├── platforms.py   # mock client + real Meta/YouTube clients
│   │       ├── autocomment.py # intent detection + smart replies
│   │       └── engine.py      # publish / sync comments / sync analytics jobs
│   └── requirements.txt
├── frontend/index.html        # single-file dark dashboard (no build step)
├── .github/workflows/cron.yml # free GitHub Actions scheduler
├── cloudflare/worker.js       # edge cron alternative
├── n8n/socialauto-workflow.json
├── Dockerfile
└── .env.example
```

## ⚠️ Prod notes
- Encrypt `access_token` at rest (e.g. Google KMS / Fernet) — shown plaintext only for demo simplicity.
- Respect each platform's rate limits & automation policies; prefer official Graph API flows.
- Add OAuth token refresh for long-lived Meta pages.
```
