// alpha.88: build the public demo – static pages with recorded fake data – into out/.
// Used by .github/workflows/demo-pages.yml; locally: `npm run build:demo`.
import {cpSync,existsSync,mkdirSync,rmSync,writeFileSync} from "node:fs";
import {dirname,join} from "node:path";
import {fileURLToPath} from "node:url";
import {spawnSync} from "node:child_process";

const web=join(dirname(fileURLToPath(import.meta.url)),"..");
const data=join(web,"demo","data"),target=join(web,"public","demo-data");
if(!existsSync(join(data,"index.json"))){console.error("demo/data/index.json missing");process.exit(1)}
const env={...process.env,NEXT_PUBLIC_DEMO:"1",NEXT_PUBLIC_BASE_PATH:process.env.DEMO_BASE_PATH??"/PenguCoach",NEXT_TELEMETRY_DISABLED:"1"};
rmSync(target,{recursive:true,force:true});mkdirSync(target,{recursive:true});
cpSync(data,target,{recursive:true});
const run=(cmd,args)=>{const r=spawnSync(cmd,args,{cwd:web,env,stdio:"inherit",shell:process.platform==="win32"});if(r.status!==0)throw new Error(`${cmd} ${args.join(" ")} failed`)};
try{
  run(process.execPath,["scripts/copy-maplibre-worker.mjs"]);
  run(process.execPath,[join(web,"node_modules","next","dist","bin","next"),"build"]);
  // GitHub Pages must not run Jekyll over _next/.
  writeFileSync(join(web,"out",".nojekyll"),"");
  console.log(`[demo] ready in out/ (base path ${env.NEXT_PUBLIC_BASE_PATH||"/"})`);
}finally{rmSync(target,{recursive:true,force:true})}
