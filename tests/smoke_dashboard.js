// Headless check of the dashboard: loads the built page, exercises all tabs, and asserts the allocation rules.
//   node tests/smoke_dashboard.js index.html [SKU]
const {JSDOM, VirtualConsole} = require('jsdom');
const fs = require('fs');
const html = fs.readFileSync(process.argv[2], 'utf8');
const vc = new VirtualConsole(); const errs = [];
vc.on('jsdomError', e => errs.push(e.message)); vc.on('error', e => errs.push(String(e)));
const t0 = Date.now();
const dom = new JSDOM(html, {runScripts: 'dangerously', virtualConsole: vc, pretendToBeVisual: true, url: 'https://x.test/',
  beforeParse(w) { w.URL.createObjectURL = () => 'blob:x'; w.URL.revokeObjectURL = () => {}; w.HTMLElement.prototype.scrollIntoView = () => {}; }});
const w = dom.window, d = w.document, $ = id => d.getElementById(id), ev = s => w.eval(s);
const txt = el => el ? el.textContent.replace(/\s+/g, ' ').trim() : '(missing)';
const fails = [], ok = (c, m) => { if (!c) fails.push(m); };
console.log('load ms', Date.now() - t0, '| load errors', errs.length);

// --- exclusions
ok(ev("K.every(k=>!k[0].startsWith('MP'))"), 'MP SKU present');
ok(ev("S.every(s=>s[9]>0 && s[6] && s[6]!=='UNMAPPED')"), 'store without base stock / cluster present');

// --- search, recent, back, match modes
const a = process.argv[3] || ev("K.find(k=>k[32]>=0&&k[18]+k[19]>200&&!k[42])[0]");
const b = ev(`(()=>{const k=idx['${a}'];return neighbours(k,'def')[0]?K[neighbours(k,'def')[0].k][0]:null})()`);
ev(`showSku('${a}')`);
console.log('\n[TAB1]', a, '|', txt(d.querySelector('#simOut .topcard h2')), '|', txt(d.querySelector('#simOut .kpi')).slice(0, 260));
for (const m of ['def', 'vis', 'meta']) {
  const inp = d.querySelector(`[data-r="match"] input[value="${m}"]`); inp.checked = true; inp.dispatchEvent(new w.Event('change'));
  console.log(`  match=${m}: ${d.querySelectorAll('#simGrid .sc').length} cards | first: ${txt(d.querySelector('#simGrid .sc .code'))}`);
}
ok(d.querySelectorAll('#simGrid .sc').length > 0, 'no similar cards');
if (b) { ev(`showSku('${b}')`); ok($('skuBack').textContent.includes(a), 'back button not pointing to previous SKU'); $('skuBack').click(); ok(ev('K[CUR][0]') === a, 'back did not return'); }
console.log('  recent:', txt($('recent')), '| explainer:', !!d.querySelector('details.ex'));

// --- basket: single SKU, then add a second, then remove
const rows = () => [...d.querySelectorAll('#pTbl tbody tr')].length;
console.log('  where-to-allocate (single):', txt($('pSum')).slice(0, 200), '| lines', rows());
$('addAlloc').click();
const navy = ev(`(()=>{const c=W[K[idx['${a}']][10]];return (K.find(k=>k[0]!=='${a}'&&W[k[10]]===c&&k[1]===K[idx['${a}']][1]&&k[32]>=0&&sum(k[20])+sum(k[21])>150)||[])[0]})()`);
if (navy) { ev(`showSku('${navy}')`); $('addAlloc').click(); }
console.log('  basket:', ev('JSON.stringify(BASKET)'), '|', txt($('pSum')).slice(0, 260), '| lines', rows());
ok(ev('BASKET.length') === (navy ? 2 : 1), 'basket size wrong');
const before = rows(); if (navy) { ev(`basketToggle('${navy}')`); console.log('  after removing', navy, '-> lines', rows(), '(was', before + ')'); }

