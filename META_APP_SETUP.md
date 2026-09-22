# SocialAuto — Meta App (Instagram + Facebook)

You cannot create the Meta Developer app from this repo — Facebook requires
**your** Facebook login. This file is the exact click-path. After you have
App ID + Secret, paste them in **Channels → Meta App setup** (or env vars).

Live callback URLs (replace with your public https URL):

```
OAuth redirect:  https://YOUR-DOMAIN/api/oauth/callback
Webhook:         https://YOUR-DOMAIN/api/webhooks/meta
Verify token:    socialauto-verify-token
```

---

## 0. Prepare Instagram + Facebook (5 min)

1. Instagram app → **Settings → Account type** → switch to **Professional**
   (Business or Creator — free).
2. Create a **Facebook Page** (even an empty one).
3. Link them: Instagram → **Edit profile → Page** → connect that Page.
   Graph API only works for IG Professional accounts linked to a Page.

---

## 1. Create the Meta app (2 min)

1. Open [developers.facebook.com/apps/creation](https://developers.facebook.com/apps/creation/)
   and log in with the Facebook account that **owns the Page**.
2. **Create App**.
3. Use case: **Other** → Next.
4. App type: **Business** → Next.
5. App name: `SocialAuto`. Contact email: yours.
6. Business portfolio: leave **No business portfolio selected** if you don't have one.
7. **Create app**.

---

## 2. Add products

On **Add products to your app**:

| Product | Why |
|---|---|
| **Facebook Login for Business** | OAuth popup (required) |
| **Instagram** (Graph API / API setup) | Publish photos, Reels, comments |
| **Webhooks** | Instant comment auto-replies |

### Facebook Login for Business

1. Product → **Facebook Login for Business → Settings**.
2. **Valid OAuth Redirect URIs** → paste:
   `https://YOUR-DOMAIN/api/oauth/callback`
   (exact match, `https`, no trailing slash)
3. Save changes.

If you cannot find that field: **Use cases → Customize** (Authentication and
account creation) → **Go to settings** → Valid OAuth Redirect URIs.

### Webhooks

1. **Webhooks** → object **Page** → Add callback URL:
   - Callback: `https://YOUR-DOMAIN/api/webhooks/meta`
   - Verify token: `socialauto-verify-token`
2. Verify and save. Subscribe fields: **`comments`**, **`feed`**, **`mentions`**.
3. Repeat for object **Instagram** → field **`comments`**.

The app also subscribes each Page automatically after you click Connect.

---

## 3. Copy App ID + Secret

**App settings → Basic**

- **App ID** → `META_APP_ID`
- **App Secret** (Show) → `META_APP_SECRET`

---

## 4. Add yourself as admin (skip App Review for your own accounts)

**App roles → Roles → Add People** → your Facebook account as **Administrator**.
Accept the invite on Facebook.

Development mode is enough for Pages / IG accounts **you** admin. App Review
is only required when *other people* will connect their accounts.

---

## 5. Paste into SocialAuto

**In the dashboard (recommended)**

1. Log in → **Channels**.
2. **Meta App setup** card.
3. Paste App ID + Secret.
4. Tick **Turn MOCK MODE off**.
5. **Save Meta app** → **Test credentials**.
6. **Connect Instagram** (also connects every Facebook Page you manage).

**Or env vars** (Render / Cloud Run):

```
MOCK_MODE=false
APP_PUBLIC_URL=https://YOUR-DOMAIN
META_APP_ID=...
META_APP_SECRET=...
META_VERIFY_TOKEN=socialauto-verify-token
META_GRAPH_VERSION=v25.0
```

Media for Instagram must be a **public HTTPS URL**. Set `APP_PUBLIC_URL` to
the same https domain the app is served from.

---

## Permissions requested

`pages_show_list`, `pages_read_engagement`, `pages_manage_posts`,
`pages_manage_engagement`, `pages_manage_metadata`, `instagram_basic`,
`instagram_content_publish`, `instagram_manage_comments`,
`instagram_manage_insights`, `business_management`

On the Facebook permission screen, tick **every Page** you want to post to.

---

## What works after connect

| | Instagram | Facebook Page |
|---|---|---|
| Photo / caption | Graph container → publish | `/{page-id}/photos` |
| Reel / video | `media_type=REELS` + poll | `/{page-id}/videos` |
| Text-only | not supported by IG | `/{page-id}/feed` |
| Comments + auto-reply | yes | yes |
| Insights | likes / comments / reach | likes / comments / impressions |
| Tokens | long-lived page token (does not expire until password change) | same |

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| Invalid OAuth redirect_uri | URI in Login settings must match exactly (https, no trailing slash) |
| App in Development | Add yourself as Admin/Tester |
| Connect shows no Instagram | IG must be Professional + linked to the Page you ticked |
| Webhook verify fails | Token must match `META_VERIFY_TOKEN`; app must be reachable on https |
| Instagram publish needs HTTPS | Set `APP_PUBLIC_URL` to your public https URL |
| Token expired after 1 hour | Re-connect once — SocialAuto now exchanges for a 60-day user token then a never-expiring Page token |
