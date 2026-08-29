# SocialAuto update guide

## What was changed

### Version
- Current local code version: `1.3.0`

### UI / UX
- Mobile top header + hamburger sidebar drawer
- Search + platform filter in Queue / Posts
- Search + unresolved-only filter in Community
- Password show/hide toggles
- Enter-key submit support in auth flows
- Reset-password flow improved, including token auto-open from URL query params
- Home dashboard polished with quick actions + status cards
- Sticky topbar and better card hover polish

### Backend
- Duplicate connected accounts are blocked with `409`
- `post_type` is validated in create/update/bulk flows

## Files changed
- `frontend/index.html`
- `backend/app/routers/posts.py`
- `backend/app/routers/accounts.py`
- `backend/app/main.py`

## Git commands
```bash
cd socialauto
git add frontend/index.html backend/app/routers/posts.py backend/app/routers/accounts.py backend/app/main.py ARENA_UPDATE_GUIDE.md
git commit -m "Improve mobile UI, auth UX, home dashboard, queue/community filters, and backend validation"
git push origin main
```

If your default branch is not `main`, replace it with your branch name.

## Render deploy steps
1. Open Render dashboard
2. Select the `socialauto` web service
3. If auto-deploy is enabled, pushing to GitHub will trigger deploy automatically
4. Otherwise click **Manual Deploy** -> **Deploy latest commit**

## Recommended environment variables
Set these in Render if not already present:
- `MOCK_MODE=false`
- `APP_PUBLIC_URL=https://socialauto-k5ou.onrender.com`
- `JWT_SECRET=your-long-random-secret`
- `CRON_SECRET=your-long-random-secret`
- `DATABASE_URL=...` (if using Postgres/Neon/Turso adapter)

Optional integrations:
- `META_APP_ID`
- `META_APP_SECRET`
- `GOOGLE_CLIENT_ID`
- `GOOGLE_CLIENT_SECRET`
- `GEMINI_API_KEY`
- `META_VERIFY_TOKEN`

## Verify after deploy
Check:
```bash
curl https://socialauto-k5ou.onrender.com/api/health
```
Expected:
```json
{"ok":true,"mock_mode":false,"version":"1.3.0"}
```

Then test manually:
- Login / signup
- Forgot password flow
- Queue search + platform filter
- Community search + unresolved-only filter
- Mobile sidebar on a small screen
- Connect-account duplicate protection

## If deploy does not reflect changes
- Ensure the latest GitHub commit actually contains the changed files
- Confirm Render service points to the same repo/branch
- Check Render build logs for startup errors
- Re-run health check after deploy finishes
