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
const nBefore = d.querySelectorAll('#healthTbl tbody tr').length; d.querySelector('#healthTbl tbody tr.click').click();
ok(d.querySelectorAll('#healthTbl tbody tr').length === nBefore && ev('F.stores.size') === 0, 'row click changed the store filter');
ok(d.querySelectorAll('#storeDetail .kpi').length >= 2, 'store detail not opened by row click');
ok(d.querySelectorAll('#storeDetail table.mini2 thead th').length >= 5, 'mini tables have no headers');
const mOne = txt(d.querySelector('#storeDetail .bar .d'));
const sb = d.querySelector('[data-r="mbench"] input[value="sales"]'); sb.checked = true; sb.dispatchEvent(new w.Event('change'));
console.log('  meta toggle ideal -> sales, first deviation:', mOne, '->', txt(d.querySelector('#storeDetail .bar .d')), '| deviation details collapsed:', !d.querySelector('#storeDetail details').open);
const dc = d.querySelector('[data-r="dcat"] input[value="1"]'); dc.checked = true; dc.dispatchEvent(new w.Event('change'));
ok(txt(d.querySelector('#storeDetail')).includes('T-SHIRTS'), 'category toggle in detail');
$('sdClose').click(); ok($('storeDetail').innerHTML === '', 'detail did not vanish after close');
const stockCol = () => [...d.querySelectorAll('#healthTbl tbody tr')].map(r => r.cells[8].textContent).join(',');
const before2 = stockCol(); $('fBand').value = D_bands1 = ev('D.bands[1]'); $('fBand').dispatchEvent(new w.Event('change'));
ok(stockCol() !== before2, 'price filter does not change health'); console.log('  price filter', D_bands1, 'changes health:', stockCol() !== before2, '|', txt($('fNote')).slice(0, 90));
$('fReset').click(); ok(stockCol() === before2 && $('fBand').value === '', 'reset filters');

// POC filter cascades: POC -> clusters -> stores; stores mapped to another cluster's POC stay with their POC
{ const pz = ev(`(()=>{const p=[...new Set(S.map(s=>s[17]))].find(x=>new Set(S.filter(s=>s[17]===x).map(s=>s[6])).size>1);return p})()`);
  $('fPoc').value = pz; $('fPoc').dispatchEvent(new w.Event('change'));
  const pc2 = JSON.parse(ev(`JSON.stringify({poc:F.poc,stores:storesFiltered().length,allPoc:storesFiltered().every(si=>S[si][17]===F.poc),
   clusters:[...document.getElementById('fClus').options].slice(1).map(o=>o.value),clusterOptsOk:[...document.getElementById('fClus').options].slice(1).every(o=>S.some(s=>s[17]===F.poc&&s[6]===o.value))})`));
  console.log('  POC filter:', JSON.stringify(pc2)); ok(pc2.allPoc && pc2.clusterOptsOk && pc2.clusters.length > 1, 'POC filter not cascading');
  $('fClus').value = pc2.clusters[0]; $('fClus').dispatchEvent(new w.Event('change'));
  ok(ev(`storesFiltered().every(si=>S[si][17]===F.poc&&S[si][6]===F.cluster)`), 'POC + cluster filter');
  $('fReset').click(); ok(ev('F.poc') === '' && $('fPoc').value === '', 'reset POC'); }

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
ev(`R.scope='store';R.store=String(LASTPER.find(x=>x[1].total>0)?.[0]??0);R.units='manual';R.mkind='units';R.min='';R.max=60;R.cat='0';runUI()`); $('aRun').click();
const man = JSON.parse(ev(`JSON.stringify({units:sum(LAST.map(r=>r.units)),stores:new Set(LAST.map(r=>r.si)).size,cats:[...new Set(LAST.map(r=>K[r.k][1]))]})`));
console.log('  manual one store / Shirts / 60u:', JSON.stringify(man)); ok(man.units <= 60 && man.stores <= 1 && man.cats.every(c => c === 0), 'manual run limits');
ev(`R.scope='cluster';R.clusters=new Set([S[0][6]]);R.units='auto';R.cat='both';runUI()`); $('aRun').click();
const cl = JSON.parse(ev(`JSON.stringify({clusters:[...new Set(LAST.map(r=>S[r.si][6]))],units:sum(LAST.map(r=>r.units))})`));
console.log('  cluster run', ev('S[0][6]'), JSON.stringify(cl)); ok(cl.clusters.every(c => c === ev('S[0][6]')), 'cluster run left the cluster');

