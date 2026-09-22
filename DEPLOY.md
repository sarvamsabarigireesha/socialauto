# 🚀 Deploy + Free Domain — Step by Step (₹0)

Two parts: **(A)** deploy the app and get a free HTTPS URL instantly, **(B)** attach a free custom domain.

---

## A. Deploy the app (free hosting)

### Option 1 — Google Cloud Run (recommended: always-on, 2M requests/mo free)

```bash
# 1. Install gcloud CLI: https://cloud.google.com/sdk/docs/install
gcloud auth login
gcloud projects create socialauto-prod       # or use an existing project
gcloud config set project socialauto-prod

# 2. Deploy straight from the source folder (this repo root)
gcloud run deploy socialauto \
  --source . \
  --region asia-south1 \
  --allow-unauthenticated \
  --port 8000 \
  --set-env-vars MOCK_MODE=false,CRON_SECRET=put-a-long-random-secret-here,DATABASE_URL='postgresql://neondb_owner:PASSWORD@ep-xxxx.ap-southeast-1.aws.neon.tech/neondb?sslmode=require'

# 3. Done — you get a free HTTPS URL instantly:
#    https://socialauto-xxxxx-el.a.run.app
```

> Add real platform tokens later with `--set-env-vars` or in Console → Service → Edit & deploy → Variables:
> `META_APP_ID`, `META_APP_SECRET`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` (see `.env.example`).
>
> **Database — Neon Postgres (free, recommended):**
> 1. Sign up at https://neon.tech → create project (region: Mumbai/Singapore) → Connect → copy the
>    `postgresql://neondb_owner:...@ep-....aws.neon.tech/neondb?sslmode=require` string.
> 2. Set it as the `DATABASE_URL` env var — no code changes; tables auto-create on first boot.
>    (Cloud Run filesystem is ephemeral, so Postgres keeps data across redeploys. SQLite is local-demo only.)

### Option 2 — Render (simplest dashboard deploy)
1. https://render.com → New → **Web Service** → connect your GitHub repo
2. Build command: `pip install -r backend/requirements.txt`
3. Start command: `cd backend && uvicorn app.main:app --host 0.0.0.0 --port $PORT`
4. Environment variables — **all four matter**:
   | Key | Value | Why |
   |-----|-------|-----|
   | `MOCK_MODE` | `false` | otherwise every "publish" is simulated |
   | `DATABASE_URL` | Neon Postgres string | **Render's disk is wiped on every deploy**, so SQLite loses all users/posts/comments. Without this you get a blank app after each push. |
   | `APP_PUBLIC_URL` | `https://socialauto.onrender.com` | Instagram fetches your media from a public https URL; without this, media stays relative and IG publishing always fails |
   | `CRON_SECRET` | long random string | the app refuses cron calls with the dev default in live mode |
5. Health check path: `/api/health` (Settings → Health Checks). Render sends **HEAD**; this app answers HEAD on `/` and `/api/health` — before, a HEAD returned `405`, which made the service look unhealthy and trigger restarts.
6. Free URL: `https://socialauto.onrender.com` (sleeps after inactivity on free plan)

#### ⚠️ The free-plan trap that breaks Instagram posting
Render's filesystem is **ephemeral**: every deploy and every restart wipes
`backend/data`. That includes uploaded media — so a URL the composer used at
10:30 returns **404 at 10:35**, and the failure shows up in the logs as Meta's
crawler (IPs in `10.26.x` / `10.28.x`) requesting `/media/...`:

```
GET /media/u3/75bb14f21a47.mp4 404 Not Found
```

Instagram then rejects the post, usually with a vague media error. Three ways
out, cheapest first:

1. **Use external media URLs** — paste an `https://` image/video link (Drive,
   GitHub raw, Cloudinary free tier) into the composer instead of uploading.
2. **Attach a Render Disk** (paid) — mount it at `/var/data` and set
   `DATA_DIR=/var/data`. Media and a SQLite DB then survive redeploys.
3. **Host the media elsewhere** — e.g. Cloudinary/ImageKit free tier, and let
   the composer store that URL.

