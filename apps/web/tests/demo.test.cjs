const {test,after}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');const os=require('node:os');const path=require('node:path');
const {execFileSync}=require('node:child_process');
const temporary=fs.mkdtempSync(path.join(os.tmpdir(),'pengucoach-demo-'));
execFileSync(process.execPath,[require.resolve('typescript/bin/tsc'),'lib/demo.ts','--module','commonjs','--target','ES2022','--skipLibCheck','--lib','ES2022,DOM','--outDir',temporary],{cwd:path.resolve(__dirname,'..')});
const D=require(path.join(temporary,'demo.js'));
after(()=>fs.rmSync(temporary,{recursive:true,force:true}));
const DATA=path.resolve(__dirname,'..','demo','data');

test('dates move by whole weeks so weekdays stay',()=>{
  assert.equal(D.shiftDays('2026-11-07',new Date(2026,10,7)),0);
  assert.equal(D.shiftDays('2026-11-07',new Date(2026,10,10)),0);
  assert.equal(D.shiftDays('2026-11-07',new Date(2026,10,12)),7);
  assert.equal(D.shiftDays('2026-11-07',new Date(2027,2,1)),112);
  assert.equal(D.shiftDate('2026-11-07',7),'2026-11-14');
  assert.equal(D.shiftDate('2026-12-28T06:30:00+00:00',7),'2027-01-04T06:30:00+00:00');
  assert.equal(D.shiftDate('Halbmarathon 2026-12',7),'Halbmarathon 2026-12');
  assert.equal(D.shiftDate('12:30',7),'12:30');
  assert.deepEqual(D.shiftAll({date:'2026-11-07',days:{'2026-11-06':3},n:2026,list:['2026-01-01']},7),{date:'2026-11-14',days:{'2026-11-13':3},n:2026,list:['2026-01-08']});
});
test('lookup keys sort the query and move dates back',()=>{
  assert.equal(D.keyFor('/calendar/month','?start=2026-11-30&end=2027-01-10',7),'/calendar/month?end=2027-01-03&start=2026-11-23');
  assert.equal(D.keyFor('/today','',7),'/today');
});
test('the demo never claims changes are saved',()=>{
  assert.match(D.DEMO_READ_ONLY.de,/nicht gespeichert/);assert.match(D.DEMO_READ_ONLY.en,/not saved/);
});
test('demo fixtures are complete and anonymous',{skip:!fs.existsSync(path.join(DATA,'index.json'))},()=>{
  const index=JSON.parse(fs.readFileSync(path.join(DATA,'index.json'),'utf8'));
  assert.match(index.recorded,/^\d{4}-\d{2}-\d{2}$/);
  const bundles={};
  for(const [key,file] of Object.entries(index.entries)){bundles[file]??=JSON.parse(fs.readFileSync(path.join(DATA,file),'utf8'));assert.ok(key in bundles[file],key)}
  assert.ok(fs.readdirSync(DATA).length<20,'few files, so a GitHub web upload stays small');
  for(const key of ['/auth/me','/setup/status','/coach/readiness','/tours','POST /tours/plan'])assert.ok(Object.keys(index.entries).some(k=>k===key||k.startsWith(key+'?')),key);
  const ids=JSON.parse(fs.readFileSync(path.join(DATA,'activities.json'),'utf8'));
  assert.ok(ids.length>=5);
  for(const id of ids){assert.ok(index.entries[`/activities/${id}`],id);assert.ok(Object.keys(index.entries).some(k=>k.startsWith(`/activities/${id}/series`)),id)}
  const me=bundles[index.entries['/auth/me']]['/auth/me'];
  const user=me.user??me;assert.equal(user.username,'Pia');assert.notEqual(user.role,'admin');
  const all=fs.readdirSync(DATA).map(f=>fs.readFileSync(path.join(DATA,f),'utf8')).join('\n');
  for(const secret of ['sv@','"SV"','Etting','sv2081','ciphertext','api_key"'])assert.ok(!all.includes(secret),secret);
});
