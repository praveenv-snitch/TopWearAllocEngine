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

// --- allocation rules on the bulk run
d.querySelector('#aMode').value = 'auto'; let t = Date.now(); $('aRun').click();
console.log('\n[TAB2] health rows', d.querySelectorAll('#healthTbl tbody tr').length, '| alloc', Date.now() - t, 'ms |', txt($('allocSum')));
const chk = ev(`(()=>{const fs=D.packs.fresh_set,bad=[];let fl=0,fp=0,rl=0,rp=0;
 for(const r of LAST){const a=K[r.k];
  if(r.packType==='PREPACK'){ if(r.units!==r.packs*a[42]||r.packs<1||r.packs>2)bad.push('prepack '+a[0]); r.type==='FRESH'?fp++:rp++; }
  else if(r.type==='FRESH'){ const set=PLUS_RE.test(a[0])?D.packs.fresh_set_plus:fs; if(r.split.some((v,i)=>v>set[i]))bad.push('fresh>set '+a[0]);
   if(!PLUS_RE.test(a[0])&&[1,2,3,4].some(i=>r.split[i]<set[i]))bad.push('fresh set missing core size '+a[0]); fl++; }
  else { rl++; }
  if(r.type==='FRESH'&&STOCK[r.si*K.length+r.k])bad.push('fresh to carrying store '+a[0]);
  if(r.type==='REPLEN'&&!STOCK[r.si*K.length+r.k])bad.push('replen to non-carrying store '+a[0]);}
 // WH never over-allocated (loose by size, packs by zone)
 const use=new Map();for(const r of LAST){const u=use.get(r.k)||{l:[Array(10).fill(0),Array(10).fill(0)],p:[0,0]};
  if(r.packType==='PREPACK')u.p[r.z]+=r.packs;else r.split.forEach((v,i)=>u.l[r.z][i]+=v);use.set(r.k,u)}
 for(const [k,u] of use){const a=K[k];for(const z of [0,1]){if(u.p[z]>a[43+z])bad.push('packs over '+a[0]);u.l[z].forEach((v,i)=>{if(v>a[20+z][i])bad.push('loose over '+a[0]+' '+SZ[i])})}}
 return JSON.stringify({fresh_loose:fl,fresh_prepack:fp,replen_loose:rl,replen_prepack:rp,violations:bad.slice(0,5),nViol:bad.length})})()`);
console.log('  rule check:', chk);
// gaps are shared: for the same store x category x colour, each later line sees the gap reduced by the earlier lines
const share = ev(`(()=>{const seen=new Map();let pairs=0,bad=0;for(const r of LAST){const key=r.si+'|'+r.f.c+'|'+r.f.colKey;
  if(seen.has(key)){pairs++;const p=seen.get(key);if(Math.abs(r.gapBefore.col-(p.gapBefore.col-p.units))>1e-6)bad++}seen.set(key,r)}
  return JSON.stringify({sameColourPairs:pairs,notShared:bad})})()`);
console.log('  colour-gap sharing:', share); ok(JSON.parse(share).notShared === 0, 'colour gap not shared between SKUs'); ok(JSON.parse(chk).nViol === 0, 'allocation rule violations');
[...d.querySelectorAll('#allocTbl tbody tr')].slice(0, 4).forEach(r => console.log('   ', [...r.cells].slice(0, 11).map(c => c.textContent.trim()).join(' | ')));
ok(d.querySelectorAll('#allocTbl th[title]').length > 10, 'column tooltips missing');
$('aCsv').click();
console.log('\n[TAB3]', txt(d.querySelector('#nudgeOut h2')));
console.log('\nerrors:', errs.length, errs.slice(0, 3), '| failed checks:', fails.length ? fails : 'none');
process.exit(errs.length || fails.length ? 1 : 0);
