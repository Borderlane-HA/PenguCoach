const {test,after}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');const os=require('node:os');const path=require('node:path');
const {execFileSync}=require('node:child_process');
const temporary=fs.mkdtempSync(path.join(os.tmpdir(),'pengucoach-tours-'));
execFileSync(process.execPath,[require.resolve('typescript/bin/tsc'),'lib/tours.ts','--module','commonjs','--target','ES2022','--skipLibCheck','--outDir',temporary],{cwd:path.resolve(__dirname,'..')});
const T=require(path.join(temporary,'tours.js'));
after(()=>fs.rmSync(temporary,{recursive:true,force:true}));

const coords=[];for(let i=0;i<=50;i++)coords.push([11.5+i*0.001,48.76,400+Math.sin(i/5)*30]);

test('GPX is valid 1.1 with every point, elevation and escaped names',()=>{
  const xml=T.gpx('Runde <Süd> & "Wald"',coords,'running','x');
  assert.match(xml,/^<\?xml version="1.0" encoding="UTF-8"\?>/);
  assert.match(xml,/<gpx version="1.1" creator="PenguCoach" xmlns="http:\/\/www.topografix.com\/GPX\/1\/1"/);
  assert.equal((xml.match(/<trkpt /g)||[]).length,51);
  assert.match(xml,/<trkpt lat="48.760000" lon="11.500000"><ele>400.0<\/ele><\/trkpt>/);
  assert.match(xml,/<name>Runde &lt;Süd&gt; &amp; &quot;Wald&quot;<\/name>/);
  assert.match(xml,/<type>running<\/type>/);
  const noEle=T.gpx('a',[[11,48,null],[11.1,48.1,null]]);
  assert.doesNotMatch(noEle,/<ele>/);
});
test('file names are safe',()=>{
  assert.equal(T.fileName('Rennrad Runde 49 km · Großweil'),'Rennrad-Runde-49-km-Grossweil.gpx');
  assert.equal(T.fileName('***'),'tour.gpx');
});
test('profile and samples follow the line',()=>{
  const p=T.profile(coords);
  assert.ok(Math.abs(p.total-3664)<15,String(p.total));
  const s=T.toSamples(coords);
  assert.equal(s.length,51);assert.equal(s[0].position_lat,48.76);assert.equal(s[0].altitude_m,400);
  assert.ok(s.at(-1).distance_km>3.6);
  const path=T.profilePath(coords,900,150,6);
  assert.ok(path.line.startsWith('M6.0,'));assert.ok(path.area.endsWith('Z'));
  assert.equal(T.profilePath([[1,1,null],[1.1,1,null]],100,50),null);
  const flat=T.profilePath([[1,1,100],[1.01,1,101]],100,50);
  assert.ok(flat.hi-flat.lo>=30,'flat tours do not look like mountains');
});
test('formatting and names',()=>{
  assert.equal(T.formatKm(49090),'49 km');assert.equal(T.formatKm(8400),'8.4 km');
  assert.equal(T.formatDuration(8269),'2:18 h');assert.equal(T.formatDuration(1800),'30 min');assert.equal(T.formatDuration(3599),'1:00 h');
  assert.equal(T.suggestName('trail_running',12.4,true,'Eichstätt',true),'Trailrun Runde 12 km · Eichstätt');
  assert.equal(T.suggestName('road_bike',80,false,'',false),'Road bike route 80 km');
});
test('every error and warning code has both languages',()=>{
  for(const table of [T.ERRORS,T.WARNINGS])for(const [k,v] of Object.entries(table)){assert.ok(v.de&&v.en,k)}
  assert.match(T.errorText('ROUTER_UNREACHABLE',true),/brouter\.de/);
  assert.match(T.errorText('SOMETHING',false),/SOMETHING/);
  assert.equal(T.SPORTS.length,7);
});
test('surface bar keeps a fixed order',()=>{
  const bar=T.surfaceBar({unpaved:.2,paved:.5,unknown:.3});
  assert.deepEqual(bar.map(b=>b.key),['paved','unpaved','unknown']);
});

test('editor helpers insert, move and remove waypoints',()=>{
  const pts=[[48,11],[48.1,11.1],[48.2,11],[48,11]];
  assert.deepEqual(T.insertWaypoint(pts,1,[48.15,11.2]),[[48,11],[48.1,11.1],[48.15,11.2],[48.2,11],[48,11]]);
  assert.deepEqual(T.insertWaypoint(pts,9,[1,1]).at(-1),[48,11],'the end point stays last');
  assert.deepEqual(T.removeWaypoint(pts,1),[[48,11],[48.2,11],[48,11]]);
  assert.equal(T.removeWaypoint(pts,0),pts,'start cannot be removed');
  const two=[[1,1],[2,2]];assert.equal(T.removeWaypoint(two,1),two,'two points always remain');
  assert.deepEqual(T.moveStart(pts,[47,10],true),[[47,10],[48.1,11.1],[48.2,11],[47,10]],'in a loop start and end move together');
  assert.deepEqual(T.moveStart(pts,[47,10],false).at(-1),[48,11]);
  const route=[[11,48,1],[11.05,48.05,1],[11.1,48.1,1],[11.05,48.15,1],[11,48.2,1]];
  assert.equal(T.nearestIndex(route,48.099,11.101),2);
  assert.equal(T.segmentOf([0,2],1),0);assert.equal(T.segmentOf([0,2],3),1);assert.equal(T.segmentOf([0,2],2),1);
  const wps=T.sampleWaypoints(route,4);assert.equal(wps.length,5);assert.deepEqual(wps[0],[48,11]);assert.deepEqual(wps.at(-1),[48.2,11]);
});