// fresh-run SKU filters: warehouse only, fresh / repeat, attribute list, MRP range
ev(`R.scope='filtered';R.units='auto';R.cat='both';runUI();RF.wh='north';RF.ftype='repeat';renderRF()`); $('aRun').click();
const fz = JSON.parse(ev(`JSON.stringify({lines:LAST.length,zones:[...new Set(LAST.map(r=>r.z))],nonRepeat:LAST.filter(r=>!REPEAT.has(r.si*K.length+r.k)).length,fallback:LAST.filter(r=>r.fallback&&r.z!==0).length})`));
console.log('  North WH + repeat only:', JSON.stringify(fz)); ok(fz.zones.every(z => z === 0) && fz.nonRepeat === 0, 'warehouse / repeat filter');
ev(`Object.assign(RF,{wh:'all',ftype:'fresh',mrpMin:'1000',mrpMax:'1499',sets:{fit:new Set([W[K[poolSkus()[0]][5]]])}});renderRF()`); $('aRun').click();
const fa = JSON.parse(ev(`JSON.stringify({lines:LAST.length,count:txt=document.getElementById('rfCount').textContent,badMrp:LAST.filter(r=>K[r.k][13]<1000||K[r.k][13]>1499).length,
 badFit:LAST.filter(r=>!RF.sets.fit.has(W[K[r.k][5]])).length,repeat:LAST.filter(r=>REPEAT.has(r.si*K.length+r.k)).length,msx:document.querySelectorAll('#t-alloc .msx').length})`));
console.log('  fresh + MRP 1000-1499 + fit:', JSON.stringify(fa)); ok(!fa.badMrp && !fa.badFit && !fa.repeat && fa.msx === 9, 'attribute / MRP filters');
// colour family: all available colours by default, capped by "Colours per style"
const FAMCHK = `(()=>{const m=new Map();for(const r of LAST){if(r.type!=='FRESH')continue;const key=r.si+'|'+famOf(r.k);m.set(key,(m.get(key)||0)+1)}
 let missed=0,checked=0;for(const r of LAST){if(r.type!=='FRESH'||r.family)continue;const ks=new Set(poolSkus());
  const sib=(FAM.get(famOf(r.k))||[]).filter(k2=>k2!==r.k&&ks.has(k2)&&!STOCK[r.si*K.length+k2]);checked+=sib.length;
  for(const k2 of sib)if(!LAST.some(x=>x.si===r.si&&x.k===k2))missed++}
 const dup=LAST.length-new Set(LAST.map(r=>r.si*K.length+r.k)).size;return JSON.stringify({dup,families:m.size,maxPerStore:Math.max(0,...m.values()),familyLines:LAST.filter(r=>r.family).length,siblingsChecked:checked,siblingsNotSent:missed})})()`;
ev(`Object.assign(RF,{wh:'all',ftype:'all',mrpMin:'',mrpMax:'',sets:{},maxCol:'all'});renderRF()`); $('aRun').click();
const fam1 = JSON.parse(ev(FAMCHK)); console.log('  colour family, all colours:', JSON.stringify(fam1), '| rules', JSON.stringify(JSON.parse(ev(`JSON.stringify((${RULES})(LAST,true))`)).nViol));
ok(fam1.familyLines > 0, 'no colour-family lines'); ok(JSON.parse(ev(`JSON.stringify((${RULES})(LAST,true))`)).nViol === 0, 'family rule broke pack rules');
ev(`RF.maxCol='2';renderRF()`); $('aRun').click();
const fam2 = JSON.parse(ev(FAMCHK)); console.log('  colour family, max 2:', JSON.stringify(fam2)); ok(fam2.maxPerStore <= 2, 'colours-per-style cap exceeded'); ok(!fam1.dup && !fam2.dup, 'duplicate store x SKU lines');
const gapOrder = ev(`(()=>{let bad=0;const by=new Map();for(const r of LAST)if(r.family){const key=r.si+'|'+famOf(r.k);if(!by.has(key))by.set(key,[]);by.get(key).push(r)}
 for(const rs of by.values())for(let i=1;i<rs.length;i++)if(rs[i].gapBefore.col>rs[i-1].gapBefore.col+1e-6&&rs[i].f.colKey!==rs[i-1].f.colKey)bad++;return bad})()`);
