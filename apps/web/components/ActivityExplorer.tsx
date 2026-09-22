"use client";

import {useEffect,useMemo,useRef,useState} from "react";

type Sample=Record<string,any>;
type MetricKey="heart_rate"|"speed_kmh"|"altitude_m"|"power"|"cadence"|"grade_pct"|"temperature";
type MetricDef={key:MetricKey;de:string;en:string;unit:string;color:string;digits:number};

const METRICS:MetricDef[]=[
  {key:"heart_rate",de:"Herzfrequenz",en:"Heart rate",unit:"bpm",color:"#d94b4b",digits:0},
  {key:"speed_kmh",de:"Geschwindigkeit",en:"Speed",unit:"km/h",color:"#3578c8",digits:1},
  {key:"altitude_m",de:"Höhe",en:"Elevation",unit:"m",color:"#9b7a3b",digits:0},
  {key:"power",de:"Leistung",en:"Power",unit:"W",color:"#7b61c9",digits:0},
  {key:"cadence",de:"Kadenz",en:"Cadence",unit:"rpm",color:"#2d8f7b",digits:0},
  {key:"grade_pct",de:"Steigung",en:"Grade",unit:"%",color:"#d77a2f",digits:1},
  {key:"temperature",de:"Temperatur",en:"Temperature",unit:"°C",color:"#6a7b87",digits:1},
];

function finite(v:any){const n=Number(v);return Number.isFinite(n)?n:null}
function fmt(v:any,d=1){const n=finite(v);return n==null?"—":n.toFixed(d)}
function time(v:any){const n=finite(v);if(n==null)return"—";const s=Math.max(0,Math.round(n));const h=Math.floor(s/3600),m=Math.floor((s%3600)/60),r=s%60;return h?`${h}:${String(m).padStart(2,"0")}:${String(r).padStart(2,"0")}`:`${m}:${String(r).padStart(2,"0")}`}
function pace(v:any){const s=finite(v);if(s==null||s<=0)return"—";const m=Math.floor(s/60),r=Math.round(s%60);return `${m}:${String(r).padStart(2,"0")} min/km`}
function hasMetric(data:Sample[],key:MetricKey){return data.some(x=>finite(x[key])!=null)}
function extent(data:Sample[],key:MetricKey){const a=data.map(x=>finite(x[key])).filter((v):v is number=>v!=null);if(!a.length)return[0,1] as const;let lo=Math.min(...a),hi=Math.max(...a);if(lo===hi){lo-=1;hi+=1}const p=(hi-lo)*.08;return[lo-p,hi+p] as const}
function linePath(data:Sample[],key:MetricKey,w:number,h:number,pad:number){const[lo,hi]=extent(data,key);let started=false,path="";data.forEach((row,i)=>{const v=finite(row[key]);if(v==null){started=false;return}const x=pad+(i/Math.max(1,data.length-1))*(w-pad*2);const y=pad+((hi-v)/(hi-lo))*(h-pad*2);path+=`${started?" L":"M"}${x.toFixed(1)} ${y.toFixed(1)}`;started=true});return path}

