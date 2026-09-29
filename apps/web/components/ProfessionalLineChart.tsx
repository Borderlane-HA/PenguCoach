"use client";

import {useId,useMemo,useState} from "react";

type Point={date:string;label?:string;value:number|null|undefined};
type Series={label:string;points:Point[];axis?:"left"|"right";unit?:string;decimals?:number;dashed?:boolean};
type Props={series:Series[];height?:number;ariaLabel?:string;emptyLabel?:string};

function fmt(value:number,decimals=1){return new Intl.NumberFormat(undefined,{maximumFractionDigits:decimals,minimumFractionDigits:decimals}).format(value)}
function humanLabel(value:string){
  if(/^\d{4}-\d{2}-\d{2}$/.test(value)){const d=new Date(`${value}T12:00:00`);return new Intl.DateTimeFormat(undefined,{day:"2-digit",month:"short"}).format(d)}
  if(/^\d{4}-\d{2}$/.test(value)){const d=new Date(`${value}-01T12:00:00`);return new Intl.DateTimeFormat(undefined,{month:"short",year:"2-digit"}).format(d)}
  return value;
}
function extent(values:number[]){
  const min=Math.min(...values),max=Math.max(...values),span=max-min;
  const pad=span===0?Math.max(1,Math.abs(max)*.06):span*.14;
  return [min>=0&&min-pad<0?0:min-pad,max+pad] as const;
}

