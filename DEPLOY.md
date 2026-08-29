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
  --set-env-vars MOCK_MODE=false,CRON_SECRET=put-a-long-random-secret-here

# 3. Done — you get a free HTTPS URL instantly:
#    https://socialauto-xxxxx-el.a.run.app
```

> Add real platform tokens later with `--set-env-vars` or in Console → Service → Edit & deploy → Variables:
> `META_APP_ID`, `META_APP_SECRET`, `X_BEARER_TOKEN`, `LINKEDIN_ACCESS_TOKEN` (see `.env.example`).
>
> Free DB: create a Turso (https://turso.tech) or Neon (https://neon.tech) database and set
> `DATABASE_URL=sqlite+... / postgresql+...` env var. Until then SQLite works (note: Cloud Run
> filesystem is ephemeral — data resets on redeploy; use Turso/Neon for persistence).

### Option 2 — Render (simplest dashboard deploy)
1. https://render.com → New → **Web Service** → connect your GitHub repo
2. Build command: `pip install -r backend/requirements.txt`
3. Start command: `cd backend && uvicorn app.main:app --host 0.0.0.0 --port $PORT`
4. Add env vars (`MOCK_MODE`, `CRON_SECRET`, …) → Create
5. Free URL: `https://socialauto.onrender.com` (sleeps after inactivity on free plan)

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
