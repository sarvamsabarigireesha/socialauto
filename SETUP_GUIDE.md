# 🔌 Real Connections Setup — Instagram · Facebook · YouTube (100% official APIs)

Everything below is **free**. After setup, set env vars in Render (Environment tab) and
set `MOCK_MODE=false`.

---

## 1) Meta — Instagram + Facebook (one app covers both)

1. Go to **https://developers.facebook.com/** → **My Apps → Create App** → type **Business**.
2. Add products: **Facebook Login for Business**, **Instagram Graph API**, **Webhooks**.
3. Settings → Basic: copy **App ID** + **App Secret** → env:
   - `META_APP_ID=...`
   - `META_APP_SECRET=...`
4. **Connect an Instagram account / Facebook Page** (you need an IG Business/Creator account
   linked to a Facebook Page — free to convert in IG settings).
5. **Webhooks (real-time comments — no 15-min wait):**
   - App → Webhooks → **Page** (and **Instagram**) → Callback URL:
     `https://YOUR-APP.onrender.com/api/webhooks/meta`
   - Verify token: the value of `META_VERIFY_TOKEN` (default `socialauto-verify-token`)
   - Subscribe fields: **`comments`** (and `feed` for pages).
6. App Review: for *your own* pages/IG, add yourself as **Admin/Tester** (Roles → Roles) and
   no review is needed to test. Public launch for other users requires Meta App Review of
   `instagram_basic`, `pages_manage_posts`, `pages_read_engagement`, `pages_manage_engagement`.

## 2) Google — YouTube Data API v3 (Google Cloud free tier)

1. **https://console.cloud.google.com/** → create project → **APIs & Services → Library**
   → enable **YouTube Data API v3**.
2. **OAuth consent screen** → External → add your Gmail as a **Test user** (or publish for others).
3. **Credentials → Create Credentials → OAuth client ID → Web application**:
   - Authorized redirect URI:
     `https://YOUR-APP.onrender.com/api/oauth/callback`
   - Copy Client ID + Secret → env:
     - `GOOGLE_CLIENT_ID=...`
     - `GOOGLE_CLIENT_SECRET=...`
4. Free quota: **10,000 units/day** — reads are 1 unit each; video uploads cost 1,600
   (~6 uploads/day free). Comment replies/reads are cheap.
5. In the app: Accounts tab → **▶️ YouTube Connect** → pick your channel → done.

## 3) X / LinkedIn (optional)
- X: https://developer.twitter.com → Project → OAuth 2.0 → redirect URI `.../api/oauth/callback`
  → `X_CLIENT_ID`, `X_CLIENT_SECRET`.
- LinkedIn: https://www.linkedin.com/developers → App → OAuth 2.0 →
  `LINKEDIN_CLIENT_ID`, `LINKEDIN_CLIENT_SECRET`.

## 4) Production env vars (Render → Environment)
```
MOCK_MODE=false
APP_PUBLIC_URL=https://YOUR-APP.onrender.com
JWT_SECRET=<long random string>
CRON_SECRET=<long random string>
DATABASE_URL=<Neon connection string>
META_APP_ID=...
META_APP_SECRET=...
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
META_VERIFY_TOKEN=socialauto-verify-token
```

---

## ✅ Safe / ban-free design (resume-friendly)

| Built ✅ | Intentionally NOT built ❌ |
|---|---|
| Official Graph/YouTube/LinkedIn APIs + OAuth | Bulk unsolicited DMs (spam → bans, ToS violation) |
| Scheduling (≤ your own normal posting cadence) | Mass follow/like/comment bots |
| Auto-replies to comments **on your own posts** | Scraping / fake accounts |
| Webhook-based real-time moderation | Aggressive rate-limit hammering |
| Per-account reply templates + human-like varied replies | Identical copy-paste spam comments |

This is a **legit social-media management tool** (Publer/Buffer/Meta Business Suite category) —
safe to deploy and to put on a resume.