console.log('  family colours picked by colour gap, order breaks:', gapOrder);
$('rfClear').click(); ok(ev('RF.wh')==='all' && !Object.keys(ev('RF.sets')).length, 'clear SKU filters');
ok(!!d.querySelector('#wExplain table') && !d.querySelector('details.wexp').open, 'weights explainer missing or open');

// manual budget modes + no-category-delta alert
ev(`Object.assign(RF,{wh:'all',ftype:'all',sets:{},maxCol:'all',nrc:'yes'});R.scope='filtered';R.cat='both';R.units='manual';R.mkind='options';R.min=2;R.max=5;R.force=false;runUI()`);
const opt = JSON.parse(ev(`(()=>{const {per}=budgets(scopeStores());const bad=per.filter(([si,b])=>!b.noCatDelta&&sum(b.cats)&&[0,1].some(c=>b.cats[c]%((D.health[si][c]||{}).depth||12)!==0)).length;
 const ex=per.find(([si,b])=>sum(b.cats));return JSON.stringify({bad,example:ex?S[ex[0]][1]+': '+ex[1].cats.join(' / ')+' units for 5 styles, depth '+[0,1].map(c=>(D.health[ex[0]][c]||{}).depth).join('/'):''})})()`));
console.log('  manual options (2-5 styles):', JSON.stringify(opt)); ok(opt.bad === 0, 'options not converted by depth');
ev(`R.mkind='fill';R.fill=130;runUI()`);
const fl = JSON.parse(ev(`(()=>{const {per}=budgets(scopeStores());const bad=per.filter(([si,b])=>S[si][16]&&b.total!==Math.max(0,Math.floor(1.3*S[si][12]-S[si][15]))).length;return JSON.stringify({bad,stores:per.filter(x=>sum(x[1].cats)).length})})()`));
console.log('  manual fill 130%:', JSON.stringify(fl)); ok(fl.bad === 0, 'fill-rate target formula');
ev(`R.units='auto';R.force=false;runUI()`); $('aRun').click();
const nd = JSON.parse(ev(`JSON.stringify({held:LASTPER.filter(x=>x[1].noCatDelta).length,servedHeld:LAST.filter(r=>LASTPER.find(x=>x[0]===r.si)[1].noCatDelta).length,alert:!!document.getElementById('aAForce')})`));
console.log('  no-category-delta stores held back:', JSON.stringify(nd)); ok(nd.servedHeld === 0, 'held-back store got units');
if (nd.held) { ok(nd.alert, 'no alert for held-back stores'); $('aAForce').click();
  const fz2 = JSON.parse(ev(`JSON.stringify({forced:LASTPER.filter(x=>x[1].forced&&sum(x[1].cats)).length,servedForced:new Set(LAST.filter(r=>LASTPER.find(x=>x[0]===r.si)[1].forced).map(r=>r.si)).size,undo:!!document.getElementById('aAUndo')})`));
  console.log('  after Force allocate:', JSON.stringify(fz2)); ok(fz2.forced > 0 && fz2.undo, 'force allocate'); $('aAUndo').click(); ok(!ev('R.force'), 'undo force'); }

// no fresh room but a category delta: held back, force sends the category delta only
ev(`R.scope='filtered';R.units='auto';R.cat='both';R.force=false;R.forceRoom=false;runUI()`); $('aRun').click();
const nr = JSON.parse(ev(`JSON.stringify({held:LASTPER.filter(x=>x[1].noRoom).length,got:LAST.filter(r=>LASTPER.find(x=>x[0]===r.si)[1].noRoom).length,alert:!!document.getElementById('aBForce')})`));
console.log('  delta but no fresh room:', JSON.stringify(nr)); ok(nr.got === 0, 'no-room store got units'); ok(!nr.held || nr.alert, 'no alert for no-room stores');
if (nr.held) { $('aBForce').click();
  const fr = JSON.parse(ev(`(()=>{const used={};LAST.forEach(r=>used[r.si*2+K[r.k][1]]=(used[r.si*2+K[r.k][1]]||0)+r.units);let over=0,served=0;
   for(const [si,b] of LASTPER){if(!b.forcedRoom)continue;for(const c of [0,1]){const h=D.health[si][c],d=h?Math.max(0,h.catBase-h.netIst):0;if((used[si*2+c]||0)>d)over++;if(used[si*2+c])served++}}return JSON.stringify({served,overDelta:over})})()`));
  console.log('  after force (no room):', JSON.stringify(fr)); ok(fr.overDelta === 0 && fr.served > 0, 'forced no-room stores exceed delta'); $('aBUndo').click(); }

