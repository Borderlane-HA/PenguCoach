"use client";

import {useMemo,useState} from "react";

type Row={date:string;label:string;total_minutes:number;[key:string]:string|number};
type Props={rows:Row[];lang:"de"|"en"};
const keys=["running","cycling","strength","mobility","swimming","walking","other"] as const;
const labels:{[key:string]:[string,string]}={running:["Laufen","Running"],cycling:["Rad","Cycling"],strength:["Kraft","Strength"],mobility:["Mobility","Mobility"],swimming:["Schwimmen","Swimming"],walking:["Gehen/Wandern","Walk/Hike"],other:["Sonstiges","Other"]};

export default function TrainingVolumeChart({rows,lang}:Props){
  const[hover,setHover]=useState<number|null>(null);
  const chart=useMemo(()=>{const max=Math.max(1,...rows.map(r=>Number(r.total_minutes)||0));const active=keys.filter(k=>rows.some(r=>Number(r[k]||0)>0));return{max,active}},[rows]);
  if(!rows.length)return <div className="pro-chart-empty">—</div>;
  const W=900,H=300,L=54,R=18,T=18,B=48,iw=W-L-R,ih=H-T-B,bar=Math.max(5,Math.min(42,iw/Math.max(1,rows.length)*.68));
  const x=(i:number)=>L+((i+.5)/rows.length)*iw,y=(v:number)=>T+ih-(v/chart.max)*ih;
  const ticks=Array.from({length:5},(_,i)=>chart.max*i/4);
  const tickIdx=[...new Set([0,Math.round((rows.length-1)*.25),Math.round((rows.length-1)*.5),Math.round((rows.length-1)*.75),rows.length-1])].filter(i=>i>=0);
  const active=hover==null?null:rows[hover];
  return <div className="pro-chart-shell">
    <svg className="pro-chart-svg" viewBox={`0 0 ${W} ${H}`} role="img" aria-label={lang==="de"?"Trainingsvolumen":"Training volume"} onMouseLeave={()=>setHover(null)}>
      {ticks.map((v,i)=><g key={i}><line className="pro-grid" x1={L} x2={W-R} y1={y(v)} y2={y(v)}/><text className="pro-axis-label" x={L-9} y={y(v)+4} textAnchor="end">{Math.round(v)}</text></g>)}
      <line className="pro-axis" x1={L} x2={W-R} y1={H-B} y2={H-B}/>
      {rows.map((row,i)=>{let cumulative=0;return <g key={row.date}>{chart.active.map((k,si)=>{const v=Number(row[k]||0),top=y(cumulative+v),bottom=y(cumulative),h=Math.max(0,bottom-top);cumulative+=v;return v>0?<rect key={k} x={x(i)-bar/2} y={top} width={bar} height={h} rx={si===chart.active.length-1?3:0} className={`pro-bar pro-series-fill-${si%4}`}/>:null})}<rect x={x(i)-Math.max(bar,iw/rows.length)/2} y={T} width={Math.max(bar,iw/rows.length)} height={ih} fill="transparent" onMouseEnter={()=>setHover(i)} onTouchStart={()=>setHover(i)}/></g>})}
      {tickIdx.map(i=><text key={`x${i}`} className="pro-axis-label" x={x(i)} y={H-17} textAnchor={i===0?"start":i===rows.length-1?"end":"middle"}>{rows[i]?.label}</text>)}
      <text className="pro-axis-title" x="15" y={T+ih/2} transform={`rotate(-90 15 ${T+ih/2})`} textAnchor="middle">min</text>
      {hover!=null&&<line className="pro-cursor" x1={x(hover)} x2={x(hover)} y1={T} y2={H-B}/>}    
    </svg>
    {active&&<div className="pro-tooltip" style={{left:`${Math.min(86,Math.max(12,(x(hover!)/W)*100))}%`}}><strong>{active.label}</strong>{chart.active.map((k,si)=>Number(active[k]||0)>0?<span key={k}><i className={`pro-legend-dot pro-series-bg-${si%4}`}/>{labels[k][lang==="de"?0:1]}<b>{Math.round(Number(active[k]))} min</b></span>:null)}<em>{lang==="de"?"Gesamt":"Total"}: {Math.round(Number(active.total_minutes))} min</em></div>}
    <div className="pro-legend">{chart.active.map((k,si)=><span key={k}><i className={`pro-legend-dot pro-series-bg-${si%4}`}/>{labels[k][lang==="de"?0:1]}</span>)}</div>
  </div>;
}
