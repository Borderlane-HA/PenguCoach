const {test,after}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');const os=require('node:os');const path=require('node:path');
const {execFileSync}=require('node:child_process');
const temporary=fs.mkdtempSync(path.join(os.tmpdir(),'pengucoach-map3d-'));
execFileSync(process.execPath,[require.resolve('typescript/bin/tsc'),'lib/map3d.ts','--module','commonjs','--target','ES2022','--skipLibCheck','--outDir',temporary],{cwd:path.resolve(__dirname,'..')});
const M=require(path.join(temporary,'map3d.js'));
const E=require(path.join(temporary,'activityExplorer.js'));
after(()=>fs.rmSync(temporary,{recursive:true,force:true}));

// ~1.1 km straight north, 101 fixes, heart rate rising, then a GPS gap and a short eastward piece.
const samples=[];
for(let i=0;i<=100;i++)samples.push({elapsed_s:i*5,position_lat:47+i*0.0001,position_long:11,heart_rate:100+i,altitude_m:600+i});
const segments=[samples.map((s,i)=>({index:i,lat:s.position_lat,lon:s.position_long,sample:s}))];

test('tile sources need no API key',()=>{
  for(const source of Object.values(M.TILES))for(const url of source.tiles){
    assert.match(url,/^https:\/\//);assert.doesNotMatch(url,/key=|token=|access_token/i);assert.match(url,/\{z\}\/\{x\}\/\{y\}/);
  }
  assert.match(M.TILES.dem.tiles[0],/terrarium/);
});
test('distance and heading',()=>{
  const d=M.metres({lat:47,lon:11},{lat:47.01,lon:11});
  assert.ok(Math.abs(d-1112)<3,String(d));
  assert.ok(Math.abs(M.heading({lat:47,lon:11},{lat:47.01,lon:11}))<0.01);
  assert.ok(Math.abs(M.heading({lat:47,lon:11},{lat:47,lon:11.01})-90)<0.1);
});
test('along measures the route and positionAt interpolates',()=>{
  const route=M.along(segments);
  assert.equal(route.points.length,101);
  assert.ok(Math.abs(route.total-1112)<3);
  const middle=M.positionAt(route,route.total/2);
  assert.ok(Math.abs(middle.lat-47.005)<1e-6);assert.equal(middle.index,50);
  assert.equal(M.positionAt(route,-10).index,0);
  assert.equal(M.positionAt(route,1e9).index,100);
  assert.equal(M.positionAt(M.along([]),5),null);
});
test('gaps between segments are not counted as distance',()=>{
  const a=segments[0].slice(0,11),b=segments[0].slice(90).map(p=>({...p,lon:p.lon+0.5}));
  const route=M.along([a,b]);
  assert.ok(route.total<300,String(route.total));
});
test('camera looks ahead along the route and turns smoothly',()=>{
  const route=M.along(segments);
  assert.ok(Math.abs(M.lookAhead(route,100,300))<0.01);
  assert.ok(M.lookAhead(route,route.total,300)<0.01||M.lookAhead(route,route.total,300)>359.99,'at the end it keeps the last direction');
  assert.equal(M.turnTowards(350,10,5),355);
  assert.equal(M.turnTowards(10,350,5),5);
  assert.equal(M.turnTowards(0,2,5),2);
  assert.equal(M.turnTowards(0,180,5),355);
});
test('coloured route merges bands and marks missing values',()=>{
  const metric=E.METRICS.find(m=>m.key==='heart_rate');
  const lines=M.colouredRoute(segments,samples,metric,'#2d806b');
  assert.ok(lines.features.length>=5&&lines.features.length<=12,String(lines.features.length));
  assert.equal(lines.features[0].properties.color,M.ROUTE_COLORS[0]);
  assert.equal(lines.features.at(-1).properties.color,M.ROUTE_COLORS.at(-1));
  const joined=lines.features.reduce((sum,f)=>sum+f.geometry.coordinates.length-1,0);
  assert.equal(joined,100,'every piece of the route is drawn exactly once');
  const single=M.colouredRoute(segments,samples,null,'#123456');
  assert.equal(single.features.length,1);assert.equal(single.features[0].properties.color,'#123456');
  const holes=samples.map((s,i)=>i>=40&&i<=60?{...s,heart_rate:null}:s);
  const withGap=M.colouredRoute([holes.map((s,i)=>({index:i,lat:s.position_lat,lon:s.position_long,sample:s}))],holes,metric,'#000');
  assert.ok(withGap.features.some(f=>f.properties.gap&&f.properties.color===M.GAP_COLOR));
});
test('hover finds the nearest point on the drawn line',()=>{
  const project=(lon,lat)=>({x:(lon-11)*100000,y:(47.01-lat)*100000});
  assert.equal(M.nearestOnScreen(segments,project,3,500,40),50);
  assert.equal(M.nearestOnScreen(segments,project,200,500,40),-1);
  assert.equal(M.nearestOnScreen(segments,project,0,1000,40),0);
});
test('first view faces along the tour',()=>{
  const route=M.along(segments);
  assert.ok(Math.abs(M.mainHeading(route.points))<0.01);
  assert.equal(M.mainHeading([]),0);
});
