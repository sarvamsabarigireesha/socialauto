/**
 * SocialAuto cron worker — Cloudflare Workers free tier (100k requests/day).
 * Deploys with:  wrangler deploy
 *
 * Set Worker secrets/vars:
 *   APP_URL      -> your FastAPI app base URL
 *   CRON_SECRET  -> same secret as the app
 *
 * wrangler.toml:
 *   name = "socialauto-cron"
 *   main = "worker.js"
 *   compatibility_date = "2026-01-01"
 *   [triggers]
 *   crons = ["*/15 * * * *"]
 */
export default {
  async scheduled(event, env, ctx) {
    ctx.waitUntil(tick(env));
  },
  // Also allow manual HTTP trigger:  curl https://<worker>.workers.dev/
  async fetch(request, env, ctx) {
    const result = await tick(env);
    return new Response(JSON.stringify(result), {
      headers: { "content-type": "application/json" },
    });
  },
};

async function tick(env) {
  const res = await fetch(`${env.APP_URL}/api/cron/tick`, {
    method: "POST",
    headers: {
      "X-Cron-Secret": env.CRON_SECRET,
      "Content-Type": "application/json",
    },
  });
  return { status: res.status, body: await res.json() };
}
