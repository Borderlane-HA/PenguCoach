"use client";
import {useEffect,useMemo,useRef,useState} from "react";
import {api} from "../lib/api";
import {bi,type Lang} from "../lib/i18n";
import {activityTimeLabel} from "../lib/sources";
import {finite} from "../lib/activityExplorer";
import {FORMATS,STYLES,type Box,type ColorBy,type FormatId,type StyleId,colouredRuns,decimal,effortText,elevationProfile,fileName,fitText,headlineStats,kindLabel,kindOf,pathOf,personalRecords,projectRoute,waveform,zoneSeconds,zonesFromProfiles} from "../lib/showcase";

type O=Record<string,any>;
const FONT='Inter, ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif';
const SPORT_QUERY:Record<string,string>={run:"running",walk:"walking",hike:"hiking",ride:"cycling",swim:"swimming",strength:"strength",other:"other"};

// Real text width from the browser's font engine; letter spacing is added per character.
function measurer(font:string,spacing:number){
 if(typeof document==="undefined")return undefined;
 const context=document.createElement("canvas").getContext("2d");if(!context)return undefined;
 context.font=font;return (value:string)=>context.measureText(value).width+spacing*value.length;
}
type Layout={pad:number;eyebrowY:number;nameY:number;nameSize:number;dateY:number;textX:number;textW:number;chipsY:number;route:Box;stats:{x:number;y:number;w:number;rowH:number;cols:number;valueSize:number};elev:Box;zonesY:number;footerY:number};
function layout(format:FormatId,hasChips:boolean):Layout{
 if(format==="landscape")return {pad:60,eyebrowY:118,nameY:178,nameSize:50,dateY:222,textX:940,textW:600,chipsY:256,route:{x:70,y:70,w:800,h:760},stats:{x:940,y:hasChips?352:312,w:600,rowH:132,cols:2,valueSize:60},elev:{x:940,y:620,w:600,h:96},zonesY:760,footerY:842};
 if(format==="story")return {pad:80,eyebrowY:170,nameY:240,nameSize:62,dateY:292,textX:80,textW:920,chipsY:330,route:{x:90,y:hasChips?430:380,w:900,h:hasChips?760:810},stats:{x:80,y:1290,w:920,rowH:160,cols:2,valueSize:76},elev:{x:80,y:1630,w:920,h:110},zonesY:1780,footerY:1858};
 return {pad:72,eyebrowY:112,nameY:172,nameSize:54,dateY:218,textX:72,textW:936,chipsY:252,route:{x:84,y:hasChips?330:288,w:912,h:hasChips?462:504},stats:{x:72,y:858,w:936,rowH:122,cols:2,valueSize:62},elev:{x:72,y:1074,w:936,h:86},zonesY:1214,footerY:1314};
}

