"use client";
import {useCallback,useEffect,useMemo,useRef,useState} from "react";
import {api} from "../lib/api";
import {bi,type Lang} from "../lib/i18n";
import {renderPng} from "./ActivityShowcase";
import {PERIODS,type O,type Period,type Slide,calendar,compact,distanceFact,easeOut,elevationFact,energyFact,fileName,format,hoursText,paceText,periodTitle,projectRoutes,slides as slidesOf,sportName,timeFact,weekGrid} from "../lib/recap";

const FONT='Inter, ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif';
const DURATION:Partial<Record<Slide,number>>={intro:5200,map:8500,calendar:7500,highlights:8000};
const PREF="pengucoach_recap_period";
const reducedMotion=()=>typeof window!=="undefined"&&window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

export function CountUp({value,digits=0,lang,duration=1500,compactLarge=false}:{value:number;digits?:number;lang:Lang;duration?:number;compactLarge?:boolean}){
 const[shown,setShown]=useState(()=>reducedMotion()?value:0);
 useEffect(()=>{if(reducedMotion()){setShown(value);return}let frame=0;const begin=performance.now();const step=(now:number)=>{const t=easeOut((now-begin)/duration);setShown(value*t);if(t<1)frame=requestAnimationFrame(step)};frame=requestAnimationFrame(step);return()=>cancelAnimationFrame(frame)},[value,duration]);
 return <>{compactLarge&&value>=1e6?compact(shown,lang):format(shown,digits,lang)}</>;
}

const SPORT_COLORS:Record<string,string>={run:"#58f0c2",ride:"#7cc8ff",swim:"#5ad1ff",walk:"#d8f25a",hike:"#ffad4d",strength:"#ff8fa3",other:"#c9b8ff"};

