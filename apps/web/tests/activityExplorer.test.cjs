const {test,after}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const os=require('node:os');
const path=require('node:path');
const {execFileSync}=require('node:child_process');
const temporary=fs.mkdtempSync(path.join(os.tmpdir(),'pengucoach-explorer-'));
execFileSync(process.execPath,[require.resolve('typescript/bin/tsc'),'lib/activityExplorer.ts','--module','commonjs','--target','ES2022','--skipLibCheck','--outDir',temporary],{cwd:path.resolve(__dirname,'..')});
const {finite,makeAxis,nearestIndex,routeSegments,linePath,METRICS,metricLabel,bearing}=require(path.join(temporary,'activityExplorer.js'));
after(()=>fs.rmSync(temporary,{recursive:true,force:true}));

test('missing values never become zero while zero watts and equator coordinates remain valid',()=>{
  for(const value of [null,undefined,'',' ',false,true,NaN,Infinity,{},[]])assert.equal(finite(value),null);
  assert.equal(finite(0),0);assert.equal(finite('0'),0);
  assert.equal(routeSegments([{position_lat:0,position_long:0}])[0][0].lat,0);
});
test('chart uses actual irregular time and distance positions for cursor lookup',()=>{
  const data=[{elapsed_s:0,distance_km:0},{elapsed_s:10,distance_km:.1},{elapsed_s:90,distance_km:2},{elapsed_s:100,distance_km:2.5}];
  assert.deepEqual(makeAxis(data,'time').positions,[0,.1,.9,1]);
  assert.deepEqual(makeAxis(data,'distance').positions,[0,.04,.8,1]);
  assert.equal(nearestIndex(makeAxis(data,'time').positions,.8),2);
  assert.equal(nearestIndex(makeAxis(data,'time').positions,-1),0);
  assert.equal(nearestIndex(makeAxis(data,'time').positions,2),3);
});
test('missing, constant and non-monotonic axes are explicitly point order',()=>{
  for(const data of [[{},{}],[{elapsed_s:1},{elapsed_s:1}],[{elapsed_s:5},{elapsed_s:2}],[{elapsed_s:0},{elapsed_s:null}]])assert.equal(makeAxis(data,'time').kind,'points');
  assert.deepEqual(makeAxis([],'time').positions,[]);
});
test('GPS gaps, invalid coordinates, time gaps and GPX boundaries split rather than bridge routes',()=>{
  const point=(index,extra={})=>({position_lat:48+index*.001,position_long:11,elapsed_s:index*10,...extra});
  const segments=routeSegments([point(0),point(1),point(2,{position_lat:null}),point(3),point(4,{track_segment:1}),point(5,{track_segment:1,elapsed_s:300}),point(6,{position_long:181})]);
  assert.deepEqual(segments.map(s=>s.map(p=>p.index)),[[0,1],[3],[4],[5]]);
  assert.equal(segments[0][0].sample.elapsed_s,0);
});
test('missing sensor values leave line gaps and are not formatted as measurements',()=>{
  const metric=METRICS.find(m=>m.key==='power');
  const path=linePath([{power:0},{power:null},{power:100}],metric,[0,.5,1],100,50,5);
  assert.equal((path.match(/M/g)||[]).length,2);
  assert.equal((path.match(/ L/g)||[]).length,0);
  assert.equal(metricLabel(metric,null),'—');assert.equal(metricLabel(metric,0),'0 W');
});
test('pace rounding carries seconds into the next minute and route bearing follows travel',()=>{
  assert.equal(metricLabel(METRICS.find(m=>m.key==='pace_s_per_km'),299.9),'5:00 min/km');
  const points=routeSegments([{position_lat:0,position_long:0},{position_lat:0,position_long:1}]).flat();
  assert.equal(Math.round(bearing(points,0)),90);
});
