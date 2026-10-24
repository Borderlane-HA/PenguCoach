const {test,after}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');const os=require('node:os');const path=require('node:path');
const {execFileSync}=require('node:child_process');
const temporary=fs.mkdtempSync(path.join(os.tmpdir(),'pengucoach-health-'));
execFileSync(process.execPath,[require.resolve('typescript/bin/tsc'),'lib/healthInsights.ts','--module','commonjs','--target','ES2022','--skipLibCheck','--outDir',temporary],{cwd:path.resolve(__dirname,'..')});
const H=require(path.join(temporary,'healthInsights.js'));
after(()=>fs.rmSync(temporary,{recursive:true,force:true}));
const hrv=H.metricDef?H.metricDef('hrv'):H.HEALTH_METRICS.find(m=>m.key==='hrv');
const rows=vals=>vals.map((v,i)=>({date:`2026-10-${String(i+1).padStart(2,'0')}`,overnight_average:v}));

test('summary averages only real values and compares both halves',()=>{
  const s=H.summarize(rows([40,null,42,'',44,50,52,54]),hrv);
  assert.equal(s.count,6);assert.equal(s.avg,47);assert.equal(s.latest,54);
  assert.equal(s.first,42);assert.equal(s.second,52);assert.equal(s.trend,'up');assert.equal(s.good,true);
});
test('tiny changes are flat, not a trend',()=>{
  const s=H.summarize(rows([50,50,50.4,50.3]),hrv);assert.equal(s.trend,'flat');assert.equal(s.good,null);
});
test('a lower resting heart rate counts as an improvement',()=>{
  const rhr=H.HEALTH_METRICS.find(m=>m.key==='resting_hr');
  const s=H.summarize([60,60,52,52].map((v,i)=>({date:`2026-10-0${i+1}`,resting_hr:v})),rhr);
  assert.equal(s.trend,'down');assert.equal(s.good,true);
});
test('empty data gives an empty summary and an honest prompt',()=>{
  const s=H.summarize([],hrv);assert.equal(s.count,0);assert.equal(s.avg,null);
  assert.match(H.coachPrompt(hrv,s,'de','letzte 30 Tage'),/keine Werte/);
});
test('coach prompt explains the value and asks how to improve it',()=>{
  const s=H.summarize(rows([40,42,44,46]),hrv);
  const de=H.coachPrompt(hrv,s,'de','letzte 30 Tage');
  assert.match(de,/HRV/);assert.match(de,/Durchschnitt 43 ms/);assert.match(de,/verbessern/);
  assert.match(H.coachPrompt(hrv,s,'en','last 30 days'),/improve/);
});
test('tiles stay in one row up to six, then two balanced rows',()=>{
  assert.deepEqual([1,2,3,6,7,8,9].map(H.tileColumns),[1,2,3,6,4,4,5]);
});
test('preferences drop unknown keys and keep at least one value',()=>{
  const p=H.normalizeHealth({order:['body','nope','body'],hidden:['x'],metrics:[],period:'13'});
  assert.equal(p.order[0],'body');assert.equal(p.order.length,H.HEALTH_SECTIONS.length);
  assert.deepEqual(p.hidden,[]);assert.deepEqual(p.metrics,H.DEFAULT_HEALTH.metrics);assert.equal(p.period,'30');
  assert.deepEqual(H.normalizeHealth(null).hidden,['coverage']);
});
test('recap only shows slides that have data',()=>{
  const s=k=>({[k]:{count:3}});
  assert.deepEqual(H.recapSlides({}),[]);
  assert.deepEqual(H.recapSlides({...s('sleep'),...s('steps')}),['intro','sleep','steps','finale']);
});
test('every metric has a plain explanation in both languages',()=>{
  for(const m of H.HEALTH_METRICS){assert.ok(m.info.de.length>30,m.key);assert.ok(m.info.en.length>30,m.key);assert.doesNotMatch(m.info.de,/API|Endpoint|Parquet|Celery/)}
});
test('missing readings are never zeros, real zero floors count',()=>{
  const floors=H.HEALTH_METRICS.find(m=>m.key==='floors');
  const s=H.summarize([{date:'2026-10-01',floors_ascended:0},{date:'2026-10-02',floors_ascended:null},{date:'2026-10-03',floors_ascended:10}],floors);
  assert.equal(s.count,2);assert.equal(s.avg,5);
  const h=H.summarize([{date:'2026-10-01',overnight_average:null},{date:'2026-10-02',overnight_average:50}],hrv);
  assert.equal(h.count,1);assert.equal(h.avg,50);
});