export default function ProfessionalLineChart({series,height=300,ariaLabel="Trend chart",emptyLabel="—"}:Props){
  const id=useId().replace(/:/g,"");
  const[hover,setHover]=useState<number|null>(null);
  const chart=useMemo(()=>{
    const rows=new Map<string,{date:string;label:string;values:(number|null)[]}>();
    series.forEach((s,si)=>s.points.forEach(p=>{
      const n=Number(p.value),valid=Number.isFinite(n)?n:null;
      const row=rows.get(p.date)??{date:p.date,label:humanLabel(p.label??p.date),values:Array(series.length).fill(null)};
      row.label=humanLabel(p.label??row.label);row.values[si]=valid;rows.set(p.date,row);
    }));
    const ordered=[...rows.values()].sort((a,b)=>a.date.localeCompare(b.date));
    const scales:{left?:readonly[number,number];right?:readonly[number,number]}={};
    for(const axis of ["left","right"] as const){
      const vals:number[]=[];
      series.forEach((s,si)=>{if((s.axis??"left")===axis)ordered.forEach(r=>{const v=r.values[si];if(v!=null)vals.push(v)})});
      if(vals.length)scales[axis]=extent(vals);
    }
    return {ordered,scales};
  },[series]);
  if(!chart.ordered.length||!series.some((_,si)=>chart.ordered.some(r=>r.values[si]!=null)))return <div className="pro-chart-empty">{emptyLabel}</div>;

  const W=900,H=height,L=58,R=series.some(s=>s.axis==="right")?58:22,T=18,B=48,iw=W-L-R,ih=H-T-B;
  const x=(i:number)=>L+(chart.ordered.length<=1?iw/2:(i/(chart.ordered.length-1))*iw);
  const y=(value:number,axis:"left"|"right")=>{const e=chart.scales[axis]??[0,1];return T+ih-((value-e[0])/(e[1]-e[0]||1))*ih};
  const ticks=(axis:"left"|"right")=>{const e=chart.scales[axis];if(!e)return[];return Array.from({length:5},(_,i)=>e[0]+(e[1]-e[0])*(i/4))};
  const pathFor=(si:number)=>{
    const axis=series[si].axis??"left";let d="",open=false;
    chart.ordered.forEach((row,i)=>{const v=row.values[si];if(v==null){open=false;return}d+=`${open?" L":"M"} ${x(i).toFixed(1)} ${y(v,axis).toFixed(1)}`;open=true});
    return d;
  };
  const tickIdx=[...new Set([0,Math.round((chart.ordered.length-1)*.25),Math.round((chart.ordered.length-1)*.5),Math.round((chart.ordered.length-1)*.75),chart.ordered.length-1])].filter(i=>i>=0);
  const active=hover==null?null:chart.ordered[hover];

  return <div className="pro-chart-shell">
    <svg className="pro-chart-svg" viewBox={`0 0 ${W} ${H}`} role="img" aria-label={ariaLabel} onMouseLeave={()=>setHover(null)}>
      <defs>{series.map((_,si)=><linearGradient key={si} id={`${id}-g${si}`} x1="0" y1="0" x2="0" y2="1"><stop offset="0%" className={`pro-stop pro-stop-${si%4}`} stopOpacity=".20"/><stop offset="100%" className={`pro-stop pro-stop-${si%4}`} stopOpacity="0"/></linearGradient>)}</defs>
      {ticks("left").map((v,i)=><g key={`g${i}`}><line className="pro-grid" x1={L} x2={W-R} y1={y(v,"left")} y2={y(v,"left")}/><text className="pro-axis-label" x={L-9} y={y(v,"left")+4} textAnchor="end">{fmt(v,Math.abs(v)<10?1:0)}</text></g>)}
      {chart.scales.right&&ticks("right").map((v,i)=><text key={`r${i}`} className="pro-axis-label" x={W-R+9} y={y(v,"right")+4} textAnchor="start">{fmt(v,Math.abs(v)<10?1:0)}</text>)}
      <line className="pro-axis" x1={L} x2={W-R} y1={H-B} y2={H-B}/>
      {series.map((s,si)=>{
        const d=pathFor(si);if(!d)return null;
        return <g key={s.label}>
          {si===0&&!s.dashed&&chart.ordered.every(row=>row.values[si]!=null)&&<path d={`${d} L ${x(chart.ordered.length-1)} ${H-B} L ${x(0)} ${H-B} Z`} fill={`url(#${id}-g${si})`} className="pro-area"/>}
          <path d={d} fill="none" className={`pro-line pro-series-${si%4}${s.dashed?" is-dashed":""}`}/>
          {chart.ordered.length<=70&&chart.ordered.map((row,i)=>row.values[si]!=null?<circle key={i} cx={x(i)} cy={y(row.values[si]!,s.axis??"left")} r="3.2" className={`pro-point pro-series-fill-${si%4}`}/>:null)}
        </g>;
      })}
      {tickIdx.map(i=><text key={`x${i}`} className="pro-axis-label" x={x(i)} y={H-17} textAnchor={i===0?"start":i===chart.ordered.length-1?"end":"middle"}>{chart.ordered[i]?.label}</text>)}
      {chart.ordered.map((_,i)=>{const left=i===0?L:(x(i-1)+x(i))/2,right=i===chart.ordered.length-1?W-R:(x(i)+x(i+1))/2;return <rect key={`hit${i}`} x={left} y={T} width={Math.max(1,right-left)} height={ih} fill="transparent" onMouseEnter={()=>setHover(i)} onTouchStart={()=>setHover(i)}/>})}
      {hover!=null&&<line className="pro-cursor" x1={x(hover)} x2={x(hover)} y1={T} y2={H-B}/>}    
    </svg>
    {active&&<div className="pro-tooltip" style={{left:`${Math.min(86,Math.max(12,(x(hover!)/W)*100))}%`}}><strong>{active.label}</strong>{series.map((s,si)=>active.values[si]!=null?<span key={s.label}><i className={`pro-legend-dot pro-series-bg-${si%4}`}/>{s.label}<b>{fmt(active.values[si]!,s.decimals??1)}{s.unit?` ${s.unit}`:""}</b></span>:null)}</div>}
    <div className="pro-legend">{series.map((s,si)=><span key={s.label}><i className={`pro-legend-line pro-series-bg-${si%4}${s.dashed?" is-dashed":""}`}/>{s.label}{s.unit?` · ${s.unit}`:""}</span>)}</div>
  </div>;
}
