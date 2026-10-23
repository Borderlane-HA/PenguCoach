const {test,after}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const os=require('node:os');
const path=require('node:path');
const {execFileSync}=require('node:child_process');
const temporary=fs.mkdtempSync(path.join(os.tmpdir(),'pengucoach-api-'));
execFileSync(process.execPath,[require.resolve('typescript/bin/tsc'),'lib/api.ts','--module','commonjs','--target','ES2022','--skipLibCheck','--outDir',temporary],{cwd:path.resolve(__dirname,'..')});
const {api,ApiError}=require(path.join(temporary,'api.js'));
const originalFetch=global.fetch,originalWindow=global.window;
after(()=>{global.fetch=originalFetch;global.window=originalWindow;fs.rmSync(temporary,{recursive:true,force:true})});

test('proxy and server errors retain their status without expiring the session',async()=>{
  const events=[];global.window={dispatchEvent:event=>events.push(event.type)};
  for(const status of [403,500,502,503,504]){
    global.fetch=async()=>new Response('<html>Unavailable</html>',{status});
    await assert.rejects(api('/auth/me'),error=>error instanceof ApiError&&error.status===status&&error.message===`HTTP ${status}`);
  }
  assert.deepEqual(events,[]);
});
test('network errors and request cancellation do not expire the session',async()=>{
  const events=[];global.window={dispatchEvent:event=>events.push(event.type)};
  for(const error of [new TypeError('Failed to fetch'),new DOMException('Aborted','AbortError')]){
    global.fetch=async()=>{throw error};
    await assert.rejects(api('/auth/me'),actual=>actual===error);
  }
  assert.deepEqual(events,[]);
});
test('a genuine 401 expires protected sessions; failed login remains on its form',async()=>{
  const events=[];global.window={dispatchEvent:event=>events.push(event.type)};
  global.fetch=async()=>Response.json({detail:'SESSION_EXPIRED'},{status:401});
  await assert.rejects(api('/auth/me'),error=>error.status===401&&error.message==='SESSION_EXPIRED');
  assert.deepEqual(events,['pengucoach-session-expired']);
  events.length=0;
  await assert.rejects(api('/auth/login',{method:'POST'}),error=>error.status===401);
  assert.deepEqual(events,[]);
});
test('successful reads keep credentials and cancellation; only mutations invalidate data',async()=>{
  const events=[],controller=new AbortController();let request;
  global.window={dispatchEvent:event=>events.push(event.type)};
  global.fetch=async(url,init)=>{request={url,...init};return Response.json({id:'athlete'})};
  assert.deepEqual(await api('/auth/me',{signal:controller.signal}),{id:'athlete'});
  assert.equal(request.credentials,'include');assert.equal(request.signal,controller.signal);
  assert.deepEqual(events,[]);
  await api('/settings/appearance',{method:'PUT',body:'{}'});
  assert.deepEqual(events,['pengucoach-data-changed']);
});
test('maintenance mode becomes a readable message without expiring the session',async()=>{
  const events=[];global.window={dispatchEvent:event=>events.push(event.type)};
  global.fetch=async()=>Response.json({detail:'MAINTENANCE_ACTIVE'},{status:503});
  await assert.rejects(api('/settings/appearance',{method:'PUT',body:'{}'}),error=>error.status===503&&/Systemwartung/.test(error.message));
  global.localStorage={getItem:()=> 'en'};
  await assert.rejects(api('/settings/appearance',{method:'PUT',body:'{}'}),error=>/maintenance is in progress/.test(error.message));
  delete global.localStorage;
  assert.deepEqual(events,[]);
});