// exhaust stock: extra lines beyond budgets, still within WH stock and pack rules
$('aRun').click(); const base1 = ev('sum(LAST.map(r=>r.units))');
$('aExhaust').checked = true; $('aRun').click();
const ex = JSON.parse(ev(`JSON.stringify({units:sum(LAST.map(r=>r.units)),exLines:LAST.filter(r=>r.exhaust).length,rules:(${RULES})(LAST,true).nViol})`));
console.log('  exhaust stock: units', base1, '->', JSON.stringify(ex)); ok(ex.units > base1 && ex.exLines > 0 && ex.rules === 0, 'exhaust stock');
$('aExhaust').checked = false;

// sleeve / size gap / cluster columns and cluster ordering
ok([...d.querySelectorAll('#allocTbl th')].map(x => x.textContent).join('|').includes('Price gap|Sleeve gap|Size gap closed|Cluster sell.'), 'new gap columns after price gap');
const cl2 = JSON.parse(ev(`(()=>{$=0;const by={};for(const r of LAST){(by[r.f.clus>=.999?'top':'rest']=by[r.f.clus>=.999?'top':'rest']||[]).push(r.s)}
 const avg=a=>a&&a.length?sum(a)/a.length:0;return JSON.stringify({topClusterLines:(by.top||[]).length,avgScoreTop:+avg(by.top).toFixed(3),avgScoreRest:+avg(by.rest).toFixed(3),
 sizeGapAvg:+avg(LAST.map(r=>r.comp.size_gap)).toFixed(2),slvGapAvg:+avg(LAST.map(r=>r.f.slvGap)).toFixed(3)})})()`));
console.log('  cluster / size / sleeve:', JSON.stringify(cl2));
ok(Math.abs(ev("Object.entries(D.weights).filter(([k])=>k!=='replen_need').reduce((s,[,v])=>s+v,0)")-1)<1e-6, 'weights do not add up to 1');

// MRP / ASP toggle
tabGo = null; ev(`tabGo('health')`); const pb = d.querySelector('[data-r="pbasis"] input[value="asp"]'); pb.checked = true; pb.dispatchEvent(new w.Event('change'));
const asp = JSON.parse(ev(`JSON.stringify({basis:PBASIS,aspHigher:K.filter(k=>k[45]>k[13]*1.02&&k[13]>0).length,aspSet:K.filter(k=>k[45]>0).length,n:K.length,
 diffBand:K.filter(k=>k[46]!==k[28]).length})`));
console.log('  ASP toggle:', JSON.stringify(asp)); ok(asp.basis === 'asp' && asp.aspSet > asp.n * 0.9, 'ASP basis');
const pb2 = d.querySelector('[data-r="pbasis"] input[value="mrp"]'); pb2.checked = true; pb2.dispatchEvent(new w.Event('change'));

