const {test,after}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const os=require('node:os');
const path=require('node:path');
const {execFileSync}=require('node:child_process');
const temporary=fs.mkdtempSync(path.join(os.tmpdir(),'pengucoach-theme-'));
execFileSync(process.execPath,[require.resolve('typescript/bin/tsc'),'lib/theme.ts','--module','commonjs','--target','ES2022','--skipLibCheck','--outDir',temporary],{cwd:path.resolve(__dirname,'..')});
const {customThemeVars,contrast,DEFAULT_CUSTOM,applyAppearance,themeBoot}=require(path.join(temporary,'theme.js'));
after(()=>fs.rmSync(temporary,{recursive:true,force:true}));

test('custom palettes keep text, muted labels and accent readable even for extreme user colors',()=>{
 const colors=['#ffffff','#000000','#ff00ff','#ffff00','#10cfff','#777777'];
 for(const mode of ['light','dark'])for(const background of colors)for(const surface of colors)for(const accent of colors){
  const vars=customThemeVars({mode,background,surface,accent});
  for(const foreground of ['--text','--muted','--accent','--danger','--blue','--violet'])for(const panel of ['--bg','--panel','--panel2','--accent-soft','--accent-pale'])assert.ok(contrast(vars[foreground],vars[panel])>=4.5,JSON.stringify({mode,background,surface,accent,foreground,panel}));
  assert.ok(contrast(vars['--accent'],vars['--primary-ink'])>=4.5);
 }
});
test('invalid color drafts produce a usable preview without injecting CSS',()=>{
 const vars=customThemeVars({...DEFAULT_CUSTOM,accent:'red;url(test)',surface:'#xyz'});
 assert.ok(Object.values(vars).every(v=>/^#[0-9a-f]{6}$/i.test(v)));
});
test('custom appearance survives first paint; switching to a preset clears custom overrides',()=>{
 const storage=new Map(),values=new Map(),style={setProperty:(k,v)=>values.set(k,v),removeProperty:k=>values.delete(k)};
 global.document={documentElement:{dataset:{},style}};global.localStorage={setItem:(k,v)=>storage.set(k,v),getItem:k=>storage.get(k)};
 applyAppearance({theme:'custom',custom_theme:{...DEFAULT_CUSTOM,mode:'dark',background:'#101722',surface:'#1b2636'}});
 const expected=values.get('--accent');
 values.clear();document.documentElement.dataset={};
 eval(themeBoot);
 assert.equal(document.documentElement.dataset.theme,'custom');assert.equal(document.documentElement.dataset.colorMode,'dark');assert.equal(values.get('--accent'),expected);
 applyAppearance({theme:'alpine'});
 assert.equal(document.documentElement.dataset.theme,'alpine');assert.equal(values.size,0);assert.equal(document.documentElement.dataset.colorMode,undefined);
 delete global.document;delete global.localStorage;
});
