const {test,after}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const os=require('node:os');
const path=require('node:path');
const {execFileSync}=require('node:child_process');
const temporary=fs.mkdtempSync(path.join(os.tmpdir(),'pengucoach-garmin-auth-'));
execFileSync(process.execPath,[require.resolve('typescript/bin/tsc'),'lib/garminAuth.ts','--module','commonjs','--target','ES2022','--skipLibCheck','--outDir',temporary],{cwd:path.resolve(__dirname,'..')});
const G=require(path.join(temporary,'garminAuth.js'));
after(()=>fs.rmSync(temporary,{recursive:true,force:true}));

test('pasted keys lose whitespace and auth prefixes',()=>{
  assert.equal(G.cleanKey('  ApiKey abc.def\n ghi '),'abc.defghi');
  assert.equal(G.cleanKey('Bearer xyz'),'xyz');
  assert.equal(G.cleanKey('plain'),'plain');
});

test('expiry presets clamp to the end of short months',()=>{
  assert.equal(G.addMonths(new Date(2026,0,31,12),1),'2026-02-28');
  assert.equal(G.addMonths(new Date(2026,9,23,12),12),'2027-10-23');
  assert.equal(G.addMonths(new Date(2026,9,23,12),0),'2026-10-23');
});

test('key status escalates near and after expiry',()=>{
  assert.equal(G.keyStatus({key_hint:'…abcd',days_left:null},'de').level,'info');
  assert.equal(G.keyStatus({key_hint:'…abcd',days_left:90,expires_on:'2027-01-21'},'de').level,'ok');
  const soon=G.keyStatus({key_hint:'…abcd',days_left:1,expires_on:'2026-10-24'},'de');
  assert.equal(soon.level,'warn');assert.match(soon.text,/morgen/);
  assert.equal(G.keyStatus({key_hint:'…abcd',days_left:-2,expires_on:'2026-10-21'},'en').level,'error');
});

test('error codes become readable text',()=>{
  assert.match(G.garminError('GARMIN_API_KEY_REJECTED','de'),/abgelehnt/);
  assert.match(G.garminError('GARMIN_API_HTTP_503','en'),/HTTP 503/);
  assert.equal(G.garminError('SOMETHING_ELSE','de'),'SOMETHING_ELSE');
});

test('feature comparison marks read-only gaps of the Personal API',()=>{
  const missing=G.CAPABILITIES.filter(c=>!c.personal).map(c=>c.key);
  assert.deepEqual(missing,['training']);
  assert.equal(G.CAPABILITIES.find(c=>c.key==='export').personal,'optional');
  assert.ok(G.CAPABILITIES.every(c=>c.password));
});

test('features are greyed out only for an active API-only connection',()=>{
  const api={auth_mode:'personal_api',connected:true,export_login:{connected:false}};
  assert.equal(G.featureUnavailable(api,'training_readiness'),true);
  assert.equal(G.featureUnavailable(api,'workout_export'),true);
  assert.equal(G.featureUnavailable({...api,export_login:{connected:true}},'workout_export'),false);
  assert.equal(G.featureUnavailable({...api,export_login:{connected:true}},'power_zones'),true);
  assert.equal(G.featureUnavailable({auth_mode:'password',connected:true},'training_readiness'),false);
  assert.equal(G.featureUnavailable({auth_mode:'personal_api',connected:false},'training_readiness'),false);
  assert.equal(G.featureUnavailable(null,'power_zones'),false);
  assert.match(G.featureHint('power_zones','de'),/Leistungszonen/);
  assert.match(G.featureHint('workout_export','en'),/export/);
});