Since this release the app also tells you instead of failing silently: a missing
file returns a `404` whose body explains the cause, and publishing checks local
media **before** calling Meta, so you get *"the media file /media/... is missing
on this server … re-upload the file"* rather than an opaque Graph API error.

### Option 3 — Fly.io
```bash
fly launch --no-deploy        # generates fly.toml, set internal_port = 8000
fly secrets set CRON_SECRET=xxx MOCK_MODE=false
fly deploy                    # -> https://socialauto.fly.dev
```

**Instant free HTTPS URL after ANY of these — that's already your "free domain" for the portfolio.**
Examples: `socialauto-xxxxx.el.run.app`, `socialauto.onrender.com`, `socialauto.fly.dev`.

---

## B. Free custom domain (yourname.is-a.dev etc.)

### Option 1 — `is-a.dev` (best for developers/portfolio, free forever, ~1–3 day approval)
Gives `yourname.is-a.dev` (e.g. `socialauto.is-a.dev`).

1. Fork https://github.com/is-a-dev/register
2. In your fork, create file `domains/yourname.json` (use the subdomain you want):
```json
{
  "owner": {
    "username": "YOUR_GITHUB_USERNAME",
    "email": "you@example.com"
  },
  "description": "SocialAuto — social media automation",
  "records": {
    "CNAME": "ghs.googlehosted.com"
  }
}
```
   - Use `CNAME: ghs.googlehosted.com` for Cloud Run, or the target your host gives you
     (Render/Fly show it in their "Custom domain" screens).
3. Open a Pull Request to the register repo → their bot validates → merged in 1–3 days.
4. In your host's dashboard add the custom domain:
   - **Cloud Run:** Console → Cloud Run → your service → **Custom domains → Add mapping** →
     enter `yourname.is-a.dev` → it shows the CNAME value (`ghs.googlehosted.com`) — matches step 2.
   - **Render:** Service → Settings → Custom Domains → add `yourname.is-a.dev`.
   - **Fly:** `fly certs create yourname.is-a.dev`.
5. HTTPS certificate is issued automatically. Done: `https://yourname.is-a.dev` 🎉

### Option 2 — `eu.org` (free forever, any name like `yourname.eu.org`, approval can take days–weeks)
1. Register at https://nic.eu.org (account creation + domain request form)
2. When asked for nameservers, use **Cloudflare's free DNS**:
   - Create free Cloudflare account → Add site `yourname.eu.org` → they give 2 nameservers
   - Put those nameservers in the eu.org form
3. After approval, in Cloudflare DNS add:
   `CNAME  @  →  ghs.googlehosted.com` (Cloud Run) or your host's target
4. Add the domain in Cloud Run / Render custom-domain screen (same as Option 1, step 4).

### Option 3 — Free `.me` / `.tech` for 1 year (students)
GitHub Student Developer Pack (https://education.github.com/pack) → Namecheap `.me` free 1 year
or Name.com `.tech` free. Then point DNS to Cloudflare/host as above.

### Avoid
- **Freenom (.tk/.ml/.ga/.cf/.gq)** — registration is effectively dead, domains get taken back; don't use for a portfolio.
- **DuckDNS** — only A/AAAA records, no CNAME → doesn't work cleanly with Cloud Run/Render custom domains.

---

## C. Turn on the scheduler after deploy

1. GitHub repo → **Settings → Secrets and variables → Actions → New repository secret**:
   | Secret | Value |
   |---|---|
   | `APP_URL` | `https://yourname.is-a.dev` (or the run.app/onrender.com URL, no trailing slash) |
   | `CRON_SECRET` | the same secret you set on the server |
2. **Actions** tab → open `socialauto-cron` → **Enable workflow**.
3. It fires every 15 minutes → publishes due posts, auto-replies to comments, refreshes analytics.
   (Alternative/backup: deploy `cloudflare/worker.js` with `wrangler deploy` and set the same two
   secrets — Cloudflare's cron does the same thing, 100k req/day free.)

## Final checklist
- [ ] App deployed → free HTTPS URL works
- [ ] (optional) Custom free domain mapped + HTTPS
- [ ] GitHub secrets `APP_URL` + `CRON_SECRET` set
- [ ] Actions workflow enabled; first manual run shows ✅
- [ ] `MOCK_MODE=false` + platform tokens set when going live for real
