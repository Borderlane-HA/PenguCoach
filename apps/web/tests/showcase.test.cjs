const {test,after}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const os=require('node:os');
const path=require('node:path');
const {execFileSync}=require('node:child_process');
const temporary=fs.mkdtempSync(path.join(os.tmpdir(),'pengucoach-showcase-'));
execFileSync(process.execPath,[require.resolve('typescript/bin/tsc'),'lib/showcase.ts','--module','commonjs','--target','ES2022','--skipLibCheck','--outDir',temporary],{cwd:path.resolve(__dirname,'..')});
const S=require(path.join(temporary,'showcase.js'));
after(()=>fs.rmSync(temporary,{recursive:true,force:true}));

test('sport kinds follow Garmin, SparkyFitness and German names',()=>{
  assert.equal(S.kindOf('trail_running'),'run');assert.equal(S.kindOf('road_biking'),'ride');
  assert.equal(S.kindOf('lap_swimming'),'swim');assert.equal(S.kindOf('hiking'),'hike');
  assert.equal(S.kindOf('Krafttraining'),'strength');assert.equal(S.kindOf(null),'other');
});
test('headline figures suit the sport and never turn missing data into zero',()=>{
  const run=S.headlineStats({sport_type:'running',distance_m:10000,moving_seconds:3000,avg_speed:10000/3000,avg_hr:150,elevation_gain:5},null,'de');
  assert.deepEqual(run.map(s=>s.key),['distance','time','pace','hr']);
  assert.equal(run[0].value,'10,00');assert.equal(run[2].value,'5:00');
  const swim=S.headlineStats({sport_type:'lap_swimming',distance_m:1500,duration_seconds:1800},null,'en');
  assert.equal(swim[0].unit,'m');assert.equal(swim[2].value,'2:00');assert.equal(swim[2].unit,'/100 m');
  const strength=S.headlineStats({sport_type:'strength_training',duration_seconds:2400,elevation_gain:80,calories:300},null,'de');
  assert.deepEqual(strength.map(s=>s.key),['time','kcal']);
  assert.deepEqual(S.headlineStats({sport_type:'running'},null,'de'),[]);
});
test('routes keep their real shape, stay inside the box and split at gaps',()=>{
  const data=[];for(let i=0;i<50;i++)data.push({position_lat:48+i*.0001,position_long:11,elapsed_s:i});
  for(let i=0;i<50;i++)data.push({position_lat:48.005,position_long:11+i*.0001,elapsed_s:500+i});
  const box={x:10,y:20,w:400,h:300},route=S.projectRoute(data,box);
  assert.equal(route.segments.length,2);
  for(const p of route.segments.flat()){assert.ok(p.x>=box.x-.01&&p.x<=box.x+box.w+.01);assert.ok(p.y>=box.y-.01&&p.y<=box.y+box.h+.01)}
  assert.ok(route.start.y>route.segments[0].at(-1).y,'north is up');
  assert.equal(S.projectRoute([{position_lat:null,position_long:null}],box),null);
});
test('route colours spread over the recorded range',()=>{
  const seg=[Array.from({length:100},(_,i)=>({x:i,y:0,sample:{heart_rate:100+i}}))];
  const runs=S.colouredRuns(seg,'heart_rate');
  assert.deepEqual([...new Set(runs.map(r=>r.bucket))].sort(),[0,1,2,3,4]);
  assert.deepEqual(S.colouredRuns([[{x:0,y:0,sample:{}},{x:1,y:1,sample:{}}]],'heart_rate'),[]);
});
test('zone time uses recorded samples and ignores long gaps',()=>{
  const zones=[{low:100,high:129},{low:130,high:149},{low:150,high:null}];
  const data=[{elapsed_s:0,heart_rate:120},{elapsed_s:10,heart_rate:140},{elapsed_s:20,heart_rate:160},{elapsed_s:500,heart_rate:160},{elapsed_s:505}];
  assert.deepEqual(S.zoneSeconds(data,zones),[10,10,5]);
  assert.equal(S.zonesFromProfiles([{sport:'CYCLING',zones:[{low_bpm:1},{low_bpm:2},{low_bpm:3}]},{sport:'DEFAULT',zones:[{low_bpm:9},{low_bpm:10},{low_bpm:11}]}],'run')[0].low,9);
  assert.equal(S.zonesFromProfiles([],'run'),null);
});
test('personal bests are highlighted only when they belong to this activity',()=>{
  const own=[{metric:'speed',seconds:300,value:13.2},{metric:'speed',seconds:60,value:14}];
  const personal=[{metric:'speed',seconds:300,value:13.2,activity_id:'a'},{metric:'speed',seconds:60,value:15,activity_id:'b'}];
  assert.deepEqual(S.personalRecords('a',own,personal),[own[0]]);
  assert.deepEqual(S.personalRecords('b',own,personal),[]);
  assert.equal(S.effortText(own[0],'run','de'),'5 min · 4:33 /km');
  assert.equal(S.effortText({metric:'power',seconds:1200,value:251.4},'ride','de'),'20 min · 251 W');
});
test('titles are shortened to the measured width and file names are safe',()=>{
  const measure=v=>v.length*10;
  assert.equal(S.fitText('Kurzer Lauf',200,20,measure),'Kurzer Lauf');
  const short=S.fitText('Ein sehr langer Aktivitätsname',100,20,measure);
  assert.ok(short.endsWith('…')&&measure(short)<=100);
  assert.equal(S.fileName({name:'Lauf: Isar / Süd!',started_at:'2026-10-22T17:42:00Z'},'story'),'PenguCoach-Lauf-Isar-Sud-2026-10-22-story.png');
  assert.equal(S.elevationProfile([{altitude_m:1}],{x:0,y:0,w:1,h:1}),null);
});
