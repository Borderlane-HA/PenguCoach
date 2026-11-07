// alpha.86: MapLibre GL 6 starts its tile worker from a separate module file.
// Next.js does not bundle that file, so it is copied to public/vendor at build time
// and the 3D map points MapLibre at /vendor/maplibre-gl-worker.mjs.
import {copyFileSync,mkdirSync,existsSync} from "node:fs";
import {dirname,join} from "node:path";
import {createRequire} from "node:module";
import {fileURLToPath} from "node:url";

const here=dirname(fileURLToPath(import.meta.url));
const require=createRequire(import.meta.url);
let source;
try{source=join(dirname(require.resolve("maplibre-gl/package.json")),"dist","maplibre-gl-worker.mjs")}
catch{source=join(here,"..","node_modules","maplibre-gl","dist","maplibre-gl-worker.mjs")}
const target=join(here,"..","public","vendor","maplibre-gl-worker.mjs");
if(!existsSync(source)){
  console.warn(`[maplibre] worker not found at ${source} – the 3D map will fall back to the standard map.`);
  process.exit(0);
}
mkdirSync(dirname(target),{recursive:true});
copyFileSync(source,target);
console.log(`[maplibre] worker copied to public/vendor/`);