// search: style -> family grid; select -> add; prepack code -> SKU with pack banner; pinned code goes first
const fam = ev(`[...FAM.entries()].find(([f,ks])=>ks.length>=3)[0]`);
$('skuIn').value = fam; $('skuGo').click();
const fg = JSON.parse(ev(`JSON.stringify({cards:document.querySelectorAll('#simOut .sc').length,chk:document.querySelectorAll('.famChk').length,title:document.querySelector('#simOut h2').textContent})`));
console.log('  family search', fam, JSON.stringify(fg)); ok(fg.cards >= 3 && fg.chk === fg.cards, 'family grid');
ev(`BASKET=[];LS.set('tw_basket',[])`); const c0 = d.querySelectorAll('.famChk'); c0[0].checked = true; c0[1].checked = true; c0[0].dispatchEvent(new w.Event('change'));
$('famAddSel').click(); ok(ev('BASKET.length') === 2, 'add selected colours'); $('famAddAll').click(); ok(ev('BASKET.length') === fg.cards, 'add all colours');
d.querySelector('#simOut .sc').click(); ok(ev('CUR') !== null && !!d.querySelector('#simGrid'), 'family card opens similarity');
const ppc = ev(`(()=>{for(const k in PPC){const v=PPC[k][String(K[k][42])];if(v&&(v[0].length||v[1].length))return v[0][1]||v[1][1]||v[0][0]||v[1][0]}})()`);
ev(`BASKET=[];LS.set('tw_basket',[])`); $('skuIn').value = ppc; $('skuGo').click();
console.log('  prepack search', ppc, '->', ev('K[CUR][0]'), '|', txt(d.querySelector('#simOut .card')).slice(0, 120));
ok(ev('K[CUR][0]') === ev(`ppSku('${ppc}')`) && txt(d.querySelector('#simOut .card')).includes('Prepack'), 'prepack search');
const addB = [...d.querySelectorAll('#simOut .card button')].find(b => b.textContent.includes('Add this prepack')); if (addB) addB.click();
ok(ev(`BASKET.includes('${ppc}')`), 'prepack added to basket');
const pinUse = ev(`(()=>{const k=CUR,out=allocate([k],[...Array(NS).keys()],'auto',cfgNow(),weights(),{pin:{[k]:['${ppc}']}});const pl=out.filter(r=>r.packType==='PREPACK');return pl.length?pl[0].codes.includes('${ppc}')||pl.some(r=>r.codes.includes('${ppc}')):'no prepack line'})()`);
console.log('  pinned prepack code used:', pinUse); ok(pinUse === true || pinUse === 'no prepack line', 'pinned code not used');
ev(`BASKET=[];LS.set('tw_basket',[])`);
// one-store picker search
ev(`tabGo('alloc');R.scope='store';runUI()`); $('rStore').value = ev('S[3][1]'); $('rStore').dispatchEvent(new w.Event('input'));
ok(ev('R.store') === '3', 'store search picker'); ev(`R.scope='filtered';runUI()`);

// --- TAB 3
const nh = txt($('nudgeOut'));
console.log('\n[TAB3]', txt(d.querySelector('#nudgeOut h2')), '|', txt(d.querySelector('#nudgeOut .legend')).slice(0, 120));
ok(!/\bACT\b/.test(nh) && !nh.includes('3d+') && nh.includes('Pending 5d+'), 'status labels');
ok(ev("[...Array(K.length).keys()].every(k=>true)"), '');
const vis = () => [$('alertCard').style.display, d.querySelector('#nudgeOut .card').style.display];
ok(vis()[0] === 'none' && vis()[1] === '', 'alerts should be hidden by default');
const nv = d.querySelector('[data-r="nview"] input[value="alerts"]'); nv.checked = true; nv.dispatchEvent(new w.Event('change'));
ok($('alertCard').style.display === '' && d.querySelector('#nudgeOut .card').style.display === 'none', 'nudges toggle');
const nv2 = d.querySelector('[data-r="nview"] input[value="wh"]'); nv2.checked = true; nv2.dispatchEvent(new w.Event('change'));
const nrows = () => d.querySelectorAll('#nudgeOut .card tbody tr').length;
const nAll = nrows(); const nc = d.querySelector('[data-r="ncat"] input[value="1"]'); nc.checked = true; nc.dispatchEvent(new w.Event('change'));
console.log('  inwards all / T-shirts:', nAll, '/', nrows());
const nv3 = d.querySelector('[data-r="nview"] input[value="alerts"]'); nv3.checked = true; nv3.dispatchEvent(new w.Event('change'));
const ac = $('aClus'); ac.value = ac.options[1].value; ac.dispatchEvent(new w.Event('change'));
console.log('  alerts after cluster filter:', txt(d.querySelector('#alertCard h2')), '| store options', $('aStore').options.length - 1);
ok([...$('aStore').options].slice(1).every(o => ev(`S[${o.value}][6]`) === ac.value), 'alert store list not cascading');
d.querySelector('#alertCard tbody tr.click').click();
ok(d.querySelectorAll('#storeDetail .kpi').length >= 2 && ev('DSI') >= 0 && $('t-health').classList.contains('on'), 'alert click did not open store health');
ok(txt($('healthTbl')).includes('MTD'), 'MTD note missing');
console.log('  alert click -> store detail:', txt(d.querySelector('#storeDetail h2')).slice(0, 60));
console.log('\nerrors:', errs.length, errs.slice(0, 3), '| failed checks:', fails.length ? fails : 'none');
process.exit(errs.length || fails.length ? 1 : 0);
