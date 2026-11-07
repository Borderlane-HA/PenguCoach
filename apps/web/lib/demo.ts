// alpha.88: public demo (GitHub Pages). There is no server: API calls are answered
// from recorded fake data in /demo-data. Dates move with the calendar so the demo
// always looks current; changes stay in this browser tab only.
import {withBase} from "./basePath";

type Index={recorded:string;entries:Record<string,string>;paths:Record<string,string[]>};
const API_PREFIX=(process.env.NEXT_PUBLIC_API_BASE_URL??"/api/v1").replace(/\/$/,"");
let index:Promise<Index>|null=null;
const bundles=new Map<string,Promise<Record<string,unknown>>>();
const overrides=new Map<string,unknown>();
const DATE=/^(\d{4})-(\d{2})-(\d{2})(?=$|[T ])/;

function lang(){try{return localStorage.getItem("pengucoach_lang")==="en"?"en":"de"}catch{return "de"}}
export const DEMO_READ_ONLY={de:"Das ist die Demo mit erfundenen Daten – Änderungen werden hier nicht gespeichert. Installiere PenguCoach selbst, um es mit deinen Daten zu nutzen.",en:"This is the demo with made-up data – changes are not saved here. Install PenguCoach yourself to use it with your data."};

/** Whole weeks between the recording day and today, so weekdays stay the same. */
export function shiftDays(recorded:string,today=new Date()){
  const [y,m,d]=recorded.split("-").map(Number);
  const a=Date.UTC(y,m-1,d),b=Date.UTC(today.getFullYear(),today.getMonth(),today.getDate());
  return Math.round((b-a)/86400000/7)*7;
}
export function shiftDate(value:string,days:number){
  if(!days)return value;
  const m=DATE.exec(value);if(!m)return value;
  const t=new Date(Date.UTC(+m[1],+m[2]-1,+m[3])+days*86400000);
  return `${t.getUTCFullYear()}-${String(t.getUTCMonth()+1).padStart(2,"0")}-${String(t.getUTCDate()).padStart(2,"0")}`+value.slice(10);
}
export function shiftAll(value:unknown,days:number):unknown{
  if(!days)return value;
  if(typeof value==="string")return shiftDate(value,days);
  if(Array.isArray(value))return value.map(v=>shiftAll(v,days));
  if(value&&typeof value==="object"){const out:Record<string,unknown>={};for(const [k,v] of Object.entries(value))out[shiftDate(k,days)]=shiftAll(v,days);return out}
  return value;
}
/** Normalised lookup key: path plus sorted query, with dates moved back to the recording. */
export function keyFor(pathname:string,search:string,days:number){
  const params=[...new URLSearchParams(search).entries()].map(([k,v])=>[k,shiftDate(v,-days)] as [string,string]).sort(([a],[b])=>a<b?-1:a>b?1:0);
  const q=new URLSearchParams(params).toString();
  return q?`${pathname}?${q}`:pathname;
}

async function load(){
  if(!index)index=window.__pengucoachFetch(withBase("/demo-data/index.json")).then(r=>r.json());
  return index;
}
const json=(body:unknown,status=200)=>new Response(JSON.stringify(body),{status,headers:{"Content-Type":"application/json"}});

async function answer(url:URL,init:RequestInit|undefined):Promise<Response>{
  const data=await load();
  const days=shiftDays(data.recorded);
  const path=url.pathname.slice(url.pathname.indexOf(API_PREFIX)+API_PREFIX.length)||"/";
  const method=(init?.method??"GET").toUpperCase();
  const read=async(key:string)=>{
    if(overrides.has(key))return overrides.get(key);
    const file=data.entries[key];
    if(!file)return undefined;
    // Fixtures come in a few bundles (core + activity groups); each is loaded once.
    if(!bundles.has(file))bundles.set(file,window.__pengucoachFetch(withBase(`/demo-data/${file}`)).then(r=>r.json()));
    const bundle=await bundles.get(file)!;
    return key in bundle?shiftAll(bundle[key],days):undefined;
  };
  const exact=keyFor(path,url.search,days);
  if(method==="GET"||method==="HEAD"){
    let body=await read(exact);
    if(body===undefined&&data.paths[path]?.length)body=await read(data.paths[path][0]);
    return body===undefined?json({detail:"DEMO_NOT_AVAILABLE"},404):json(body);
  }
  const recorded=await read(`${method} ${exact}`)??await read(`${method} ${path}`);
  if(recorded!==undefined)return json(recorded);
  if(path==="/auth/logout"||path==="/auth/safety-notice/accept")return json({ok:true,accepted:true});
  // Settings forms: keep the change for this tab so the page shows it.
  if((method==="PUT"||method==="PATCH")&&typeof init?.body==="string"){
    const current=await read(exact);
    if(current&&typeof current==="object"&&!Array.isArray(current)){
      try{const merged={...(current as object),...JSON.parse(init.body)};overrides.set(exact,merged);return json(merged)}catch{}
    }
  }
  return json({detail:DEMO_READ_ONLY[lang()]},403);
}

declare global{interface Window{__pengucoachFetch:typeof fetch;__pengucoachDemo?:boolean}}

export function installDemo(){
  if(typeof window==="undefined"||window.__pengucoachDemo)return;
  window.__pengucoachDemo=true;
  const original=window.fetch.bind(window);
  window.__pengucoachFetch=original;
  window.fetch=(input:RequestInfo|URL,init?:RequestInit)=>{
    const url=new URL(typeof input==="string"?input:input instanceof URL?input.href:input.url,window.location.href);
    if(url.origin===window.location.origin&&url.pathname.includes(API_PREFIX+"/"))return answer(url,init??(input instanceof Request?{method:input.method}:undefined));
    return original(input as RequestInfo,init);
  };
}
