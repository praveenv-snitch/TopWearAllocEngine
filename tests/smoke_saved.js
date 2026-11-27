// Saved allocations, performance analysis and store rules, end to end: the page talks to the real Worker code
// (worker/src/index.js) through an in-memory KV.
//   NODE_PATH=~/node_modules node --max-old-space-size=2500 tests/smoke_saved.js index.html
// Build index.html with TW_ALLOCS_FILE (a saved allocation dated in the past) to also check the analysis numbers.
const { JSDOM } = require('jsdom');
const fs = require('fs'), path = require('path');
const fails = [], errs = [];
const ok = (c, m) => { if (!c) { fails.push(m); console.log('  FAIL', m); } };
const tick = (ms = 0) => new Promise(r => setTimeout(r, ms));

(async () => {
  const worker = (await import(path.resolve(__dirname, '../worker/src/index.js'))).default;
  const store = new Map();
  const KV = {
    async get(k, o) { const v = store.get(k); if (!v) return null; return o && o.type === 'json' ? JSON.parse(v.v) : v.v; },
    async put(k, v, o = {}) { store.set(k, { v, meta: o.metadata, exp: o.expirationTtl ? Math.floor(Date.now() / 1000) + o.expirationTtl : null }); },
    async delete(k) { store.delete(k); },
    async list({ prefix }) { return { keys: [...store].filter(([k]) => k.startsWith(prefix)).map(([k, v]) => ({ name: k, metadata: v.meta, expiration: v.exp })), list_complete: true }; },
  };
  const env = { TW: KV };
  const html = fs.readFileSync(process.argv[2] || 'index.html', 'utf8');
  const dom = new JSDOM(html, { runScripts: 'dangerously', pretendToBeVisual: true, url: 'https://topwear.test/',
    beforeParse(w) {
      w.fetch = async (u, o = {}) => { const r = await worker.fetch(new Request(new URL(u, 'https://topwear.test/'), { method: o.method || 'GET', headers: o.headers, body: o.body }), env);
        const t = await r.text(); return { ok: r.ok, status: r.status, json: async () => JSON.parse(t) }; };
      w.confirm = () => true; w.alert = m => errs.push('alert: ' + m);
      w.addEventListener('error', e => errs.push(e.message));
    } });
  const w = dom.window, d = w.document, $ = id => d.getElementById(id), ev = s => w.eval(s);
  await tick(50);

  // ---- 1. save from "Where to allocate": name format, frozen lines, identical re-download
  const kx = ev(`(()=>{for(let k=0;k<K.length;k++)if(sum(K[k][20])+sum(K[k][21])>300)return k;return 0})()`);
  ev(`BASKET=[];LS.set('tw_basket',[]);showSku(K[${kx}][0])`);
  $('pSave').click();
  const name = $('svName').value;
  console.log('  suggested name:', name);
  ok(/^\d\d-\d\d-\d\d_[A-Z0-9-]+_[0-9+-]+_\d+$/.test(name), 'name format DD-MM-YY_POC_codes_qty');
  const units = +name.split('_').pop();
  $('svBy').value = 'QC';
  $('svSave').click(); await tick(30);
  ok(/Saved as/.test($('svMsg').textContent), 'save message: ' + $('svMsg').textContent);
  const keys = [...store.keys()].filter(k => k.startsWith('alloc:'));
  ok(keys.length === 1, 'one alloc in KV');
  const saved = JSON.parse(store.get(keys[0]).v), sid = keys[0].slice(6);
  ok(saved.lines.length > 0 && Math.abs(saved.lines.reduce((s, l) => s + l.units, 0) - units) === 0, 'saved units = name qty');
  ok(store.get(keys[0]).exp - Date.now() / 1000 > 34.9 * 86400, '35-day expiry set');
  let dl = null; w.downloadCsv = (rows, file) => { dl = { rows, file }; };
  ev(`closeSave();tabGo('saved')`); await tick(30);
  ok(d.querySelectorAll('#savedList tbody tr').length === 1, 'listed in Saved allocations');
  $('savedQ').value = 'zzz-no-match'; $('savedQ').dispatchEvent(new w.Event('input'));
  ok(d.querySelectorAll('#savedList tbody tr').length === 0, 'search filters');
  $('savedQ').value = name.slice(0, 8); $('savedQ').dispatchEvent(new w.Event('input'));
  ok(d.querySelectorAll('#savedList tbody tr').length === 1, 'search by name');
  d.querySelector('#savedList tbody tr button').click(); await tick(20);
  const fresh = ev(`JSON.stringify(allocCsv(allocate([${kx}],[...Array(NS).keys()],PMODE,cfgNow(),weights(),{pin:{}})))`);
  ok(dl && JSON.stringify(dl.rows) === JSON.stringify(saved.csv) && dl.file === name + '.csv', 're-download = saved file');
  ok(JSON.stringify(saved.csv) === fresh, 'saved file = what Download gave at save time');
  console.log('  saved', saved.lines.length, 'lines,', units, 'units; re-download identical');

  // ---- 2. analysis of a past allocation (from TW_ALLOCS_FILE) checked against D.perf
  const pid = ev(`Object.keys((D.perf||{}).a||{})[0]||''`);
  if (pid) {
    const rows = ev(`JSON.stringify(D.perf.a['${pid}'])`), pr = JSON.parse(rows);
    const pairs = [...new Set(pr.map(r => r[0] + '|' + r[1]))].map(x => x.split('|'));
    const lines = pairs.map(([bc, sku]) => ({ bc: +bc, sku, store: 'BC ' + bc, cat: 'SHIRTS', type: 'REPLEN', pack: 'LOOSE', units: 6, ros: 0.2, ev: 3, have: 2, design: 'Solid', colour: 'Navy', sleeve: 'Full' }));
    const meta = { name: 'QC past', date: ev(`(()=>{const a=D.perf.asOf;const t=new Date(Date.parse(a)-13*86400000);return t.toISOString().slice(0,10)})()`), stores: 1, skus: 1, units: lines.length * 6 };
    store.set('alloc:' + pid, { v: JSON.stringify({ meta, lines, csv: ['H'] }), meta, exp: null });
    ev(`loadSaved()`); await tick(30);
    ev(`openSaved('${pid}')`); await tick(30);
    const sold = pr.reduce((s, r) => s + r[3], 0), shown = d.querySelector('#savedDetail .kpi div:nth-child(2) b').textContent.replace(/,/g, '');
    console.log('  analysis', pid, '| sold (D.perf)', sold, '| shown', shown, '| days', ev(`perfCalc(CACHE.get('${pid}'),'${pid}').days`));
    ok(+shown === sold, 'analysis sold = perf rows');
    ok(ev(`perfCalc(CACHE.get('${pid}'),'${pid}').days`) === 14, 'same-period days (alloc date..yesterday)');
    const proj = ev(`sum(perfCalc(CACHE.get('${pid}'),'${pid}').lines.map(l=>l.proj))`);
    ok(Math.abs(proj - lines.length * Math.min(0.2 * 14, 8)) < 1e-6, 'projection = ROS x days, capped at stock');
    ok(!!d.querySelector('#savedDetail svg polyline') && d.querySelectorAll('#savedDetail .bar').length > 0, 'charts drawn');
    ok(d.querySelectorAll('#savedLines tbody tr').length === lines.length, 'lines table');
  } else console.log('  (no D.perf in this build: analysis numbers not checked)');

  // ---- 3. remark -> rule -> engine follows it
  ev(`openSaved('${sid}')`); await tick(30);
  const li = ev(`CACHE.get('${sid}').lines.findIndex(l=>l.sleeve&&l.sleeve!=='Unknown')`);
  ok(li >= 0, 'a line with a sleeve');
  const L = JSON.parse(ev(`JSON.stringify(CACHE.get('${sid}').lines[${li}])`));
  ev(`remarkForm('${sid}',${li})`);
  const tx = $('rmText'); tx.value = L.sleeve.toLowerCase() + " sleeve doesn't work here"; tx.dispatchEvent(new w.Event('input'));
  ok($('rmType').value === 'sleeve', 'free text suggests the sleeve rule (got ' + $('rmType').value + ')');
  $('rmSave').click(); await tick(30);
  const rk = [...store.keys()].filter(k => k.startsWith('rule:'));
  ok(rk.length === 1 && store.get(rk[0]).meta.type === 'sleeve' && store.get(rk[0]).meta.value === L.sleeve && store.get(rk[0]).exp, 'rule stored with expiry');
  ok(d.querySelectorAll('#savedLines .chip.rule').length >= 1 && d.querySelectorAll('#rulesBox tbody tr').length === 1, 'rule shown on the line and in Store rules');
  const si = ev(`S.findIndex(s=>s[0]===${L.bc})`);
  const chk = JSON.parse(ev(`(()=>{const ks=[...Array(K.length).keys()].filter(k=>CATS[K[k][1]]==='${L.cat}'&&W[K[k][47]]==='${L.sleeve}'&&poolTot(k)>0).slice(0,60);
    const out=allocate(ks,[${si}],'auto',cfgNow(),weights(),{});return JSON.stringify({lines:out.length,skipped:out.ruleSkips.length})})()`));
  console.log('  after rule "' + L.sleeve + ' sleeve" at BC', L.bc, ':', JSON.stringify(chk));
  ok(chk.lines === 0 && chk.skipped > 0, 'engine skips the rule\'s lines at that store');
  ok(ev(`allocate([${kx}],[...Array(NS).keys()],PMODE,cfgNow(),weights(),{pin:{}}).every(r=>!(r.si===${si}&&W[K[r.k][47]]==='${L.sleeve}'&&CATS[K[r.k][1]]==='${L.cat}'))`), 'no line for the store breaks the rule');
  // stock still balances with rules on (no over-allocation, codes unique)
  const bal = ev(`(()=>{const ks=Object.keys(POOL).map(Number).slice(0,200),sts=[...Array(NS).keys()],{m}=budgets(sts),out=allocate(ks,sts,'fresh',cfgNow(),weights(),{fresh:true,budget:m});
    const u=new Map(),codes=new Set();let bad=0;for(const r of out){if(r.packType==='PREPACK'){for(const c of r.codes){if(codes.has(c))bad++;codes.add(c)}const kk=r.k+'p'+r.z;u.set(kk,(u.get(kk)||0)+r.packs)}else r.split.forEach((x,i)=>{const kk=r.k+'|'+r.z+'|'+i;u.set(kk,(u.get(kk)||0)+x)})}
    for(const [kk,v] of u){const pl=freshPool(+kk.split(/[p|]/)[0]);if(kk.includes('p')){if(v>pl.packs[+kk.split('p')[1]])bad++}else{const [k,z,i]=kk.split('|').map(Number);if(v>pl.loose[z][i])bad++}}
    return bad})()`);
  ok(bal === 0, 'no over-allocation with rules on');
  // sku rule + less rule
  const k2 = ev(`(()=>{const o=allocate([...Array(K.length).keys()].filter(k=>poolTot(k)>50).slice(0,80),[${si}],'auto',cfgNow(),weights(),{});return o.length?o[0].k:-1})()`);
  if (k2 >= 0) {
    ev(`RULES.push({id:'t1',meta:{bc:${L.bc},type:'sku',sku:K[${k2}][0]}});indexRules()`);
    ok(ev(`allocate([${k2}],[${si}],'auto',cfgNow(),weights(),{}).length`) === 0, "don't-send-SKU rule");
    ev(`RULES=RULES.filter(r=>r.id!=='t1');indexRules()`);
    ok(ev(`allocate([${k2}],[${si}],'auto',cfgNow(),weights(),{}).length`) > 0, 'line back once the rule is removed');
  }
  const kr = ev(`(()=>{for(let k=0;k<K.length;k++){if(poolTot(k)<30)continue;for(let s=0;s<NS;s++){if(!STOCK[s*K.length+k])continue;const o=allocate([k],[s],'replen',cfgNow(),weights(),{});if(o.length&&o[0].packType==='LOOSE'&&o[0].units>=4)return [k,s,o[0].units]}}return null})()`);
  if (kr) {
    ev(`RULES.push({id:'t2',meta:{bc:S[${kr[1]}][0],type:'less',sku:K[${kr[0]}][0]}});indexRules()`);
    const half = ev(`(()=>{const o=allocate([${kr[0]}],[${kr[1]}],'replen',cfgNow(),weights(),{});return o.length?o[0].units:0})()`);
    console.log('  send-less replen units', kr[2], '->', half);
    ok(half < kr[2], 'send-less reduces replen quantity');
    ev(`RULES=RULES.filter(r=>r.id!=='t2');indexRules()`);
  }
  // remove the stored rule through the UI
  d.querySelector('#rulesBox tbody tr button').click(); await tick(30);
  ok([...store.keys()].filter(k => k.startsWith('rule:')).length === 0 && ev('RULES.length') === 0, 'rule removed');
  // store health chip
  ev(`RULES.push({id:'t3',meta:{bc:${L.bc},type:'colour',value:'Navy',cat:'SHIRTS'}});indexRules()`);
  ok(/1 store rule/.test(ev(`storeRuleChip(${si})`)), 'store rule chip');
  // delete saved allocation
  ev(`delSaved('${sid}')`); await tick(30);
  ok(![...store.keys()].includes('alloc:' + sid), 'saved allocation deleted');
  // worker rejects bad input
  const bad = await worker.fetch(new Request('https://t/api/rules', { method: 'POST', body: JSON.stringify({ bc: 'x', type: 'drop' }) }), env);
  ok(bad.status === 400, 'worker rejects a bad rule');

  console.log('\nerrors:', errs.length, errs.slice(0, 3), '| failed checks:', fails.length ? fails : 'none');
  process.exit(errs.length || fails.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
