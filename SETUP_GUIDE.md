# 🔌 Real Accounts Connect — Step-by-Step (Instagram · Facebook · YouTube · Threads)

App live: **https://socialauto-k5ou.onrender.com** · Admin login = your signup (demo: `demo@socialauto.app` / `demo1234`)

Everything below is **FREE**. Total time: ~25 minutes. After setup, set env vars in
**Render → your service → Environment**, then set `MOCK_MODE=false`.

---

## PART 1 — Meta Developer App (Instagram + Facebook + Threads, one app)

### A. Prepare your socials (one time)
1. Instagram app → Settings → Account type → switch to **Professional** (Business or Creator — free).
2. Create/own a **Facebook Page** (any Page, even empty) and link it to that IG account:
   IG → Edit profile → Page → connect/create Page.
   *(Instagram Graph API only works with an IG Professional account linked to a FB Page.)*

### B. Create the app
1. Go to **https://developers.facebook.com/** → login with your Facebook → **My Apps → Create App**.
2. Type: **Business** → name it `SocialAuto` → Create.
3. Dashboard → **Add products**: add **Instagram Graph API**, **Facebook Pages API** (or "Pages"),
   and **Webhooks**.

### C. Copy credentials
1. Left menu → **App settings → Basic**.
2. Copy **App ID** and **App Secret** (click Show, enter password).
   → these become `META_APP_ID` and `META_APP_SECRET`.

### D. Add yourself as tester/admin (so NO app review is needed for YOUR accounts)
1. Left menu → **App roles → Roles**.
2. **Add People** → add your own Facebook account as **Administrator/Tester** and accept the invite
   on your Facebook (notifications/business.facebook.com).
3. With your own pages, content publishing + comment replies work even while the app is in
   **Development mode**. (App Review is only required when OTHER people's accounts will connect.)

### E. Webhooks — real-time comments (instant auto-replies)
1. Left menu → **Webhooks** → select object **Page** → **Add callback URL**:
   - Callback URL: `https://socialauto-k5ou.onrender.com/api/webhooks/meta`
   - Verify token: `socialauto-verify-token`  ← (value of `META_VERIFY_TOKEN`; you can keep default)
2. Click **Verify and save**. After subscribe, tick fields: **`comments`**, **`feed`**, **`mentions`**.
3. Also add the same callback URL under the **Instagram** object and subscribe to **`comments`**.
4. On the same screen click **"Subscribe"** for each Page you manage.

### F. Threads (optional, same Meta app)
- Threads API uses the same App ID/Secret. Request access at
  **https://developers.facebook.com/docs/threads** (Threads API access is granted in app dashboard;
  for your own Threads account it works once approved — typically instant for dev apps).

---

## PART 2 — Google Cloud (YouTube Data API, free tier)

1. Go to **https://console.cloud.google.com/** → login with your YouTube Google account →
   top bar → **Select a project → New Project** → name `SocialAuto` → Create.
2. Left menu → **APIs & Services → Library** → search **"YouTube Data API v3"** → **Enable**.
3. Left menu → **APIs & Services → OAuth consent screen**:
   - User type: **External** → Create.
   - App name: `SocialAuto`, support email: your Gmail, developer email: your Gmail → Save.
   - **Test users → Add users** → add YOUR OWN gmail (the channel owner).
     (In "Testing" mode only test users can connect — perfect for you; publish later for others.)
4. Left menu → **Credentials → + Create Credentials → OAuth client ID**:
   - Application type: **Web application**.
   - **Authorized redirect URIs → Add URI**:
     `https://socialauto-k5ou.onrender.com/api/oauth/callback`
   - Create → copy **Client ID** and **Client Secret**.
   → these become `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`.
5. Free quota: **10,000 units/day** — reading comments = 1 unit, replying = cheap,
   video upload = ~1,600 units (≈6 uploads/day free).

> Your Google account must have a **YouTube channel** (create one at youtube.com if prompted).

---

## PART 3 — AI captions (Google Gemini, free — optional but recommended)

1. Go to **https://aistudio.google.com/apikey** → login with Google → **Create API key**.
2. Copy the key (`AIza...`) → becomes `GEMINI_API_KEY`.
3. Free tier: 15 requests/minute, hundreds/day — more than enough. The AI then:
   - reads your **uploaded image** and suggests captions (vision),
   - generates hashtags, SEO keywords, disclaimers, YouTube titles.
   Badge in composer changes from "smart rules" to **"Gemini AI"**.

---

## PART 4 — Put everything into Render

**Render dashboard → socialauto service → Environment → Add Environment Variable:**

| Key | Value |
|---|---|
| `MOCK_MODE` | `false` |
| `APP_PUBLIC_URL` | `https://socialauto-k5ou.onrender.com` |
| `JWT_SECRET` | any long random string (e.g. 40+ chars) |
| `CRON_SECRET` | a long random string (the SAME one you put in GitHub secrets) |
| `DATABASE_URL` | Neon Postgres string (already set) |
| `META_APP_ID` | from Part 1-C |
| `META_APP_SECRET` | from Part 1-C |
| `META_VERIFY_TOKEN` | `socialauto-verify-token` |
| `GOOGLE_CLIENT_ID` | from Part 2-4 |
| `GOOGLE_CLIENT_SECRET` | from Part 2-4 |
| `GEMINI_API_KEY` | from Part 3 |

Save → Render auto-redeploys (~2 min).

---

## PART 5 — Connect inside the app

1. Open https://socialauto-k5ou.onrender.com → log in.
2. **Accounts tab** → click **📸 Instagram** / **👍 Facebook Page** → a Meta login popup opens →
   accept permissions → both your FB Page **and** linked IG account appear as connected channels.
3. Click **▶️ YouTube** → choose your Google account → "SocialAuto wants access…" → Continue
   (it says unverified because consent screen is in Testing — that's fine, you're a test user) →
   your YouTube channel appears.
4. 🧵 Threads similarly once Threads API access is on.
5. **Community tab → "🔄 Fetch latest comments"** now pulls REAL comments from your posts →
   auto-replies fire (webhook = instant; cron = every 15 min) → you can also type **manual replies**.
6. **Create Post**: pick IG + FB + YouTube → attach photo → **✨ AI suggest** → schedule.
   Posts publish to the real platforms at the scheduled time.

---

## ✅ Safety / ban-free design

| Built ✅ | NOT built ❌ |
|---|---|
| Official Graph / YouTube Data / Threads APIs + OAuth | Bulk unsolicited DMs |
| Scheduling at your normal cadence | Mass follow/like/comment bots |
| Replies to comments **on your own posts** | Fake accounts / scraping |
| Human-like varied replies + manual control | API rate-limit hammering |

## 🔧 Troubleshooting
- **"Invalid OAuth redirect_uri"** → exact URI from Part 2-4 must match (https, no trailing slash).
- **Meta popup says app in development** → normal; just be added as Admin/Tester (Part 1-D).
- **IG connect shows nothing** → IG must be Professional + linked to a FB Page (Part 1-A).
- **Webhook verify fails** → check `META_VERIFY_TOKEN` matches and app is deployed with the env var.
- **YouTube upload fails** → uploads use quota; check API enabled and channel exists.