export function ShowcaseCard({activity,analysis,series,lang,format,style,colorBy,records,zones,svgRef}:{activity:O;analysis:O|null;series:O[];lang:Lang;format:FormatId;style:StyleId;colorBy:ColorBy;records:O[];zones:{seconds:number[]}|null;svgRef?:React.Ref<SVGSVGElement>}){
 const palette=STYLES[style],{w,h}=FORMATS[format],kind=kindOf(activity.sport_type),L=layout(format,records.length>0);
 const route=useMemo(()=>projectRoute(series,L.route),[series,format,records.length>0]);
 const runs=useMemo(()=>route&&colorBy!=="gradient"?colouredRuns(route.segments,colorBy==="heart_rate"?"heart_rate":"speed_kmh"):[],[route,colorBy]);
 const elev=useMemo(()=>elevationProfile(series,{x:L.elev.x,y:L.elev.y+30,w:L.elev.w,h:L.elev.h-30}),[series,format,records.length>0]);
 const stats=headlineStats(activity,analysis,lang);
 const waveKey=series.some(r=>finite(r.heart_rate))?"heart_rate":series.some(r=>finite(r.power))?"power":"speed_kmh";
 const wave=route?null:waveform(series,waveKey,{x:L.route.x,y:L.route.y+L.route.h*.2,w:L.route.w,h:L.route.h*.6});
 const title=fitText(String(activity.name||kindLabel(kind,lang)),L.textW,L.nameSize,measurer(`800 ${L.nameSize}px ${FONT}`,-1.5));
 const routePaths=route?route.segments.map(s=>pathOf(s)):[];
 const totalZone=zones?zones.seconds.reduce((a,b)=>a+b,0):0;
 const de=lang==="de";
 // Personal-best badges; a second badge is only shown when both fit on one line.
 const chipText=style==="night"?palette.accent:palette.bg[0];
 const chips:{label:string;width:number;x:number}[]=[];
 for(const record of records.slice(0,2)){
  const label=`${de?"BESTLEISTUNG":"PERSONAL BEST"} · ${effortText(record,kind,lang)}`,width=label.length*13.6+56;
  const x=chips.length?chips[0].x+chips[0].width+14:L.textX;
  if(x+width<=L.textX+L.textW)chips.push({label,width,x});
 }
 return <svg ref={svgRef} xmlns="http://www.w3.org/2000/svg" width={w} height={h} viewBox={`0 0 ${w} ${h}`} fontFamily={FONT} role="img" aria-label={`${kindLabel(kind,lang)} · ${title}`}>
  <defs>
   <linearGradient id="sc-bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stopColor={palette.bg[0]}/><stop offset="1" stopColor={palette.bg[1]}/></linearGradient>
   {route&&<linearGradient id="sc-route" gradientUnits="userSpaceOnUse" x1={route.start.x} y1={route.start.y} x2={route.end.x} y2={route.end.y}><stop offset="0" stopColor={palette.route[0]}/><stop offset="1" stopColor={palette.route[1]}/></linearGradient>}
   <linearGradient id="sc-elev" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor={palette.accent} stopOpacity=".42"/><stop offset="1" stopColor={palette.accent} stopOpacity="0"/></linearGradient>
   <filter id="sc-glow" x="-20%" y="-20%" width="140%" height="140%"><feGaussianBlur stdDeviation="12"/></filter>
  </defs>
  <rect width={w} height={h} fill="url(#sc-bg)"/>
  {style==="night"&&<><circle cx={w*.86} cy={h*.08} r={w*.42} fill={palette.accent} opacity=".07"/><circle cx={w*.05} cy={h*.92} r={w*.32} fill="#7cc8ff" opacity=".06"/></>}
  {style==="paper"&&<rect x={L.pad/2} y={L.pad/2} width={w-L.pad} height={h-L.pad} rx="28" fill="none" stroke={palette.track} strokeWidth="2"/>}
  {style==="poster"&&<text x={w-L.pad} y={L.route.y+L.route.h*.86} textAnchor="end" fontSize={w*.2} fontWeight="900" fill={palette.accent} opacity=".08" letterSpacing="-8">{kindLabel(kind,lang).toUpperCase()}</text>}

  <text x={L.textX} y={L.eyebrowY} fontSize="24" fontWeight="800" letterSpacing="5" fill={palette.accent}>{kindLabel(kind,lang).toUpperCase()}</text>
  <text x={L.textX} y={L.nameY} fontSize={L.nameSize} fontWeight="800" letterSpacing="-1.5" fill={palette.text}>{title}</text>
  <text x={L.textX} y={L.dateY} fontSize="27" fill={palette.muted}>{activityTimeLabel(activity,lang).replace(/(\d{1,2}:\d{2}):\d{2}/,"$1")}</text>
  {chips.map((chip,i)=><g key={i} transform={`translate(${chip.x} ${L.chipsY})`}>
   <rect width={chip.width} height="46" rx="23" fill={palette.accent} opacity={style==="night"?.16:1}/>
   {style==="night"&&<rect width={chip.width} height="46" rx="23" fill="none" stroke={palette.accent} strokeWidth="2"/>}
   <path d="M24 12l3.2 6.4 7 1-5.1 5 1.2 7-6.3-3.3-6.3 3.3 1.2-7-5.1-5 7-1z" fill={chipText}/>
   <text x="44" y="30.5" fontSize="22" fontWeight="800" letterSpacing="1" fill={chipText}>{chip.label}</text>
  </g>)}

  {route&&<g strokeLinecap="round" strokeLinejoin="round" fill="none">
   {palette.glow&&routePaths.map((d,i)=><path key={`g${i}`} d={d} stroke={palette.accent} strokeWidth="18" opacity=".45" filter="url(#sc-glow)"/>)}
   {routePaths.map((d,i)=><path key={`t${i}`} d={d} stroke={palette.track} strokeWidth="22"/>)}
   {runs.length?runs.map((r,i)=><path key={`c${i}`} d={r.d} stroke={palette.buckets[r.bucket]} strokeWidth="10"/>):routePaths.map((d,i)=><path key={`r${i}`} d={d} stroke="url(#sc-route)" strokeWidth="10"/>)}
   <circle cx={route.start.x} cy={route.start.y} r="13" fill={palette.bg[0]} stroke={palette.accent} strokeWidth="6"/>
   <circle cx={route.end.x} cy={route.end.y} r="15" fill={palette.text}/><circle cx={route.end.x} cy={route.end.y} r="7" fill={palette.bg[1]}/>
  </g>}
  {!route&&wave&&<g>{wave.map((b,i)=><rect key={i} x={b.x} y={b.y} width={b.w} height={b.h} rx={b.w/2} fill={palette.buckets[Math.min(4,Math.floor(i/wave.length*5))]} opacity=".9"/>)}<text x={L.route.x} y={L.route.y+L.route.h*.12} fontSize="24" fontWeight="700" letterSpacing="3" fill={palette.muted}>{(waveKey==="heart_rate"?bi(lang,"Herzfrequenzverlauf","Heart rate"):waveKey==="power"?bi(lang,"Leistungsverlauf","Power"):bi(lang,"Tempoverlauf","Speed")).toUpperCase()}</text></g>}
  {!route&&!wave&&<text x={L.route.x+L.route.w/2} y={L.route.y+L.route.h/2} textAnchor="middle" fontSize={L.route.w*.13} fontWeight="900" fill={palette.text} opacity=".9">{kindLabel(kind,lang)}</text>}

  {stats.map((s,i)=>{const col=i%L.stats.cols,row=Math.floor(i/L.stats.cols),cw=L.stats.w/L.stats.cols,x=L.stats.x+col*cw,y=L.stats.y+row*L.stats.rowH;return <g key={s.key}>
   <text x={x} y={y} fontSize="23" fontWeight="800" letterSpacing="3" fill={palette.muted}>{s.label.toUpperCase()}</text>
   <text x={x} y={y+L.stats.valueSize+8} fontSize={L.stats.valueSize} fontWeight="800" letterSpacing="-2" fill={palette.text}>{s.value}{s.unit&&<tspan fontSize={L.stats.valueSize*.42} fontWeight="700" letterSpacing="0" fill={palette.muted} dx="10">{s.unit}</tspan>}</text>
  </g>})}

  {elev&&<g><text x={L.elev.x} y={L.elev.y+18} fontSize="21" fontWeight="800" letterSpacing="3" fill={palette.muted}>{bi(lang,"HÖHENPROFIL","ELEVATION")}</text><text x={L.elev.x+L.elev.w} y={L.elev.y+18} textAnchor="end" fontSize="21" fill={palette.muted}>{decimal(elev.min,0,lang)}–{decimal(elev.max,0,lang)} m</text><path d={elev.area} fill="url(#sc-elev)"/><path d={elev.line} fill="none" stroke={palette.accent} strokeWidth="3.5" strokeLinejoin="round"/></g>}

  {zones&&totalZone>0&&<g>
   <text x={L.elev.x} y={L.zonesY-14} fontSize="21" fontWeight="800" letterSpacing="3" fill={palette.muted}>{bi(lang,"PULSZONEN","HEART RATE ZONES")}</text>
   {(()=>{let x=L.elev.x;return zones.seconds.map((s,i)=>{const width=s/totalZone*L.elev.w,start=x;x+=width;return width>0?<g key={i}><rect x={start} y={L.zonesY} width={Math.max(width-3,1)} height="16" rx="8" fill={STYLES[style].buckets[Math.min(4,Math.round(i*4/Math.max(1,zones.seconds.length-1)))]}/>{width>70&&<text x={start+width/2} y={L.zonesY+44} textAnchor="middle" fontSize="19" fontWeight="700" fill={palette.muted}>Z{i+1} {Math.round(s/totalZone*100)}%</text>}</g>:null})})()}
  </g>}

  <text x={L.textX} y={L.footerY} fontSize="26" fontWeight="800" fill={palette.text}>PenguCoach</text>
  <text x={format==="landscape"?L.textX+L.textW:w-L.pad} y={L.footerY} textAnchor="end" fontSize="21" fill={palette.muted}>{bi(lang,"Training & Health","Training & Health")}</text>
 </svg>;
}

