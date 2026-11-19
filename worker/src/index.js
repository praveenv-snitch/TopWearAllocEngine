// Snitch TopWear Allocation Engine - serves the HTML that `python -m engine.build` publishes to Workers KV (key "index.html").
// Optional password: `npx wrangler secret put SITE_PASSWORD` (any username, that password).
// On-time refresh: the cron trigger in wrangler.toml starts the GitHub workflow (GitHub's own schedule often runs late).
// Needs `npx wrangler secret put GH_TOKEN` (fine-grained token, this repo only, "Actions: Read and write").
export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname !== "/" && url.pathname !== "/index.html") {
      return new Response("Not found", { status: 404 });
    }
    if (env.SITE_PASSWORD) {
      const auth = request.headers.get("Authorization") || "";
      let pass = "";
      if (auth.startsWith("Basic ")) {
        try { pass = atob(auth.slice(6)).split(":").slice(1).join(":"); } catch (e) { pass = ""; }
      }
      if (pass !== env.SITE_PASSWORD) {
        return new Response("Authentication required", {
          status: 401, headers: { "WWW-Authenticate": 'Basic realm="Snitch TopWear Allocation", charset="UTF-8"' },
        });
      }
    }
    const html = await env.TW.get("index.html", { type: "stream" });
    if (!html) {
      return new Response("Not published yet - run the GitHub Action (TopWear refresh).",
        { status: 503, headers: { "Content-Type": "text/plain; charset=utf-8" } });
    }
    return new Response(html, {
      headers: { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store", "X-Robots-Tag": "noindex, nofollow" },
    });
  },

  async scheduled(event, env, ctx) {
    if (!env.GH_TOKEN || !env.GH_REPO) {
      console.log("refresh trigger skipped: GH_TOKEN secret or GH_REPO var not set");
      return;
    }
    const res = await fetch(`https://api.github.com/repos/${env.GH_REPO}/actions/workflows/refresh.yml/dispatches`, {
      method: "POST",
      headers: {
        "Authorization": "Bearer " + env.GH_TOKEN, "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "topwearalloc-worker",
      },
      body: JSON.stringify({ ref: env.GH_REF || "main", inputs: { refresh_only: "true" } }),
    });
    if (res.status !== 204) throw new Error(`workflow dispatch failed (${res.status}): ${await res.text()}`);
    console.log("refresh dispatched for cron", event.cron);
  },
};