// --- placement rules over a large sample (auto = fresh + replen), the same allocator as "Where to allocate"
const RULES = `(out,fresh)=>{const fs=D.packs.fresh_set,bad=[];let fl=0,fp=0,rl=0,rp=0;const seen=new Set();
 for(const r of out){const a=K[r.k],pl=fresh?freshPool(r.k):placementPool(r.k);
  if(r.packType==='PREPACK'){ if(r.units!==r.packs*r.depth)bad.push('prepack units '+a[0]);
   if(r.type==='FRESH'&&r.packs!==2)bad.push('fresh prepacks != 2 '+a[0]); if(r.packs<1||r.packs>2)bad.push('replen packs '+a[0]);
   if(r.codes.length!==r.packs)bad.push('codes != packs '+a[0]);
   for(const c of r.codes){if(!c.includes('-'+a[0]+'-')||!c.startsWith('PP'+r.depth+'-'))bad.push('code not this SKU / depth '+c);
    if(!pl.codes[r.z].includes(c))bad.push('code not on hand in zone '+c)}
   r.type==='FRESH'?fp++:rp++; }
  else if(r.type==='FRESH'){ const set=PLUS_RE.test(a[0])?D.packs.fresh_set_plus:fs; if(r.split.some((v,i)=>v>set[i]))bad.push('fresh>set '+a[0]);
   if(!PLUS_RE.test(a[0])&&[1,2,3,4].some(i=>r.split[i]<set[i]))bad.push('fresh set missing core size '+a[0]); fl++; }
  else { if(r.split.some(v=>v>6))bad.push('replen > 6 a size '+a[0]); rl++; }
  if(!r.ok)bad.push('fulfilment flag '+a[0]);
  if(r.type==='FRESH'&&STOCK[r.si*K.length+r.k])bad.push('fresh to carrying store '+a[0]);
  if(r.type==='REPLEN'&&!STOCK[r.si*K.length+r.k])bad.push('replen to non-carrying store '+a[0]);}
 const use=new Map();for(const r of out){const u=use.get(r.k)||{l:[Array(10).fill(0),Array(10).fill(0)],p:[0,0],s:[0,0]};
  if(r.packType==='PREPACK'){u.p[r.z]+=r.packs;for(const c of r.codes){if(seen.has(c))bad.push('code used twice '+c);seen.add(c)}}
  else{r.split.forEach((v,i)=>u.l[r.z][i]+=v);if(r.type==='FRESH')u.s[r.z]++}use.set(r.k,u)}
 for(const [k,u] of use){const pl=fresh?freshPool(k):placementPool(k);for(const z of [0,1]){if(u.p[z]>pl.packs[z])bad.push('packs over '+K[k][0]);
  if(fresh&&u.s[z]>pl.fso[z])bad.push('full size options over '+K[k][0]);
  u.l[z].forEach((v,i)=>{if(v>pl.loose[z][i])bad.push('loose over '+K[k][0]+' '+SZ[i])})}}
 return {fresh_loose:fl,fresh_prepack:fp,replen_loose:rl,replen_prepack:rp,lines:out.length,violations:bad.slice(0,5),nViol:bad.length}}`;
let t = Date.now();
const pchk = JSON.parse(ev(`(()=>{const ks=[];for(let k=0;k<K.length&&ks.length<400;k++){const a=K[k];if(a[32]>=0&&poolUnits(placementPool(k),0)+poolUnits(placementPool(k),1)>40)ks.push(k)}
 const sts=[...Array(NS).keys()],out=allocate(ks,sts,'auto',cfgNow(),weights());return JSON.stringify((${RULES})(out,false))})()`));
console.log('  placement rule check (400 SKUs x all stores):', JSON.stringify(pchk), Date.now() - t, 'ms');
ok(pchk.nViol === 0, 'placement rule violations'); ok(pchk.fresh_prepack + pchk.replen_prepack > 0, 'no prepack lines in placement sample');

// --- TAB 2: filters, single-store detail, meta toggle, mini headers, price filter, reset
tabsel = s => { const e = $(s); return e; };
console.log('\n[TAB2] health rows', d.querySelectorAll('#healthTbl tbody tr').length, '| detail shown:', !!$('storeDetail').innerHTML);
ok($('storeDetail').innerHTML === '', 'store detail shown without a single store');
d.querySelector('#healthTbl tbody tr.click').click();
ok(d.querySelectorAll('#storeDetail .kpi').length >= 2, 'store detail not opened by row click');
ok(d.querySelectorAll('#storeDetail table.mini2 thead th').length >= 5, 'mini tables have no headers');
const mOne = txt(d.querySelector('#storeDetail .bar .d'));
const sb = d.querySelector('[data-r="mbench"] input[value="sales"]'); sb.checked = true; sb.dispatchEvent(new w.Event('change'));
console.log('  meta toggle ideal -> sales, first deviation:', mOne, '->', txt(d.querySelector('#storeDetail .bar .d')), '| deviation details collapsed:', !d.querySelector('#storeDetail details').open);
const dc = d.querySelector('[data-r="dcat"] input[value="1"]'); dc.checked = true; dc.dispatchEvent(new w.Event('change'));
ok(txt(d.querySelector('#storeDetail')).includes('T-SHIRTS'), 'category toggle in detail');
$('sdClose').click(); ok($('storeDetail').innerHTML === '', 'detail did not vanish after close');
const stockCol = () => [...d.querySelectorAll('#healthTbl tbody tr')].map(r => r.cells[7].textContent).join(',');
const before2 = stockCol(); $('fBand').value = D_bands1 = ev('D.bands[1]'); $('fBand').dispatchEvent(new w.Event('change'));
ok(stockCol() !== before2, 'price filter does not change health'); console.log('  price filter', D_bands1, 'changes health:', stockCol() !== before2, '|', txt($('fNote')).slice(0, 90));
$('fReset').click(); ok(stockCol() === before2 && $('fBand').value === '', 'reset filters');

