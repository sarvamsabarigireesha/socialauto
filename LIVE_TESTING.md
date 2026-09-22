# Real posting test — Instagram, Facebook, YouTube

The app runs in `MOCK_MODE=true` by default (every publish is simulated). This
is how to prove real posting works, cheapest first.

## What was fixed for this (2026-09-22)

| Issue | Why it blocked real posting |
|-------|-----------------------------|
| `config.py` never read `.env` | You could copy `.env.example` → `.env`, fill in every key, and the app would still see nothing. Real env vars (`export`/Render) still win; `.env` only fills gaps. |
| YouTube upload passed a file object to `AsyncClient.put` | httpx raises `Attempted to send an sync request with an AsyncClient instance` → **every** real YouTube upload would have failed. Now streamed with an async generator. |
| YouTube publish was a hard `manual=True` stub | There was no code path to upload at all. Now implemented (resumable upload) and opt-in. |

New tools: `backend/live_check.py` (preflight + real publish) and
`backend/contract_test.py` (verifies our parsing against real API response
shapes, no credentials needed).

---

## Step 0 — always run the preflight first

```bash
cd backend
python3 live_check.py            # offline: which keys are missing
python3 live_check.py --online   # read-only calls that prove the keys work
```

It tells you exactly what to fix, e.g.:

```
[4] public URL (Instagram needs to *fetch* your media)
  ❌ APP_PUBLIC_URL is empty
       ↳ Instagram must download your image/video from a public https URL.
         localhost won't work — deploy, then set this to https://your-app.onrender.com
```

> **The #1 gotcha:** Instagram does not accept an upload from your server. It
> fetches the image/video **itself** from a public `https://` URL. `localhost`
> and `http://` are rejected with a 9004/100 error. So real Instagram posting
> requires the app to be deployed (Render/Railway free tier is enough) or the
> media to be hosted somewhere public.

---

## Instagram + Facebook (Meta Graph API)

Free. You need a **Business/Creator** Instagram account linked to a Facebook Page.

1. **Create the app** — [developers.facebook.com](https://developers.facebook.com) → My Apps → Create App → type **Business**.
2. **Add products** — Instagram Graph API, and (for FB Pages) Facebook Login.
3. **Copy credentials** — Settings → Basic → App ID + App Secret → into `.env`:
   ```
   MOCK_MODE=false
   META_APP_ID=1234567890
   META_APP_SECRET=abcdef...
   META_GRAPH_VERSION=v21.0
   APP_PUBLIC_URL=https://your-app.onrender.com
   JWT_SECRET=<random 48+ chars>
   CRON_SECRET=<random 48+ chars>
   ```
4. **Redirect URI** — Facebook Login → Settings → Valid OAuth Redirect URIs →
   add `https://your-app.onrender.com/api/oauth/callback`
   (must match `APP_PUBLIC_URL` + `/api/oauth/callback` exactly).
5. **Get a Page token the fast way** (no redirects) —
   [Graph API Explorer](https://developers.facebook.com/tools/explorer) →
   select your app → Permissions: `pages_show_list, pages_manage_posts,
   instagram_basic, instagram_content_publish, instagram_manage_comments` →
   **Generate Access Token** → click the dropdown → select your **Page** →
   "Get Page Access Token" → paste into `.env` as `META_ACCESS_TOKEN=EAAG...`.
6. **Find your IG user id** — in the Explorer run
   `GET /me/accounts?fields=id,name,instagram_business_account` → copy the
   `instagram_business_account.id` (starts with `17841…`).

### Run the real post

```bash
cd backend
python3 live_check.py --direct instagram:17841400000000000 \
  --media https://your-cdn.com/test.jpg \
  --caption "SocialAuto live test 🧪" --yes
```

Success looks like:

```
  ok     : True
  id     : 17890000000000001
✅ REAL POST SUCCEEDED — live id 17890000000000001
```

Facebook Pages are the same but easier (no media required):

```bash
python3 live_check.py --direct facebook:YOUR_PAGE_ID --media https://x/y.jpg --yes
# text-only also works for FB: the client automatically uses /feed
```

> **Limits:** Instagram allows **50 published posts per 24 h** per account, and
> a brand-new app is in *Development mode* — posting works for accounts with a
> role on the app. Switch to **Live** before other people use it.
> Test posts really do appear on your profile; delete them after.

---

## YouTube

Free quota: **10,000 units/day**. One `videos.insert` costs **1,600** → about
**6 uploads/day**. (Listing uses the uploads playlist = 1 unit; `search.list`
would cost 100 — that's why the importer doesn't use it.)

1. [console.cloud.google.com](https://console.cloud.google.com) → new project.
2. **APIs & Services → Library** → enable **YouTube Data API v3**.
3. **OAuth consent screen** → External → add your own Google account as a **Test user**
   (otherwise you get `access_denied`).
4. **Credentials → Create credentials → OAuth client ID → Web application** →
   Authorised redirect URI: `https://your-app.onrender.com/api/oauth/callback`.
5. Put the pair in `.env`:
   ```
   GOOGLE_CLIENT_ID=....apps.googleusercontent.com
   GOOGLE_CLIENT_SECRET=GOCSPX-...
   YOUTUBE_AUTO_UPLOAD=true
   YOUTUBE_PRIVACY_STATUS=private
   ```
6. Quick test without the redirect flow: [OAuth 2.0 Playground](https://developers.google.com/oauthplayground)
   → scope `https://www.googleapis.com/auth/youtube.force-ssl` → Authorise →
   exchange for tokens → put the access token in `.env` as `GOOGLE_ACCESS_TOKEN`.

```bash
python3 live_check.py --direct youtube:UC_your_channel_id \
  --media https://your-cdn.com/test.mp4 --yes
```

`YOUTUBE_PRIVACY_STATUS` defaults to `private` on purpose — flip it to `public`
only when you want scheduled posts going live to subscribers.

---

## After the first success — test the whole pipeline

Once tokens are in the DB (via the app's Connect button, not `--direct`):

```bash
python3 live_check.py --online          # every stored token verified
```

Then in the dashboard: create a post 2 minutes in the future → wait for the cron
tick (or `curl -X POST localhost:8000/api/cron/tick -H "X-Cron-Secret: $CRON_SECRET"`)
→ the post should flip to `published`, and comments/metrics start filling in.

---

## Security

* Never commit `.env` — it is already in `.gitignore`.
* Revoke any token you pasted into a chat: GitHub tokens, Page tokens, and
  Google refresh tokens are all full credentials.
* Set `JWT_SECRET` and `CRON_SECRET` to random values before going live
  (`python3 -c "import secrets;print(secrets.token_urlsafe(48))"`). The app
  refuses cron calls in non-mock mode while `CRON_SECRET` is the dev default.
