# Connecting accounts — step by step

> **Comment syncing:** the app only pulls the **last 7 days** of comments
> (`COMMENT_SYNC_WINDOW_DAYS`, default 7). Older comments are neither stored nor
> replied to, and rows that age out are pruned, so the Community inbox stays
> small and current. Auto-replies are limited to `COMMENT_WATCH_WINDOW_HOURS`
> (default 24) — set it to `168` if you want the app to answer everything inside
> the whole 7-day window.

Two kinds of connections live in this app:

| Type | Platforms | Who posts |
|------|-----------|-----------|
| **OAuth** (the app posts for you) | Instagram, Facebook Page, YouTube, Threads\* | the app calls the platform API |
| **Manual / helper** (you post, the app prepares it) | Moj, ShareChat, Snapchat, **Bilibili** | you, in the platform's own app |

\* Threads is OAuth on Meta's side, but this build marks it manual until the
Threads publishing permissions are approved for your Meta app.

---

## 1. OAuth platforms — Instagram, Facebook, YouTube

1. Open **Channels** (left sidebar).
2. Click the platform card, e.g. **Instagram** → *Meta OAuth · photos & reels*.
3. You land on Meta/Google. Log in, and **grant every permission** the screen
   asks for (Instagram: `instagram_basic`, `instagram_content_publish`,
   `instagram_manage_comments`, `pages_show_list`, `pages_read_engagement`,
   `pages_manage_posts`, `business_management`).
4. Pick the Page / Instagram Business account when prompted.
5. You come back to **Channels** with a green `@yourbrand` card. That is the
   connection done.

**YouTube has one extra requirement.** While the Google OAuth consent screen is
in **Testing** mode, Google kills the refresh token after **7 days**, and then
the account silently stops working with
`Google refresh failed 400`. Fix:

> Google Cloud Console → **APIs & Services → OAuth consent screen** →
> **Publish app** (or add yourself as a test user and reconnect every week).
> Then disconnect and reconnect YouTube in the app.

## 2. Manual / helper platforms — Moj, ShareChat, Snapchat, Bilibili

These platforms either have no posting API (Moj, ShareChat) or gate it behind a
partner approval (Snapchat, see §3), so the app prepares the post and you finish
it in the platform's app.

1. **Channels → click the card** (Moj / ShareChat / Snapchat). The
   *Advanced manual connect* section opens with the platform pre-selected.
2. Fill in:
   - **Display name** — anything you recognise, e.g. `@sarvam_snap`.
   - **Account / Page ID** — your username or profile id on that platform.
   - **Access token** — leave **blank** (there is no API to call).
3. Keep **Enable auto-comments** on only if that platform supports comments
   (Moj/ShareChat/Snapchat do not, so it will simply stay quiet).
4. Optional *Fixed reply template*.
5. Click **Add manual account**.

### What happens when a post is due

The post is **not** published silently. In **Posts** it shows up with a
`✋ manual` badge and a helper block:

- **📋 Copy caption** — caption onto your clipboard, ready to paste.
- **⬇️ Download media** — the image/video you attached, ready to upload.
- **👻 Open Snapchat** / **🎬 Open Moj** / **💬 Open ShareChat** / **▶️ Open YouTube Studio**
- **✅ I posted it** — marks the post as published so your calendar and
  analytics stay honest.

Nothing is claimed to be published that wasn't, so your posting streaks and
analytics stay truthful.

## 2b. Bilibili

Bilibili has an official **开放平台 (Open Platform)** with real server-side video
submission (`member.bilibili.com/arcopen/fn/...`: upload pre-processing →
chunked upload → merge → cover → submit, signed with HMAC-SHA256), plus data
APIs for video and account stats. It is **application/approval gated** — you
apply as a developer and are given an access key id + secret — so it also runs
as a manual/helper platform until that approval lands.

Steps to make it automatic: apply on the Bilibili 开放平台, get
`access_key_id` / `access_key_secret` / `access_token`, then send them over and
the client gets wired the same way Instagram and YouTube are. Video uploads are
chunked (no practical size limit) and a cover image is uploaded separately.

Related: `biliup` is a well-known open-source CLI that uploads with a browser
cookie instead of API keys — useful for a one-off bulk upload of your back
catalogue, but not something to put on a server with your account cookie.

## 3. Snapchat — why it is manual, and how to make it automatic later

Snapchat has **no open organic posting API**. Their public developer surface is:

- **Snap Kit / Login Kit** — lets people sign in with Snapchat. No publishing.
- **Marketing API** — advertising.
- **Public Profile API** (inside the Marketing API) — the only way to publish
  Stories, Spotlight and Saved Stories programmatically. It is **partner /
  allowlist gated**: you need a Snap **Business** account, an OAuth app created
  in **Ads Manager**, and Snap's approval. A personal Snapchat account cannot
  post through the API at all.

So today Snapchat uses the manual/helper flow above.

### To unlock automatic Snapchat posting

1. Open the Snapchat app → your profile → **Settings → Public Profile** and
   create one (free — required for API posting; personal accounts are not
   eligible).
2. Create a **Snap Business** account and an **organization** at
   <https://ads.snapchat.com> / Snap Business Manager.
3. In **Business Manager → Business Details → OAuth Apps**, create an OAuth app
   and request the **Public Profile** scope. This is where the allowlist
   approval happens — expect a review, not an instant toggle.
4. Send me three values and I wire the client (about an hour of work):
   `client_id`, `client_secret`, and the redirect URI
   `https://socialauto-k5ou.onrender.com/api/oauth/callback`.
5. Publishing then goes through
   `POST https://businessapi.snapchat.com/v1/public_profiles/{profile_id}/stories`
   (or `/spotlights`), after a chunked + AES-256 media upload
   (`/media/multipart-upload`). Spotlight also needs a `locale` (e.g. `en_IN`)
   and accepts a ≤160-character description — matching the 160-char limit the
   composer already applies to Snapchat.

If Snap approval is too slow, the equivalent without the wait is a social API
aggregator that already holds the allowlist (paid, per post).

## 4. Quick reference

| Platform | Connect how | App can publish? | App can read comments/metrics? |
|----------|-------------|------------------|-------------------------------|
| Instagram | Meta OAuth | ✅ photos, reels | ✅ comments + insights |
| Facebook Page | Meta OAuth | ✅ text, photo, video | ✅ comments + insights |
| YouTube | Google OAuth (publish consent screen!) | ✅ with `YOUTUBE_AUTO_UPLOAD=true`, else upload-by-hand helper | ✅ comments |
| Threads | Meta OAuth (permissions pending) | ✋ manual for now | — |
| Moj | manual connect | ✋ manual | ✋ |
| ShareChat | manual connect | ✋ manual | ✋ |
| **Snapchat** | manual connect | ✋ manual (Public Profile API needs Snap approval) | ✋ |
| **Bilibili** | manual connect | ✋ manual (开放平台 needs developer approval) | ✋ |