// --- TAB 2 fresh run: auto over all stores
t = Date.now(); $('aRun').click();
console.log('  fresh auto run', Date.now() - t, 'ms |', txt($('allocSum')).slice(0, 330));
const fchk = JSON.parse(ev(`JSON.stringify((${RULES})(LAST,true))`));
console.log('  fresh rule check:', JSON.stringify(fchk)); ok(fchk.nViol === 0, 'fresh run rule violations'); ok(fchk.replen_loose + fchk.replen_prepack === 0, 'replen in fresh run');
const bchk = JSON.parse(ev(`(()=>{const used={},bad=[];for(const r of LAST){const key=r.si*2+K[r.k][1];used[key]=(used[key]||0)+r.units}
 let full=0;for(const [si,b] of LASTPER){for(const c of [0,1])if((used[si*2+c]||0)>b.cats[c])bad.push('over budget '+S[si][1]+' '+c);
  const sf=storeFill(si);if(sf&&sf.ist>=D.fresh.fill_budget){full++;if((used[si*2]||0)+(used[si*2+1]||0)>0)bad.push('store >=110% got units '+S[si][1])}
  if(b.total&&sum(b.cats)>b.total)bad.push('split > total '+S[si][1])}
 const ex=LASTPER.find(([si,b])=>b.total>0);let eg='';if(ex){const [si,b]=ex,s=S[si];eg=s[1]+': base '+s[12]+' x 1.1 - net '+s[15]+' = '+b.total+' (expect '+Math.max(0,Math.floor(1.1*s[12]-s[15]))+') -> S '+b.cats[0]+' / T '+b.cats[1];
  if(b.total!==Math.max(0,Math.floor(1.1*s[12]-s[15])))bad.push('budget formula')}
 return JSON.stringify({storesAtOrAbove110:full,example:eg,violations:bad.slice(0,5),nViol:bad.length})})()`));
console.log('  budget check:', JSON.stringify(bchk)); ok(bchk.nViol === 0, 'budget violations');
ok(d.querySelectorAll('#allocTbl th[title]').length > 10, 'column tooltips missing');
$('aCsv').click();
// manual: one store, Shirts only, 60 units
ev(`R.scope='store';R.store=String(LASTPER.find(x=>x[1].total>0)?.[0]??0);R.units='manual';R.manual=60;R.cat='0';runUI()`); $('aRun').click();
const man = JSON.parse(ev(`JSON.stringify({units:sum(LAST.map(r=>r.units)),stores:new Set(LAST.map(r=>r.si)).size,cats:[...new Set(LAST.map(r=>K[r.k][1]))]})`));
console.log('  manual one store / Shirts / 60u:', JSON.stringify(man)); ok(man.units <= 60 && man.stores <= 1 && man.cats.every(c => c === 0), 'manual run limits');
ev(`R.scope='cluster';R.clusters=new Set([S[0][6]]);R.units='auto';R.cat='both';runUI()`); $('aRun').click();
const cl = JSON.parse(ev(`JSON.stringify({clusters:[...new Set(LAST.map(r=>S[r.si][6]))],units:sum(LAST.map(r=>r.units))})`));
console.log('  cluster run', ev('S[0][6]'), JSON.stringify(cl)); ok(cl.clusters.every(c => c === ev('S[0][6]')), 'cluster run left the cluster');

// --- TAB 3
const nh = txt($('nudgeOut'));
console.log('\n[TAB3]', txt(d.querySelector('#nudgeOut h2')), '|', txt(d.querySelector('#nudgeOut .legend')).slice(0, 120));
ok(!/\bACT\b/.test(nh), 'ACT label still shown');
const nrows = () => d.querySelectorAll('#nudgeOut .card:first-child tbody tr').length;
const nAll = nrows(); const nc = d.querySelector('[data-r="ncat"] input[value="1"]'); nc.checked = true; nc.dispatchEvent(new w.Event('change'));
console.log('  inwards all / T-shirts:', nAll, '/', nrows());
const ac = $('aClus'); ac.value = ac.options[1].value; ac.dispatchEvent(new w.Event('change'));
console.log('  alerts after cluster filter:', txt(d.querySelector('#alertCard h2')), '| store options', $('aStore').options.length - 1);
ok([...$('aStore').options].slice(1).every(o => ev(`S[${o.value}][6]`) === ac.value), 'alert store list not cascading');
d.querySelector('#alertCard tbody tr.click').click();
ok(d.querySelectorAll('#storeDetail .kpi').length >= 2 && ev('F.stores.size') === 1, 'alert click did not open store health');
console.log('  alert click -> store detail:', txt(d.querySelector('#storeDetail h2')).slice(0, 60));
console.log('\nerrors:', errs.length, errs.slice(0, 3), '| failed checks:', fails.length ? fails : 'none');
process.exit(errs.length || fails.length ? 1 : 0);