export function RecapCard({data,lang,svgRef}:{data:O;lang:Lang;svgRef?:React.Ref<SVGSVGElement>}){
 const w=1080,h=1350,t=data.totals??{},de=lang==="de";
 const routes=useMemo(()=>projectRoutes(data.routes??[],{x:96,y:720,w:888,h:430}),[data]);
 const cells=calendar(data.series);
 const tiles:[string,string,string][]=[];
 tiles.push([de?"AKTIVITÄTEN":"ACTIVITIES",format(t.count,0,lang),""]);
 if(t.distance_m>0)tiles.push([de?"STRECKE":"DISTANCE",compact(t.distance_m/1000,lang),"km"]);
 if(t.elevation_m>0)tiles.push([de?"HÖHENMETER":"ELEVATION",format(t.elevation_m,0,lang),"m"]);
 if(t.duration_s>0)tiles.push([de?"ZEIT":"TIME",format(t.duration_s/3600,t.duration_s>=36000?0:1,lang),"h"]);
 if(t.calories>0)tiles.push([de?"ENERGIE":"ENERGY",compact(t.calories,lang),"kcal"]);
 if(data.period!=="today")tiles.push([de?"AKTIVE TAGE":"ACTIVE DAYS",format(data.active_days,0,lang),""]);
 const range=data.start&&data.start!==data.end?`${new Date(`${data.start}T12:00:00`).toLocaleDateString(de?"de-DE":"en-GB")} – ${new Date(`${data.end}T12:00:00`).toLocaleDateString(de?"de-DE":"en-GB")}`:new Date(`${data.end}T12:00:00`).toLocaleDateString(de?"de-DE":"en-GB");
 return <svg ref={svgRef} xmlns="http://www.w3.org/2000/svg" width={w} height={h} viewBox={`0 0 ${w} ${h}`} fontFamily={FONT} role="img" aria-label={periodTitle(data.period,data.start,lang)}>
  <defs><linearGradient id="rc-bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stopColor="#07130f"/><stop offset="1" stopColor="#12382f"/></linearGradient><filter id="rc-glow" x="-10%" y="-10%" width="120%" height="120%"><feGaussianBlur stdDeviation="6"/></filter><clipPath id="rc-clip"><rect x="96" y="700" width="888" height="470" rx="24"/></clipPath></defs>
  <rect width={w} height={h} fill="url(#rc-bg)"/>
  <circle cx={w*.88} cy={h*.06} r={w*.4} fill="#58f0c2" opacity=".07"/><circle cx={w*.04} cy={h*.95} r={w*.34} fill="#7cc8ff" opacity=".06"/>
  <text x="96" y="132" fontSize="24" fontWeight="800" letterSpacing="5" fill="#58f0c2">{de?"PENGUCOACH RÜCKBLICK":"PENGUCOACH RECAP"}</text>
  <text x="96" y="208" fontSize="66" fontWeight="800" letterSpacing="-2" fill="#f2f8f5">{periodTitle(data.period,data.start,lang)}</text>
  <text x="96" y="256" fontSize="28" fill="#9db8ae">{range}</text>
  {tiles.slice(0,6).map(([label,value,unit],i)=>{const x=96+(i%3)*300,y=330+Math.floor(i/3)*170,size=Math.min(64,270/((value.length+unit.length*.45)*.6));return <g key={label}><text x={x} y={y} fontSize="21" fontWeight="800" letterSpacing="3" fill="#9db8ae">{label}</text><text x={x} y={y+76} fontSize={size} fontWeight="800" letterSpacing="-2" fill="#f2f8f5">{value}{unit&&<tspan fontSize={Math.min(27,size*.45)} fill="#9db8ae" dx="8">{unit}</tspan>}</text></g>})}
  {routes.length>0?<g fill="none" strokeLinecap="round" strokeLinejoin="round" clipPath="url(#rc-clip)"><g filter="url(#rc-glow)" opacity=".5">{routes.map(r=><path key={`g${r.id}`} d={r.d} stroke="#58f0c2" strokeWidth="5"/>)}</g>{routes.map(r=><path key={r.id} d={r.d} stroke="#c8fff0" strokeWidth={routes.length>40?1.6:3} opacity={routes.length>40?.55:.9}/>)}</g>
   :cells.length>1?<g>{(()=>{const cols=data.series?.granularity==="month"?Math.min(cells.length,60):cells.length>40?53:7;const grid=cols===53?weekGrid(cells).flatMap((week,wi)=>week.map((c,di)=>c?{...c,x:wi,y:di}:null)).filter(Boolean) as O[]:cells.map((c,i)=>({...c,x:i%cols,y:Math.floor(i/cols)}));const size=Math.min(888/(cols===53?53:cols),cols===53?16:96);return grid.map((c:O)=><rect key={c.key} x={96+c.x*size} y={740+c.y*size} width={size-4} height={size-4} rx={size/5} fill={["rgba(255,255,255,.07)","#1f6b55","#2fa37f","#4fd8a9","#58f0c2"][c.level]}/>)})()}</g>:null}
  <text x="96" y="1268" fontSize="28" fontWeight="800" fill="#f2f8f5">PenguCoach</text>
  <text x={w-96} y="1268" textAnchor="end" fontSize="22" fill="#9db8ae">{de?`${routes.length?`${routes.length} ${routes.length===1?"Strecke":"Strecken"} · `:""}Training & Health`:`${routes.length?`${routes.length} ${routes.length===1?"route":"routes"} · `:""}Training & Health`}</text>
 </svg>;
}

