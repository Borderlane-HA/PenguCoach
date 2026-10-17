const {test,after}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const os=require('node:os');
const path=require('node:path');
const {execFileSync}=require('node:child_process');
const temporary=fs.mkdtempSync(path.join(os.tmpdir(),'pengucoach-number-input-'));
execFileSync(process.execPath,[require.resolve('typescript/bin/tsc'),'lib/numberInput.ts','--module','commonjs','--target','ES2022','--skipLibCheck','--outDir',temporary],{cwd:path.resolve(__dirname,'..')});
const {parseNumberDraft,validNumberDraft,normalizeNumberDraft}=require(path.join(temporary,'numberInput.js'));
after(()=>fs.rmSync(temporary,{recursive:true,force:true}));

test('clearing a required value stays a draft; an entered 2 is accepted for weeks and training days',()=>{
  for(const max of [7,24]){
    const limits={min:1,max};
    assert.equal(validNumberDraft('',limits),false);
    assert.equal(normalizeNumberDraft('','4',limits),'4');
    assert.equal(validNumberDraft('2',limits),true);
    assert.equal(normalizeNumberDraft('2','4',limits),'2');
  }
});
test('typing 8000 or 32768 only accepts complete in-range values without filling minimums',()=>{
  const limits={min:128,max:65536};
  assert.deepEqual(['','8','80','800','8000'].map(v=>validNumberDraft(v,limits)),[false,false,false,true,true]);
  assert.equal(normalizeNumberDraft('8000','4500',limits),'8000');
  assert.equal(normalizeNumberDraft('32768','8192',{min:2048,max:131072,step:1024}),'32768');
  assert.equal(validNumberDraft('8000',{min:2048,max:131072,step:1024}),true,'context step is a keyboard increment, not a rounding rule');
});
test('German commas and decimal points retain fractional body values, prices and intervals',()=>{
  for(const [raw,result] of [['75,5',75.5],['75.5',75.5],[',75',.75],['0,',0],[' 0,0001 ',.0001]])assert.equal(parseNumberDraft(raw),result);
  assert.equal(validNumberDraft('0,75',{min:.25,step:.25}),true);
  assert.equal(normalizeNumberDraft('0,75','1',{min:.25,step:.25}),'0.75');
  assert.equal(normalizeNumberDraft('0.30000000000000004','0',{min:0,step:.1}),'0.3');
  assert.equal(normalizeNumberDraft('0,0001','0',{min:0,step:.0001}),'0.0001');
});
test('blank optional values and zero remain distinct',()=>{
  const limits={min:0,step:.01,allowEmpty:true};
  assert.equal(validNumberDraft('',limits),true);
  assert.equal(normalizeNumberDraft('','20',limits),'');
  assert.equal(normalizeNumberDraft('0','20',limits),'0');
  assert.equal(validNumberDraft('0',{min:0,max:480}),true);
});
test('limits apply on commit and non-numbers never reach the numeric state',()=>{
  const limits={min:1,max:24};
  assert.equal(validNumberDraft('25',limits),false);
  assert.equal(normalizeNumberDraft('25','8',limits),'24');
  assert.equal(normalizeNumberDraft('-2','8',limits),'1');
  assert.equal(validNumberDraft('2.5',limits),false);
  assert.equal(normalizeNumberDraft('2.5','8',limits),'3');
  for(const raw of ['-','.',',','1,2.3','1e999','Infinity','NaN','abc']){
    assert.equal(parseNumberDraft(raw),null);
    assert.equal(validNumberDraft(raw,limits),false);
    assert.equal(normalizeNumberDraft(raw,'8',limits),'8');
  }
});
