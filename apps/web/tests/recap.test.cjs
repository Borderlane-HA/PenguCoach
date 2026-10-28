const {test,after}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const os=require('node:os');
const path=require('node:path');
const {execFileSync}=require('node:child_process');
const temporary=fs.mkdtempSync(path.join(os.tmpdir(),'pengucoach-recap-'));
execFileSync(process.execPath,[require.resolve('typescript/bin/tsc'),'lib/recap.ts','--module','commonjs','--target','ES2022','--skipLibCheck','--outDir',temporary],{cwd:path.resolve(__dirname,'..')});
const R=require(path.join(temporary,'recap.js'));
after(()=>fs.rmSync(temporary,{recursive:true,force:true}));

test('titles follow the period and language',()=>{
  assert.equal(R.periodTitle('month','2026-10-01','de'),'Dein Oktober');
  assert.equal(R.periodTitle('year','2026-01-01','en'),'Your 2026');
  assert.equal(R.periodTitle('all',null,'de'),'Deine ganze Geschichte');
});
test('comparisons pick a fitting scale',()=>{
  assert.equal(R.distanceFact(84.39,'de').text,'2,0 Marathons');
  assert.equal(R.distanceFact(1170,'de').text,'2,0 × von München nach Berlin');
  assert.match(R.distanceFact(4007.5,'en').text,/^10\.0 % of the way around the Earth$/);
  assert.equal(R.elevationFact(5924,'de').text,'1,2 × die Höhe vom Mont Blanc');
  assert.equal(R.elevationFact(165,'de').text,'50 % vom Eiffelturm');
  assert.equal(R.elevationFact(0,'de'),null);
  assert.equal(R.timeFact(10800,'de').text,'so lang wie 2,0 Tatort-Folgen');
  assert.equal(R.energyFact(1700,'de').text,'≈ 2,0 Pizzen Margherita');
});
test('heatmap ignores a single far-away holiday route',()=>{
  const home=Array.from({length:20},(_,i)=>({id:`h${i}`,points:[[48.1+i*1e-3,11.5],[48.12+i*1e-3,11.52]]}));
  const holiday={id:'far',points:[[28.1,-15.4],[28.2,-15.3]]};
  const paths=R.projectRoutes([...home,holiday],{x:0,y:0,w:800,h:600});
  assert.equal(paths.length,20);assert.ok(!paths.some(p=>p.id==='far'));
  const single=R.projectRoutes([{id:'one',points:[[48,11],[48.001,11.002]]}],{x:0,y:0,w:100,h:100});
  assert.equal(single.length,1);
  assert.deepEqual(R.projectRoutes([],{x:0,y:0,w:1,h:1}),[]);
});
test('calendar levels and Monday-first year grid',()=>{
  const cells=R.calendar({items:[{key:'2026-10-21',count:0,duration_s:0},{key:'2026-10-22',count:1,duration_s:600},{key:'2026-10-23',count:2,duration_s:3600}]});
  assert.deepEqual(cells.map(c=>c.level),[0,1,4]);
  const grid=R.weekGrid(cells);
  assert.equal(grid[0].length,5);assert.equal(grid[0][0],null);assert.equal(grid[0][2].key,'2026-10-21');
});
test('slides appear only when there is something to show',()=>{
  assert.deepEqual(R.slides(null),[]);
  assert.deepEqual(R.slides({totals:{count:0}}),[]);
  const one={period:'today',totals:{count:1,distance_m:0,elevation_m:0,duration_s:1800,calories:0},sports:[{sport:'strength'}],highlights:{longest_duration:{}},routes:[],series:{items:[]},previous:{count:0},change:{}};
  assert.deepEqual(R.slides(one),['intro','time','finale']);
  const rich={period:'year',totals:{count:9,distance_m:1,elevation_m:1,duration_s:1,calories:1},sports:[{},{}],highlights:{a:{}},routes:[{}],series:{items:[{},{}]},previous:{count:3},change:{distance_m:12}};
  assert.deepEqual(R.slides(rich),['intro','distance','elevation','time','sports','highlights','map','calendar','compare','finale']);
});
test('numbers stay readable',()=>{
  assert.equal(R.compact(1234567,'de'),'1,2 Mio.');assert.equal(R.compact(12.34,'de'),'12,3');
  assert.equal(R.hoursText(5400,'de'),'1 h 30 min');assert.equal(R.paceText(299.6),'5:00 /km');
  assert.equal(R.fileName('year','2026-10-23'),'PenguCoach-Rueckblick-year-2026-10-23.png');
});