export default function ActivityRecap({lang,query,source}:{lang:Lang;query?:string;source?:string}){
 const de=lang==="de";
 const[open,setOpen]=useState(false),[period,setPeriod]=useState<Period>("month"),[data,setData]=useState<O|null>(null),[loading,setLoading]=useState(false),[error,setError]=useState("");
 const[index,setIndex]=useState(0),[paused,setPaused]=useState(false),[progress,setProgress]=useState(0),[busy,setBusy]=useState(false),[status,setStatus]=useState("");
 const opener=useRef<HTMLButtonElement>(null),closer=useRef<HTMLButtonElement>(null),cardRef=useRef<SVGSVGElement>(null);
 const list=slidesOf(data),slide=list[Math.min(index,Math.max(0,list.length-1))];
 useEffect(()=>{try{const v=localStorage.getItem(PREF);if(PERIODS.some(p=>p.id===v))setPeriod(v as Period)}catch{}},[]);
 useEffect(()=>{
  if(!open)return;let active=true;const controller=new AbortController();
  setLoading(true);setError("");setIndex(0);setProgress(0);setStatus("");elapsed.current=0;
  const params=new URLSearchParams({period});if(query)params.set("q",query);if(source&&source!=="all")params.set("source",source);
  api<O>(`/activities/recap?${params}`,{signal:controller.signal}).then(v=>{if(active)setData(v)}).catch(e=>{if(active&&e?.name!=="AbortError")setError(e instanceof Error?e.message:String(e))}).finally(()=>{if(active)setLoading(false)});
  try{localStorage.setItem(PREF,period)}catch{}
  return()=>{active=false;controller.abort()};
 },[open,period,query,source]);
 const elapsed=useRef(0);
 const go=useCallback((delta:number)=>{elapsed.current=0;setProgress(0);setIndex(i=>Math.max(0,Math.min(list.length-1,i+delta)))},[list.length]);
 // Story timing: the progress bar fills, then the next slide starts. The finale waits.
 useEffect(()=>{
  if(!open||!slide||slide==="finale"||paused||loading)return;
  let frame=0,last=performance.now();const total=DURATION[slide]??6500;
  const step=(now:number)=>{elapsed.current+=(now-last)/total;last=now;if(elapsed.current>=1){go(1);return}setProgress(elapsed.current);frame=requestAnimationFrame(step)};
  frame=requestAnimationFrame(step);return()=>cancelAnimationFrame(frame);
 },[open,slide,paused,loading,go]);
 useEffect(()=>{
  if(!open)return;closer.current?.focus();document.body.style.overflow="hidden";
  const key=(e:KeyboardEvent)=>{if(e.key==="Escape")setOpen(false);else if(e.key==="ArrowRight")go(1);else if(e.key==="ArrowLeft")go(-1);else if(e.key===" "&&!(e.target instanceof HTMLButtonElement)){e.preventDefault();setPaused(p=>!p)}};
  const hidden=()=>{if(document.visibilityState!=="visible")setPaused(true)};
  document.addEventListener("keydown",key);document.addEventListener("visibilitychange",hidden);
  return()=>{document.removeEventListener("keydown",key);document.removeEventListener("visibilitychange",hidden);document.body.style.overflow="";opener.current?.focus()};
 },[open,go]);
 async function image(){if(!cardRef.current)throw new Error("NO_CARD");return renderPng(cardRef.current,1080,1350)}
 async function save(){setBusy(true);setStatus("");try{const blob=await image(),url=URL.createObjectURL(blob),a=document.createElement("a");a.href=url;a.download=fileName(period,data?.end);document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),2000);setStatus(bi(lang,"Bild gespeichert.","Image saved."))}catch{setStatus(bi(lang,"Das Bild konnte nicht erstellt werden.","The image could not be created."))}finally{setBusy(false)}}
 const canShare=typeof navigator!=="undefined"&&typeof navigator.canShare==="function";
 async function share(){setBusy(true);setStatus("");try{const file=new File([await image()],fileName(period,data?.end),{type:"image/png"});if(navigator.canShare?.({files:[file]}))await navigator.share({files:[file],title:"PenguCoach"});else setStatus(bi(lang,"Teilen wird nicht unterstützt – speichere das Bild stattdessen.","Sharing is not supported – save the image instead."))}catch(e){if(!(e instanceof DOMException&&e.name==="AbortError"))setStatus(bi(lang,"Teilen ist fehlgeschlagen.","Sharing failed."))}finally{setBusy(false)}}
 function stageClick(e:React.MouseEvent<HTMLDivElement>){
  if((e.target as HTMLElement).closest("button,a,input,select"))return;
  const r=e.currentTarget.getBoundingClientRect();go(e.clientX-r.left<r.width*.3?-1:1);
 }
 const t=data?.totals??{};
 const previousLabel=period==="today"?bi(lang,"gestern","yesterday"):period==="week"?bi(lang,"Vorwoche","last week"):period==="month"?bi(lang,"Vormonat","last month"):bi(lang,"Vorjahr","last year");

 function content(){
  if(loading&&!data)return <div className="recap-center"><span className="recap-loader" aria-hidden="true"/><p>{bi(lang,"Dein Rückblick wird zusammengestellt …","Putting your recap together …")}</p></div>;
  if(error)return <div className="recap-center"><p>{error}</p></div>;
  if(!data||!list.length)return <div className="recap-center"><h2 className="recap-title">{periodTitle(period,data?.start,lang)}</h2><p className="recap-sub">{bi(lang,"In diesem Zeitraum gibt es noch keine Aktivitäten. Wähle oben einen längeren Zeitraum.","No activities in this period yet. Pick a longer period above.")}</p></div>;
  switch(slide){
   case "intro":return <div className="recap-slide recap-intro"><span className="recap-eyebrow">{bi(lang,"PENGUCOACH RÜCKBLICK","PENGUCOACH RECAP")}</span><h2 className="recap-title">{periodTitle(period,data.start,lang)}</h2><div className="recap-hero"><CountUp value={t.count} lang={lang}/></div><p className="recap-label">{t.count===1?bi(lang,"Aktivität","activity"):bi(lang,"Aktivitäten","activities")}</p><p className="recap-sub recap-delay">{period!=="today"&&<>{bi(lang,"an","on")} <strong>{data.active_days}</strong> {data.active_days===1?bi(lang,"aktivem Tag","active day"):bi(lang,"aktiven Tagen","active days")} · </>}<strong>{data.sports.length}</strong> {data.sports.length===1?bi(lang,"Sportart","sport"):bi(lang,"Sportarten","sports")}</p></div>;
   case "distance":{const km=t.distance_m/1000,fact=distanceFact(km,lang),items=(data.series?.items??[]) as O[],max=Math.max(1,...items.map(i=>i.distance_m||0));
    return <div className="recap-slide"><span className="recap-eyebrow">{bi(lang,"STRECKE","DISTANCE")}</span><div className="recap-hero"><CountUp value={km} digits={km<100?1:0} lang={lang} compactLarge/><span className="recap-unit">km</span></div>{fact&&<p className="recap-fact recap-delay">{fact.text}</p>}{items.length>1&&<div className="recap-bars" aria-hidden="true">{items.map((i,n)=><i key={i.key} style={{height:`${Math.max(i.distance_m>0?6:2,i.distance_m/max*100)}%`,animationDelay:`${300+n*Math.min(40,1800/items.length)}ms`}}/>)}</div>}</div>}
   case "elevation":{const fact=elevationFact(t.elevation_m,lang)!;const fill=Math.min(1,fact.ratio);
    return <div className="recap-slide"><span className="recap-eyebrow">{bi(lang,"HÖHENMETER","ELEVATION GAIN")}</span><div className="recap-hero"><CountUp value={t.elevation_m} lang={lang}/><span className="recap-unit">m</span></div><p className="recap-fact recap-delay">{fact.text}</p><svg className="recap-mountain" viewBox="0 0 400 180" aria-hidden="true"><defs><clipPath id="recap-mountain-clip"><path d="M0 180 L120 70 L165 105 L240 18 L400 180 Z"/></clipPath></defs><path d="M0 180 L120 70 L165 105 L240 18 L400 180 Z" fill="rgba(255,255,255,.08)"/><rect className="recap-mountain-fill" x="0" y={180-fill*162} width="400" height={fill*162} fill="#58f0c2" clipPath="url(#recap-mountain-clip)" style={{transformOrigin:"0 180px"}}/><text x="240" y="12" textAnchor="middle" fontSize="12" fill="#9db8ae">{fact.mountain} · {format(fact.height,0,lang)} m</text></svg>{fact.ratio>1&&<p className="recap-sub recap-delay-2">{bi(lang,`Du hättest ihn ${format(Math.floor(fact.ratio),0,lang)}-mal komplett bestiegen.`,`You could have climbed it ${format(Math.floor(fact.ratio),0,lang)} times.`)}</p>}</div>}
   case "time":{const tf=timeFact(t.duration_s,lang),ef=energyFact(t.calories,lang);
    return <div className="recap-slide recap-split">{t.duration_s>0&&<div><span className="recap-eyebrow">{bi(lang,"IN BEWEGUNG","ON THE MOVE")}</span><div className="recap-hero recap-hero-md"><CountUp value={t.duration_s/3600} digits={t.duration_s>=36000?0:1} lang={lang}/><span className="recap-unit">h</span></div>{tf&&<p className="recap-fact recap-delay">{tf.text}</p>}</div>}{t.calories>0&&<div><span className="recap-eyebrow">{bi(lang,"VERBRANNT","BURNED")}</span><div className="recap-hero recap-hero-md"><CountUp value={t.calories} lang={lang} compactLarge/><span className="recap-unit">kcal</span></div>{ef&&<p className="recap-fact recap-delay">{ef.text}</p>}</div>}</div>}
   case "sports":{const max=Math.max(1,...data.sports.map((s:O)=>s.duration_s||s.count));
    return <div className="recap-slide"><span className="recap-eyebrow">{bi(lang,"DEIN MIX","YOUR MIX")}</span><h2 className="recap-title recap-title-sm">{bi(lang,"Wofür du unterwegs warst","How you moved")}</h2><div className="recap-sports">{data.sports.map((s:O,n:number)=><div key={s.sport} style={{animationDelay:`${200+n*180}ms`}}><span>{sportName(s.sport,lang)}</span><b><i style={{width:`${(s.duration_s||s.count)/max*100}%`,background:SPORT_COLORS[s.sport]??SPORT_COLORS.other,animationDelay:`${350+n*180}ms`}}/></b><small>{s.count}× {s.distance_m>0?`· ${compact(s.distance_m/1000,lang)} km `:""}{s.duration_s>0?`· ${hoursText(s.duration_s,lang)}`:""}</small></div>)}</div></div>}
   case "highlights":{const h=data.highlights??{};const cards:[string,string,O][]=[];
    if(h.longest_distance)cards.push([bi(lang,"Längste Einheit","Longest session"),`${compact(h.longest_distance.value/1000,lang)} km`,h.longest_distance]);
    if(h.biggest_climb)cards.push([bi(lang,"Größter Anstieg","Biggest climb"),`${format(h.biggest_climb.value,0,lang)} m`,h.biggest_climb]);
    if(h.fastest_run)cards.push([bi(lang,"Schnellster Lauf (ab 3 km)","Fastest run (3 km+)"),paceText(h.fastest_run.pace_s_per_km),h.fastest_run]);
    if(h.strongest_ride)cards.push([bi(lang,"Stärkste Radfahrt","Strongest ride"),`${format(h.strongest_ride.value,0,lang)} W Ø`,h.strongest_ride]);
    if(h.longest_duration&&!h.longest_distance)cards.push([bi(lang,"Längste Einheit","Longest session"),hoursText(h.longest_duration.value,lang),h.longest_duration]);
    return <div className="recap-slide"><span className="recap-eyebrow">HIGHLIGHTS</span><h2 className="recap-title recap-title-sm">{bi(lang,"Deine stärksten Momente","Your standout moments")}</h2><div className="recap-cards">{cards.map(([label,value,item],n)=><a key={label} href={`/activities/${item.id}`} style={{animationDelay:`${250+n*260}ms`}}><span>{label}</span><strong>{value}</strong><small>{item.name||sportName(item.sport,lang)} · {new Date(`${item.date}T12:00:00`).toLocaleDateString(de?"de-DE":"en-GB")}</small></a>)}</div></div>}
   case "map":{const routes=projectRoutes(data.routes,{x:10,y:10,w:780,h:580});
    return <div className="recap-slide"><span className="recap-eyebrow">{bi(lang,"DEINE STRECKEN","YOUR ROUTES")}</span><svg className="recap-map" viewBox="0 0 800 600" aria-label={bi(lang,`${routes.length} Strecken übereinander`,`${routes.length} routes overlaid`)}><clipPath id="recap-map-clip"><rect width="800" height="600"/></clipPath><g clipPath="url(#recap-map-clip)"><g filter="url(#recap-map-glow)" opacity=".6">{routes.map((r,n)=><path key={`g${r.id}`} d={r.d} pathLength={1} className="recap-route" style={{animationDelay:`${Math.min(n*60,3000)}ms`}} stroke="#58f0c2" strokeWidth="4"/>)}</g>{routes.map((r,n)=><path key={r.id} d={r.d} pathLength={1} className="recap-route" style={{animationDelay:`${Math.min(n*60,3000)}ms`}} stroke="#e6fff7" strokeWidth={routes.length>40?1.2:2.4} opacity={routes.length>40?.6:.95}/>)}</g><defs><filter id="recap-map-glow"><feGaussianBlur stdDeviation="5"/></filter></defs></svg><p className="recap-sub recap-delay-2">{bi(lang,`${routes.length} ${routes.length===1?"Strecke":"Strecken"} übereinander`,`${routes.length} ${routes.length===1?"route":"routes"} overlaid`)}{data.routes_limited?bi(lang," · die neuesten 300"," · newest 300"):""}</p></div>}
   case "calendar":{const cells=calendar(data.series),month=data.series?.granularity==="month",max=Math.max(1,...cells.map(c=>c.duration_s));
    return <div className="recap-slide"><span className="recap-eyebrow">{bi(lang,"DRANBLEIBEN","CONSISTENCY")}</span><h2 className="recap-title recap-title-sm">{data.streaks.longest>1?bi(lang,`${data.streaks.longest} Tage in Folge`,`${data.streaks.longest} days in a row`):bi(lang,`${data.active_days} aktive Tage`,`${data.active_days} active days`)}</h2>
     {month?<div className="recap-bars recap-bars-months" aria-hidden="true">{cells.map((c,n)=><i key={c.key} style={{height:`${Math.max(c.duration_s>0?6:2,c.duration_s/max*100)}%`,animationDelay:`${200+n*Math.min(50,2200/cells.length)}ms`}}/>)}</div>
      :cells.length>40?<div className="recap-year" aria-hidden="true">{weekGrid(cells).map((week,wi)=><div key={wi}>{week.map((c,di)=><i key={di} className={c?`l${c.level}`:"empty"} style={{animationDelay:`${200+wi*35}ms`}}/>)}</div>)}</div>
      :<div className="recap-days" aria-hidden="true">{cells.map((c,n)=><i key={c.key} className={`l${c.level}`} style={{animationDelay:`${200+n*70}ms`}}><span>{new Date(`${c.key}T12:00:00`).getDate()}</span></i>)}</div>}
     <p className="recap-sub recap-delay-2">{data.streaks.current>1?bi(lang,`Aktuelle Serie: ${data.streaks.current} Tage – weiter so!`,`Current streak: ${data.streaks.current} days – keep going!`):month?bi(lang,`${data.active_days} aktive Tage in ${cells.length} Monaten`,`${data.active_days} active days in ${cells.length} months`):bi(lang,`An ${data.active_days} von ${cells.length} Tagen aktiv`,`Active on ${data.active_days} of ${cells.length} days`)}</p></div>}
   case "compare":{const rows:[string,number|null,string][]=[[bi(lang,"Strecke","Distance"),data.change.distance_m,`${compact(t.distance_m/1000,lang)} km`],[bi(lang,"Zeit","Time"),data.change.duration_s,hoursText(t.duration_s,lang)],[bi(lang,"Höhenmeter","Elevation"),data.change.elevation_m,`${format(t.elevation_m,0,lang)} m`],[bi(lang,"Aktivitäten","Activities"),data.change.count,String(t.count)]];
    return <div className="recap-slide"><span className="recap-eyebrow">{bi(lang,"IM VERGLEICH","COMPARED")}</span><h2 className="recap-title recap-title-sm">{bi(lang,`gegenüber ${previousLabel}`,`vs. ${previousLabel}`)}</h2><div className="recap-compare">{rows.filter(r=>r[1]!=null).map(([label,value,now],n)=><div key={label} className={value!>=0?"up":"down"} style={{animationDelay:`${200+n*220}ms`}}><span>{label}</span><strong>{value!>=0?"▲":"▼"} {format(Math.abs(value!),0,lang)} %</strong><small>{now}</small></div>)}</div><p className="recap-sub recap-delay-2">{bi(lang,"Verglichen wird jeweils derselbe Zeitraum bis zum heutigen Tag.","Each comparison uses the same span up to today.")}</p></div>}
   case "finale":return <div className="recap-slide recap-finale"><div className="recap-card-preview"><RecapCard data={data} lang={lang} svgRef={cardRef}/></div><div className="recap-actions"><button type="button" disabled={busy} onClick={()=>void save()}>{busy?bi(lang,"Erstelle Bild …","Creating image …"):bi(lang,"Bild speichern","Save image")}</button>{canShare&&<button type="button" className="ghost" disabled={busy} onClick={()=>void share()}>{bi(lang,"Teilen","Share")}</button>}<button type="button" className="ghost" onClick={()=>{elapsed.current=0;setIndex(0);setProgress(0);setPaused(false)}}>{bi(lang,"Nochmal abspielen","Play again")}</button></div>{status&&<p className="recap-sub" role="status">{status}</p>}</div>;
   default:return null;
  }
 }

 return <>
  <button ref={opener} type="button" className="recap-trigger" onClick={()=>{setOpen(true);setPaused(false)}}><svg aria-hidden="true" viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M3 12a9 9 0 1 0 3-6.7"/><path d="M3 4v4h4"/><path d="M12 7v5l3 2"/></svg>{bi(lang,"Rückblick","Recap")}</button>
  {open&&<div className="recap-overlay" role="dialog" aria-modal="true" aria-label={bi(lang,"Rückblick","Recap")}>
   <div className="recap-top">
    <div className="recap-progress" aria-hidden="true">{list.map((s,n)=><i key={s}><b style={{width:`${n<index?100:n===index?progress*100:0}%`}}/></i>)}</div>
    <div className="recap-toolbar">
     <div className="recap-periods" role="radiogroup" aria-label={bi(lang,"Zeitraum","Period")}>{PERIODS.map(p=><button key={p.id} type="button" role="radio" aria-checked={period===p.id} className={period===p.id?"active":""} onClick={()=>setPeriod(p.id)}>{de?p.de:p.en}</button>)}</div>
     <div className="recap-tools">{slide&&slide!=="finale"&&<button type="button" className="recap-icon" aria-label={paused?bi(lang,"Fortsetzen","Resume"):bi(lang,"Pausieren","Pause")} onClick={()=>setPaused(p=>!p)}>{paused?"▶":"❚❚"}</button>}<button ref={closer} type="button" className="recap-icon" aria-label={bi(lang,"Schließen","Close")} onClick={()=>setOpen(false)}>✕</button></div>
    </div>
    {(query||(source&&source!=="all"))&&<p className="recap-filter">{bi(lang,"Gefiltert","Filtered")}: {[query&&`„${query}“`,source&&source!=="all"&&source].filter(Boolean).join(" · ")}</p>}
   </div>
   <div className="recap-stage" onClick={stageClick} key={`${period}-${slide}-${data?.end}`}>{content()}</div>
   {list.length>1&&<div className="recap-nav"><button type="button" className="recap-icon" disabled={index===0} aria-label={bi(lang,"Zurück","Previous")} onClick={()=>go(-1)}>‹</button><span>{index+1} / {list.length}</span><button type="button" className="recap-icon" disabled={index>=list.length-1} aria-label={bi(lang,"Weiter","Next")} onClick={()=>go(1)}>›</button></div>}
  </div>}
 </>;
}