export default function ActivityExplorer({data,lang}:{data:Sample[];lang:string}){
  const available=useMemo(()=>METRICS.filter(m=>hasMetric(data,m.key)),[data]);
  const initial=useMemo(()=>available.filter(m=>["heart_rate","speed_kmh","altitude_m","power"].includes(m.key)).map(m=>m.key),[available]);
  const[selected,setSelected]=useState<MetricKey[]>(initial.length?initial:available.slice(0,3).map(m=>m.key));
  useEffect(()=>{if(!selected.length&&available.length)setSelected(initial.length?initial:available.slice(0,3).map(m=>m.key))},[available,initial,selected.length]);
  const[mode,setMode]=useState<"overlay"|"stacked">("overlay");
  const[xMode,setXMode]=useState<"time"|"distance">("time");
  const[from,setFrom]=useState(0),[to,setTo]=useState(100),[cursor,setCursor]=useState<number|null>(null);
  const svgRef=useRef<SVGSVGElement|null>(null);
  const de=lang!=="en";
  const filtered=useMemo(()=>{if(!data.length)return[];const a=Math.floor((Math.min(from,to)/100)*(data.length-1));const b=Math.ceil((Math.max(from,to)/100)*(data.length-1));return data.slice(a,b+1)},[data,from,to]);
  const active=available.filter(m=>selected.includes(m.key));
  const point=cursor==null?null:filtered[Math.max(0,Math.min(filtered.length-1,cursor))];
  const W=1200,H=330,P=44;
  function toggle(k:MetricKey){setSelected(v=>v.includes(k)?(v.length>1?v.filter(x=>x!==k):v):[...v,k])}
  function pointer(e:React.PointerEvent<SVGSVGElement>){const r=e.currentTarget.getBoundingClientRect();const pct=Math.max(0,Math.min(1,(e.clientX-r.left)/r.width));setCursor(Math.round(pct*Math.max(0,filtered.length-1)))}
  function xLabel(row:Sample|undefined){if(!row)return"—";return xMode==="distance"&&finite(row.distance_km)!=null?`${fmt(row.distance_km,2)} km`:time(row.elapsed_s)}
  function axisLabelAt(frac:number){if(!filtered.length)return"";const row=filtered[Math.round(frac*(filtered.length-1))];return xLabel(row)}

  if(!data.length)return <div className="activity-chart-empty">{de?"Keine FIT-Zeitreihe verfügbar.":"No FIT time series available."}</div>;
  return <div className="activity-explorer">
    <div className="chart-toolbar">
      <div className="chart-chip-row" aria-label={de?"Messwerte":"Metrics"}>{available.map(m=><button type="button" key={m.key} className={`chart-chip ${selected.includes(m.key)?"active":""}`} onClick={()=>toggle(m.key)}><span className="chart-dot" style={{background:m.color}}/>{de?m.de:m.en}</button>)}</div>
      <div className="chart-segmented"><button type="button" className={mode==="overlay"?"active":""} onClick={()=>setMode("overlay")}>{de?"Überlagert":"Overlay"}</button><button type="button" className={mode==="stacked"?"active":""} onClick={()=>setMode("stacked")}>{de?"Untereinander":"Stacked"}</button></div>
      <div className="chart-segmented"><button type="button" className={xMode==="time"?"active":""} onClick={()=>setXMode("time")}>{de?"Zeit":"Time"}</button><button type="button" className={xMode==="distance"?"active":""} onClick={()=>setXMode("distance")}>{de?"Distanz":"Distance"}</button></div>
    </div>

    {mode==="overlay"?<div className="chart-stage">
      <svg ref={svgRef} className="activity-svg" viewBox={`0 0 ${W} ${H}`} role="img" aria-label={de?"Überlagertes Aktivitätsdiagramm":"Overlaid activity chart"} onPointerMove={pointer} onPointerLeave={()=>setCursor(null)}>
        {[0,.25,.5,.75,1].map(t=><line key={`g${t}`} x1={P+t*(W-P*2)} y1={P} x2={P+t*(W-P*2)} y2={H-P} className="chart-grid"/>)}
        {[0,.25,.5,.75,1].map(t=><line key={`h${t}`} x1={P} y1={P+t*(H-P*2)} x2={W-P} y2={P+t*(H-P*2)} className="chart-grid"/>)}
        {active.map(m=><path key={m.key} d={linePath(filtered,m.key,W,H,P)} fill="none" stroke={m.color} strokeWidth="3" strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke"/>) }
        {cursor!=null&&<line x1={P+(cursor/Math.max(1,filtered.length-1))*(W-P*2)} y1={P} x2={P+(cursor/Math.max(1,filtered.length-1))*(W-P*2)} y2={H-P} className="chart-cursor"/>}
        {[0,.25,.5,.75,1].map(t=><text key={`x${t}`} x={P+t*(W-P*2)} y={H-10} textAnchor={t===0?"start":t===1?"end":"middle"} className="chart-axis-label">{axisLabelAt(t)}</text>)}
      </svg>
      <div className="chart-scale-note">{de?"Jede Kurve nutzt im Überlagerungsmodus ihre eigene Skala; der Tooltip zeigt die Originalwerte.":"Each line uses its own scale in overlay mode; the tooltip shows original values."}</div>
    </div>:<div className="stacked-charts">{active.map(m=><MiniPanel key={m.key} metric={m} data={filtered} cursor={cursor} onPointer={pct=>setCursor(Math.round(pct*Math.max(0,filtered.length-1)))} de={de}/>)}</div>}

    <div className="chart-readout" aria-live="polite"><div><span>{de?"Position":"Position"}</span><strong>{point?xLabel(point):de?"Mit Maus/Finger ins Diagramm":"Move pointer over chart"}</strong></div>{active.map(m=><div key={m.key}><span>{de?m.de:m.en}</span><strong>{point?`${fmt(point[m.key],m.digits)} ${m.unit}`:"—"}</strong></div>)}{point&&finite(point.pace_s_per_km)!=null&&<div><span>Pace</span><strong>{pace(point.pace_s_per_km)}</strong></div>}</div>

    <div className="range-panel"><div className="between"><strong>{de?"Analysebereich":"Analysis range"}</strong><span className="muted">{Math.min(from,to)}–{Math.max(from,to)} %</span></div><div className="dual-range"><input aria-label={de?"Start des Analysebereichs":"Analysis range start"} type="range" min="0" max="100" value={from} onChange={e=>setFrom(Number(e.target.value))}/><input aria-label={de?"Ende des Analysebereichs":"Analysis range end"} type="range" min="0" max="100" value={to} onChange={e=>setTo(Number(e.target.value))}/></div><div className="range-actions"><button type="button" className="ghost compact" onClick={()=>{setFrom(0);setTo(100)}}>{de?"Gesamt":"All"}</button><button type="button" className="ghost compact" onClick={()=>{setFrom(0);setTo(50)}}>{de?"1. Hälfte":"First half"}</button><button type="button" className="ghost compact" onClick={()=>{setFrom(50);setTo(100)}}>{de?"2. Hälfte":"Second half"}</button></div></div>
  </div>
}

function MiniPanel({metric,data,cursor,onPointer,de}:{metric:MetricDef;data:Sample[];cursor:number|null;onPointer:(p:number)=>void;de:boolean}){
  const W=1200,H=128,P=30;const[lo,hi]=extent(data,metric.key);
  return <div className="mini-panel"><div className="mini-panel-title"><span className="chart-dot" style={{background:metric.color}}/><strong>{de?metric.de:metric.en}</strong><span>{fmt(lo,metric.digits)}–{fmt(hi,metric.digits)} {metric.unit}</span></div><svg className="activity-svg mini" viewBox={`0 0 ${W} ${H}`} onPointerMove={e=>{const r=e.currentTarget.getBoundingClientRect();onPointer(Math.max(0,Math.min(1,(e.clientX-r.left)/r.width)))}} onPointerLeave={()=>{}}><line x1={P} y1={H/2} x2={W-P} y2={H/2} className="chart-grid"/><path d={linePath(data,metric.key,W,H,P)} fill="none" stroke={metric.color} strokeWidth="2.5" vectorEffect="non-scaling-stroke"/>{cursor!=null&&<line x1={P+(cursor/Math.max(1,data.length-1))*(W-P*2)} y1={P/2} x2={P+(cursor/Math.max(1,data.length-1))*(W-P*2)} y2={H-P/2} className="chart-cursor"/>}</svg></div>
}
