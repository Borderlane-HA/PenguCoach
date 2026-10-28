const {test,after}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');const os=require('node:os');const path=require('node:path');
const {execFileSync}=require('node:child_process');
const temporary=fs.mkdtempSync(path.join(os.tmpdir(),'pengucoach-today-'));
execFileSync(process.execPath,[require.resolve('typescript/bin/tsc'),'lib/todayLayout.ts','lib/help.ts','--module','commonjs','--target','ES2022','--skipLibCheck','--outDir',temporary],{cwd:path.resolve(__dirname,'..')});
const T=require(path.join(temporary,'todayLayout.js')),H=require(path.join(temporary,'help.js'));
after(()=>fs.rmSync(temporary,{recursive:true,force:true}));

test('normalize drops unknown keys and appends missing cards',()=>{
  const v=T.normalizeToday({order:['metrics','bogus','metrics'],hidden:['x','week'],pinned_metrics:[],density:'huge'});
  assert.equal(v.order[0],'metrics');assert.equal(v.order.length,T.CARD_KEYS.length);
  assert.deepEqual(v.hidden,['week']);assert.deepEqual(v.pinned_metrics,T.DEFAULT_TODAY.pinned_metrics);assert.equal(v.density,'comfortable');
});
test('half cards pair up, a lone half card takes the full row',()=>{
  const prefs=T.normalizeToday({});
  const layout=T.visibleCards({...prefs,hidden:['preparation','weather','progress','trend','reflection']});
  const span=k=>layout.find(x=>x.key===k).span;
  assert.equal(span('readiness'),7);assert.equal(span('checkin'),5);assert.equal(span('metrics'),12);
  assert.equal(span('load'),6);assert.equal(span('activities'),6);assert.equal(span('week'),12);
  assert.ok(!layout.some(x=>x.key==='reflection'));
  const alone=T.visibleCards({...prefs,hidden:['checkin']});assert.equal(alone.find(x=>x.key==='readiness').span,12);
});
test('move and toggle keep lists consistent',()=>{
  assert.deepEqual(T.move(['a','b','c'],'b',-1),['b','a','c']);assert.deepEqual(T.move(['a','b'],'a',-1),['a','b']);
  assert.deepEqual(T.toggle(['a'],'b',true),['a','b']);assert.deepEqual(T.toggle(['a','b'],'a',false),['b']);
});
test('greeting follows the hour, ring follows the score, status picks the worst',()=>{
  assert.equal(T.greeting(7,'de','SV'),'Guten Morgen, SV');assert.equal(T.greeting(19,'en'),'Good evening');
  const r=T.ringDash(50,10);assert.ok(Math.abs(r.dash-r.length/2)<1e-9);assert.equal(T.ringDash(null,10).dash,0);
  assert.equal(T.overallStatus([{connected:true,status:'connected'},{connected:false,status:'reauth_required'}],true),'attention');
  assert.equal(T.overallStatus([{connected:true}],false),'offline');assert.equal(T.overallStatus([{connected:false}],true),'idle');
});
test('help covers both languages, admin sections stay hidden for users, search works',()=>{
  for(const s of H.HELP_SECTIONS){for(const x of [s.title,s.intro,...s.topics.flatMap(t=>[t.q,t.a]),...s.links.map(l=>l.label)]){assert.ok(x.de&&x.en,s.id)}}
  assert.ok(!H.filterHelp('','de',false).some(s=>s.id==='admin'));assert.ok(H.filterHelp('','de',true).some(s=>s.id==='admin'));
  const hits=H.filterHelp('API-Key','de',false);assert.ok(hits.some(s=>s.id==='garmin'));
  assert.deepEqual(H.filterHelp('zzzz-nothing','en',true),[]);
  const ids=H.HELP_SECTIONS.map(s=>s.id);assert.equal(new Set(ids).size,ids.length);
  for(const id of ['today','garmin','activities','updates'])assert.ok(ids.includes(id));
});
