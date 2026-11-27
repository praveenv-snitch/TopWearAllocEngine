// Snitch TopWear Allocation Engine - serves the HTML that `python -m engine.build` publishes to Workers KV (key "index.html"),
// plus a small JSON API for saved allocations and store rules (same KV namespace, same password).
// Optional password: `npx wrangler secret put SITE_PASSWORD` (any username, that password).
// On-time refresh: the cron trigger in wrangler.toml starts the GitHub workflow (GitHub's own schedule often runs late).
// Needs `npx wrangler secret put GH_TOKEN` (fine-grained token, this repo only, "Actions: Read and write").
//
// KV keys
//   alloc:<id>  {meta, lines}  expires 35 days after saving; list metadata = meta (name, date, poc, stores, skus, units, by)
//   rule:<id>   {}             the rule itself lives in the key metadata (small), optional expiry
const ALLOC_TTL = 35 * 86400;
const MAX_ALLOC_BYTES = 2 * 1024 * 1024;
const RULE_TYPES = ["sku", "design", "meta", "colour", "sleeve", "band", "fit", "collar", "material", "less", "note"];
const ID_RE = /^[a-z0-9]{6,32}$/;

const json = (o, status = 200) => new Response(JSON.stringify(o), {
  status, headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" } });
const newId = () => Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
const str = (v, n) => String(v == null ? "" : v).slice(0, n);

function authorised(request, env) {
  if (!env.SITE_PASSWORD) return true;
  const auth = request.headers.get("Authorization") || "";
  let pass = "";
  if (auth.startsWith("Basic ")) {
    try { pass = atob(auth.slice(6)).split(":").slice(1).join(":"); } catch (e) { pass = ""; }
  }
  return pass === env.SITE_PASSWORD;
}

async function listAll(env, prefix) {
  const out = [];
  let cursor;
  do {
    const r = await env.TW.list({ prefix, cursor });
    for (const k of r.keys) out.push({ id: k.name.slice(prefix.length), meta: k.metadata || {}, exp: k.expiration || null });
    cursor = r.list_complete ? null : r.cursor;
  } while (cursor);
  return out;
}

async function readBody(request) {
  const len = +(request.headers.get("Content-Length") || 0);
  if (len > MAX_ALLOC_BYTES) throw new Error("too large");
  const txt = await request.text();
  if (txt.length > MAX_ALLOC_BYTES) throw new Error("too large");
  return JSON.parse(txt);
}

async function api(request, env, path) {
  const m = request.method;
  // ---- saved allocations
  if (path === "/api/allocs" && m === "GET") return json(await listAll(env, "alloc:"));
  if (path === "/api/allocs" && m === "POST") {
    let b;
    try { b = await readBody(request); } catch (e) { return json({ error: "body must be JSON under 2 MB" }, 400); }
    if (!b || !b.meta || !Array.isArray(b.lines) || !b.lines.length || b.lines.length > 50000) return json({ error: "meta and lines required" }, 400);
    const x = b.meta, id = newId();
    const meta = { name: str(x.name, 120), date: str(x.date, 10), poc: str(x.poc, 40), stores: +x.stores || 0, skus: +x.skus || 0,
      units: +x.units || 0, by: str(x.by, 40), src: str(x.src, 20), created: Date.now() };
    if (!meta.name || !/^\d{4}-\d{2}-\d{2}$/.test(meta.date)) return json({ error: "name and date (YYYY-MM-DD) required" }, 400);
    const csv = Array.isArray(b.csv) ? b.csv.filter(x => typeof x === "string") : [];        // the exact downloaded file, for re-download
    await env.TW.put("alloc:" + id, JSON.stringify({ meta, cfg: b.cfg || null, lines: b.lines, csv }), { expirationTtl: ALLOC_TTL, metadata: meta });
    return json({ id, meta, exp: Math.floor(Date.now() / 1000) + ALLOC_TTL });
  }
  let mm = path.match(/^\/api\/allocs\/([a-z0-9]+)$/);
  if (mm && ID_RE.test(mm[1])) {
    if (m === "GET") { const v = await env.TW.get("alloc:" + mm[1], { type: "json" }); return v ? json(v) : json({ error: "not found (expired?)" }, 404); }
    if (m === "DELETE") { await env.TW.delete("alloc:" + mm[1]); return json({ ok: true }); }
  }
  // ---- store rules (from merchandiser remarks)
  if (path === "/api/rules" && m === "GET") return json(await listAll(env, "rule:"));
  if (path === "/api/rules" && m === "POST") {
    let b;
    try { b = await readBody(request); } catch (e) { return json({ error: "body must be JSON" }, 400); }
    const bc = parseInt(b && b.bc, 10), type = str(b && b.type, 12);
    if (!(bc > 0) || !RULE_TYPES.includes(type)) return json({ error: "bc and a valid type required" }, 400);
    const rule = { bc, type, value: str(b.value, 80), sku: str(b.sku, 40), text: str(b.text, 300), by: str(b.by, 40),
      alloc: str(b.alloc, 32), store: str(b.store, 60), cat: str(b.cat, 12), created: Date.now() };
    const days = parseInt(b.days, 10), id = newId();
    const opts = { metadata: rule };
    if (days > 0) opts.expirationTtl = Math.min(days, 3650) * 86400;
    if (JSON.stringify(rule).length > 1000) return json({ error: "remark too long" }, 400);   // KV metadata limit 1024 bytes
    await env.TW.put("rule:" + id, "{}", opts);
    return json({ id, meta: rule, exp: opts.expirationTtl ? Math.floor(Date.now() / 1000) + opts.expirationTtl : null });
  }
  mm = path.match(/^\/api\/rules\/([a-z0-9]+)$/);
  if (mm && ID_RE.test(mm[1]) && m === "DELETE") { await env.TW.delete("rule:" + mm[1]); return json({ ok: true }); }
  return json({ error: "not found" }, 404);
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const isApi = url.pathname.startsWith("/api/");
    if (!isApi && url.pathname !== "/" && url.pathname !== "/index.html") {
      return new Response("Not found", { status: 404 });
    }
    if (!authorised(request, env)) {
      return new Response("Authentication required", {
        status: 401, headers: { "WWW-Authenticate": 'Basic realm="Snitch TopWear Allocation", charset="UTF-8"' },
      });
    }
    if (isApi) {
      try { return await api(request, env, url.pathname); }
      catch (e) { return json({ error: "server error: " + e.message }, 500); }
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
