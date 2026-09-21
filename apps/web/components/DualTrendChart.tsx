"use client";

import {useMemo} from "react";

type Point={date:string;value:number};
type Props={running:Point[];cycling:Point[];lang:"de"|"en"};

export default function DualTrendChart({running,cycling,lang}:Props){
  const chart=useMemo(()=>{
    const clean=(rows:Point[])=>rows
      .map(p=>({date:p.date,value:Number(p.value),ts:new Date(`${p.date}T12:00:00`).getTime()}))
      .filter(p=>Number.isFinite(p.value)&&Number.isFinite(p.ts));
    const run=clean(running),bike=clean(cycling),all=[...run,...bike];
    if(!all.length)return null;
    const minTs=Math.min(...all.map(p=>p.ts)),maxTs=Math.max(...all.map(p=>p.ts));
    const vals=all.map(p=>p.value),rawMin=Math.min(...vals),rawMax=Math.max(...vals);
    const pad=Math.max(1,(rawMax-rawMin)*.12);
    const yMin=Math.floor(rawMin-pad),yMax=Math.ceil(rawMax+pad);
    return {run,bike,minTs,maxTs,yMin,yMax};
  },[running,cycling]);

  if(!chart)return <div className="vo2-empty">—</div>;

  const W=760,H=270,L=52,R=18,T=18,B=42;
  const innerW=W-L-R,innerH=H-T-B;
  const x=(ts:number)=>L+((ts-chart.minTs)/(chart.maxTs-chart.minTs||1))*innerW;
  const y=(v:number)=>T+innerH-((v-chart.yMin)/(chart.yMax-chart.yMin||1))*innerH;
  const line=(rows:typeof chart.run)=>rows.map(p=>`${x(p.ts).toFixed(1)},${y(p.value).toFixed(1)}`).join(" ");
  const ticks=4;
  const yTicks=Array.from({length:ticks+1},(_,i)=>chart.yMin+(chart.yMax-chart.yMin)*(i/ticks));
  const xTicks=Array.from({length:5},(_,i)=>chart.minTs+(chart.maxTs-chart.minTs)*(i/4));
  const fmt=(ts:number)=>new Intl.DateTimeFormat(lang==="de"?"de-DE":"en-US",{month:"short",year:"2-digit"}).format(new Date(ts));
  const showPoints=chart.run.length+chart.bike.length<=160;

  return <div className="vo2-chart-wrap">
    <svg className="vo2-chart" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="VO2 max history">
      {yTicks.map((v,i)=><g key={`y-${i}`}>
        <line className="vo2-grid" x1={L} x2={W-R} y1={y(v)} y2={y(v)}/>
        <text className="vo2-axis-label" x={L-10} y={y(v)+4} textAnchor="end">{v.toFixed(0)}</text>
      </g>)}
      {xTicks.map((ts,i)=><g key={`x-${i}`}>
        <line className="vo2-tick" x1={x(ts)} x2={x(ts)} y1={H-B} y2={H-B+6}/>
        <text className="vo2-axis-label" x={x(ts)} y={H-14} textAnchor={i===0?"start":i===4?"end":"middle"}>{fmt(ts)}</text>
      </g>)}
      <line className="vo2-axis" x1={L} x2={W-R} y1={H-B} y2={H-B}/>
      {chart.run.length>1&&<polyline className="vo2-line vo2-run" points={line(chart.run)} fill="none"/>}
      {chart.bike.length>1&&<polyline className="vo2-line vo2-bike" points={line(chart.bike)} fill="none"/>}
      {showPoints&&chart.run.map((p,i)=><circle key={`r-${i}`} className="vo2-point vo2-run-point" cx={x(p.ts)} cy={y(p.value)} r="3.5"><title>{`${p.date}: ${p.value.toFixed(1)}`}</title></circle>)}
      {showPoints&&chart.bike.map((p,i)=><circle key={`b-${i}`} className="vo2-point vo2-bike-point" cx={x(p.ts)} cy={y(p.value)} r="3.5"><title>{`${p.date}: ${p.value.toFixed(1)}`}</title></circle>)}
      <text className="vo2-unit" transform={`translate(15 ${T+innerH/2}) rotate(-90)`} textAnchor="middle">ml/kg/min</text>
    </svg>
    <div className="vo2-legend"><span><i className="vo2-legend-dot run"/>{lang==="de"?"VO₂max Laufen":"Running VO₂ max"}</span><span><i className="vo2-legend-dot bike"/>{lang==="de"?"VO₂max Radfahren":"Cycling VO₂ max"}</span></div>
  </div>;
}