export async function renderPng(svg:SVGSVGElement,width:number,height:number):Promise<Blob>{
 const xml=new XMLSerializer().serializeToString(svg);
 const image=new Image();
 image.decoding="async";
 image.src="data:image/svg+xml;charset=utf-8,"+encodeURIComponent(xml);
 await image.decode();
 const canvas=document.createElement("canvas");canvas.width=width;canvas.height=height;
 const context=canvas.getContext("2d");if(!context)throw new Error("CANVAS_UNAVAILABLE");
 context.drawImage(image,0,0,width,height);
 return await new Promise((resolve,reject)=>canvas.toBlob(b=>b?resolve(b):reject(new Error("PNG_EXPORT_FAILED")),"image/png"));
}

const PREF="pengucoach_showcase";
export default function ActivityShowcase({activity,analysis,series,lang,activityId}:{activity:O;analysis:O|null;series:O[];lang:Lang;activityId:string}){
 const[open,setOpen]=useState(false),[format,setFormat]=useState<FormatId>("portrait"),[style,setStyle]=useState<StyleId>("night"),[colorBy,setColorBy]=useState<ColorBy>("gradient");
 const[records,setRecords]=useState<O[]>([]),[checking,setChecking]=useState(false),[zoneData,setZoneData]=useState<{seconds:number[]}|null>(null),[busy,setBusy]=useState(false),[status,setStatus]=useState("");
 const svgRef=useRef<SVGSVGElement>(null),dialogRef=useRef<HTMLElement>(null),opener=useRef<HTMLButtonElement>(null);
 const kind=kindOf(activity.sport_type);
 const hasHr=series.some(r=>finite(r.heart_rate)),hasSpeed=series.some(r=>(finite(r.speed_kmh)??0)>0),hasGps=series.some(r=>finite(r.position_lat)!=null);
 useEffect(()=>{try{const v=JSON.parse(localStorage.getItem(PREF)||"{}");if(v.format in FORMATS)setFormat(v.format);if(v.style in STYLES)setStyle(v.style);if(["gradient","heart_rate","speed"].includes(v.colorBy))setColorBy(v.colorBy)}catch{}},[]);
 useEffect(()=>{try{localStorage.setItem(PREF,JSON.stringify({format,style,colorBy}))}catch{}},[format,style,colorBy]);
 useEffect(()=>{
  if(!open)return;let active=true;
  // Recorded zone durations (SparkyFitness) first, otherwise the Garmin zone profile for this sport.
  const recorded=(analysis?.hr_zones??[]) as O[];
  if(recorded.length>=3)setZoneData({seconds:recorded.map(z=>Number(z.duration_seconds)||0)});
  else if(hasHr)api<O>("/garmin/zones").then(z=>{const zones=zonesFromProfiles(z?.heart_rate?.profiles,kind);if(active&&zones)setZoneData({seconds:zoneSeconds(series,zones)})}).catch(()=>{});
  setChecking(true);
  Promise.all([api<O>(`/activities/${activityId}/best-efforts`),api<O>(`/coach/best-efforts?sport=${SPORT_QUERY[kind]}`)])
   .then(([own,personal])=>{if(active)setRecords(personalRecords(activityId,own?.items??[],personal?.items??[]))})
   .catch(()=>{}).finally(()=>{if(active)setChecking(false)});
  return()=>{active=false};
 },[open,activityId]);
 useEffect(()=>{
  if(!open)return;const node=dialogRef.current;node?.querySelector<HTMLElement>("button")?.focus();
  const key=(e:KeyboardEvent)=>{if(e.key==="Escape")setOpen(false);if(e.key==="Tab"&&node){const items=Array.from(node.querySelectorAll<HTMLElement>("button:not(:disabled)"));const first=items[0],last=items.at(-1);if(e.shiftKey&&document.activeElement===first){e.preventDefault();last?.focus()}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first?.focus()}}};
  document.addEventListener("keydown",key);document.body.style.overflow="hidden";
  return()=>{document.removeEventListener("keydown",key);document.body.style.overflow="";opener.current?.focus()};
 },[open]);
 const{w,h}=FORMATS[format];
 async function image(){if(!svgRef.current)throw new Error("NO_CARD");return renderPng(svgRef.current,w,h)}
 async function save(){setBusy(true);setStatus("");try{const blob=await image(),url=URL.createObjectURL(blob),a=document.createElement("a");a.href=url;a.download=fileName(activity,format);document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),2000);setStatus(bi(lang,"Bild gespeichert.","Image saved."))}catch{setStatus(bi(lang,"Das Bild konnte nicht erstellt werden.","The image could not be created."))}finally{setBusy(false)}}
 const canShare=typeof navigator!=="undefined"&&typeof navigator.canShare==="function";
 async function share(){setBusy(true);setStatus("");try{const blob=await image(),file=new File([blob],fileName(activity,format),{type:"image/png"});if(navigator.canShare?.({files:[file]})){await navigator.share({files:[file],title:String(activity.name??"PenguCoach")})}else{setStatus(bi(lang,"Teilen wird von diesem Browser nicht unterstützt – speichere das Bild stattdessen.","Sharing is not supported by this browser – save the image instead."))}}catch(e){if(!(e instanceof DOMException&&e.name==="AbortError"))setStatus(bi(lang,"Teilen ist fehlgeschlagen.","Sharing failed."))}finally{setBusy(false)}}
 const choice=<T extends string>(label:string,value:T,set:(v:T)=>void,options:[T,string][])=><div className="showcase-choice"><span>{label}</span><div role="radiogroup" aria-label={label}>{options.map(([key,text])=><button type="button" role="radio" aria-checked={value===key} key={key} className={value===key?"active":""} onClick={()=>set(key)}>{text}</button>)}</div></div>;
 return <>
  <button ref={opener} type="button" className="showcase-trigger" onClick={()=>setOpen(true)}><svg aria-hidden="true" viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 3l2.6 5.3 5.9.9-4.3 4.1 1 5.8-5.2-2.7-5.2 2.7 1-5.8-4.3-4.1 5.9-.9z"/></svg>Showcase</button>
  {open&&<div className="modal-backdrop showcase-backdrop" onMouseDown={e=>{if(e.target===e.currentTarget)setOpen(false)}}><section ref={dialogRef} className="card showcase-dialog" role="dialog" aria-modal="true" aria-labelledby="showcase-title">
   <div className="showcase-preview" data-format={format}><ShowcaseCard activity={activity} analysis={analysis} series={series} lang={lang} format={format} style={style} colorBy={hasGps?colorBy:"gradient"} records={records} zones={zoneData} svgRef={svgRef}/></div>
   <div className="showcase-controls">
    <div><span className="eyebrow">SHOWCASE</span><h2 id="showcase-title">{bi(lang,"Deine Aktivität als Bild","Your activity as an image")}</h2><p className="muted">{bi(lang,"Wähle Stil und Format und speichere die Karte oder teile sie direkt.","Pick a style and format, then save the card or share it directly.")}</p></div>
    {choice(bi(lang,"Stil","Style"),style,setStyle,(Object.keys(STYLES) as StyleId[]).map(k=>[k,lang==="de"?STYLES[k].de:STYLES[k].en]))}
    {choice("Format",format,setFormat,(Object.keys(FORMATS) as FormatId[]).map(k=>[k,lang==="de"?FORMATS[k].de:FORMATS[k].en]))}
    {hasGps&&(hasHr||hasSpeed)&&choice(bi(lang,"Strecke färben","Route colour"),colorBy,setColorBy,[["gradient",bi(lang,"Verlauf","Gradient")],...(hasHr?[["heart_rate",bi(lang,"Puls","Heart rate")]] as [ColorBy,string][]:[]),...(hasSpeed?[["speed",bi(lang,"Tempo","Speed")]] as [ColorBy,string][]:[])])}
    <p className="showcase-note" role="status">{checking?bi(lang,"Bestleistungen werden geprüft …","Checking personal bests …"):records.length?bi(lang,`${records.length} Bestleistung(en) in dieser Einheit – auf der Karte hervorgehoben.`,`${records.length} personal best(s) in this session – highlighted on the card.`):status}</p>
    {status&&(checking||records.length>0)&&<p className="showcase-note">{status}</p>}
    <div className="showcase-actions"><button type="button" disabled={busy} onClick={()=>void save()}>{busy?bi(lang,"Erstelle Bild …","Creating image …"):bi(lang,"Bild speichern","Save image")}</button>{canShare&&<button type="button" className="ghost" disabled={busy} onClick={()=>void share()}>{bi(lang,"Teilen","Share")}</button>}<button type="button" className="ghost" onClick={()=>setOpen(false)}>{bi(lang,"Schließen","Close")}</button></div>
    <small className="muted">{w} × {h} px · PNG</small>
   </div>
  </section></div>}
 </>;
}
