const {test,after}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');const os=require('node:os');const path=require('node:path');
const {execFileSync}=require('node:child_process');
const temporary=fs.mkdtempSync(path.join(os.tmpdir(),'pengucoach-races-'));
execFileSync(process.execPath,[require.resolve('typescript/bin/tsc'),'lib/races.ts','--module','commonjs','--target','ES2022','--skipLibCheck','--outDir',temporary],{cwd:path.resolve(__dirname,'..')});
const R=require(path.join(temporary,'races.js'));
after(()=>fs.rmSync(temporary,{recursive:true,force:true}));

test('target times are read the way people type them',()=>{
  assert.equal(R.parseDuration('1:50'),6600);
  assert.equal(R.parseDuration('1:50:30'),6630);
  assert.equal(R.parseDuration('48:30'),2910);
  assert.equal(R.parseDuration('105'),6300);
  assert.equal(R.parseDuration('1:75'),null);
  assert.equal(R.parseDuration('abc'),null);
  assert.equal(R.parseDuration(''),null);
});
test('durations format compactly',()=>{
  assert.equal(R.formatDuration(6600),'1:50:00');
  assert.equal(R.formatDuration(2910),'48:30');
  assert.equal(R.formatDuration(null),'—');
});
test('countdown wording',()=>{
  assert.equal(R.countdownText(0,'de'),'Heute ist Wettkampftag');
  assert.equal(R.countdownText(1,'en'),'Tomorrow is the day');
  assert.equal(R.countdownText(42,'de'),'noch 42 Tage');
});
test('a year heatmap has Monday-based weeks covering every day once',()=>{
  const weeks=R.yearWeeks(2026);
  const days=weeks.flat().filter(d=>d.inYear).map(d=>d.date);
  assert.equal(days.length,365);assert.equal(new Set(days).size,365);
  assert.equal(days[0],'2026-01-01');assert.equal(days.at(-1),'2026-12-31');
  assert.equal(weeks[0][0].date,'2025-12-29');
  for(const w of weeks)assert.equal(w.length,7);
});
test('month grid starts on Monday and ends on Sunday',()=>{
  const g=R.monthGrid(2026,10);
  assert.equal(g[0].date,'2026-10-26');assert.equal(g.at(-1).date,'2026-12-06');
  assert.equal(g.length%7,0);assert.equal(g.filter(d=>d.inMonth).length,30);
});
test('heatmap levels use the spread of the year',()=>{
  const lvl=R.levels([0,10,20,30,40,50,60,70,80,90,100]);
  assert.equal(lvl(0),0);assert.equal(lvl(10),1);assert.equal(lvl(100),4);
  assert.ok(lvl(50)>=2&&lvl(50)<=3);
  assert.equal(R.levels([])(5),1);
});
