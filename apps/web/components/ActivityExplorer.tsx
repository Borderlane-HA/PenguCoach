"use client";
import ClientLink from "next/link";


import {useCallback,useEffect,useMemo,useRef,useState} from "react";
import ActivityRouteMap from "./ActivityRouteMap";
import ActivityPanorama from "./ActivityPanorama";
import RouteBriefing from "./RouteBriefing";
import RouteComparison from "./RouteComparison";
import InfoTip from "./InfoTip";
import {api} from "../lib/api";
import {AxisMode,extent,finite,linePath,makeAxis,MapSettings,METRICS,Metric,metricLabel,nearestIndex,routeSegments,Sample,timeLabel} from "../lib/activityExplorer";

const MINI_W=1200,P=16,TOP=14,BOTTOM=30;
const DEFAULTS=["heart_rate","speed_kmh","altitude_m","power"];
const TICKS=[0,.25,.5,.75,1];

export default function ActivityExplorer({data,lang,activityId}:{data:Sample[];lang:string;activityId?:string}){
  const de=lang!=="en";
  const available=useMemo(()=>METRICS.filter(m=>data.some(row=>finite(row[m.key])!=null)),[data]);
  const initial=useMemo(()=>{const keys=available.filter(m=>DEFAULTS.includes(m.key));return (keys.length?keys:available.slice(0,3)).map(m=>m.key)},[available]);
  const [selected,setSelected]=useState<string[]>([]),[mode,setMode]=useState<"overlay"|"stacked">("overlay"),[xMode,setXMode]=useState<AxisMode>("time");
  const [from,setFrom]=useState(0),[to,setTo]=useState(100),[cursor,setCursor]=useState<number|null>(0),[hover,setHover]=useState<number|null>(null);
  const [annotations,setAnnotations]=useState<Record<string,any>[]>([]);
  const [settings,setSettings]=useState<MapSettings|null>(null),[settingsFailed,setSettingsFailed]=useState(false);
  const [playing,setPlaying]=useState(false),[replaySpeed,setReplaySpeed]=useState(60);
  const replayClock=useRef(0);
  const [colorKey,setColorKey]=useState(""),[googleActive,setGoogleActive]=useState(false);
  // The chart is drawn at its real pixel width, so text stays crisp and the
  // curve keeps a readable height on phones (no squashed 1200-wide viewBox).
  const stage=useRef<HTMLDivElement>(null),[W,setWidth]=useState(1200);
  useEffect(()=>{const el=stage.current;if(!el)return;const update=()=>setWidth(Math.max(300,Math.min(1800,Math.round(el.clientWidth-16))));update();const observer=new ResizeObserver(update);observer.observe(el);return()=>observer.disconnect()},[mode,available.length>0]);
  const H=W<640?200:260;
  async function loadSettings(){try{setSettings(await api<MapSettings>("/settings/maps",{cache:"no-store"}));setSettingsFailed(false)}catch{setSettingsFailed(true)}}
  useEffect(()=>{void loadSettings()},[]);
  useEffect(()=>{setSelected(previous=>{const valid=previous.filter(k=>available.some(m=>m.key===k));return valid.length?valid:initial})},[available,initial]);
  useEffect(()=>{setPlaying(false);setCursor(0);setFrom(0);setTo(100);if(makeAxis(data,"time").kind==="points"&&makeAxis(data,"distance").kind!=="points")setXMode("distance")},[data]);
  const fullAxis=useMemo(()=>makeAxis(data,xMode),[data,xMode]);
  const filtered=useMemo(()=>{
    const lo=Math.min(from,to)/100,hi=Math.max(from,to)/100;
    return data.filter((_,i)=>fullAxis.positions[i]>=lo&&fullAxis.positions[i]<=hi);
  },[data,fullAxis,from,to]);
  const mapAnnotations=useMemo(()=>{
    const indices=new Map(data.map((row,i)=>[row,i]));
    return annotations.flatMap(item=>{
      const first=item.start_index??item.point_index;
      if(!Number.isInteger(first))return [item];
      const last=item.end_index??first;
      const visible=filtered.map((row,index)=>({row,index,original:indices.get(row)!})).filter(p=>p.original>=first&&p.original<=last);
      if(!visible.length)return [];
      const start=visible[0],end=visible.at(-1)!;
      return [{...item,start_index:start.index,end_index:end.index,lat:start.row.position_lat,lon:start.row.position_long}];
    });
  },[annotations,data,filtered]);
  const axis=useMemo(()=>makeAxis(filtered,xMode),[filtered,xMode]);
  const route=useMemo(()=>routeSegments(filtered),[filtered]);
  const routePoints=useMemo(()=>route.flat(),[route]);
  // Hover (chart or map) shows a point live; a click, the slider or replay sets the marker it returns to.
  const shown=hover??cursor;
  const current=shown==null?null:Math.max(0,Math.min(filtered.length-1,shown));
  const point=current==null?null:filtered[current];
  const routePoint=useMemo(()=>routePoints.find(p=>p.index===current)??null,[routePoints,current]);
  const active=available.filter(m=>selected.includes(m.key));
  const colorMetric=available.find(m=>m.key===colorKey)??null;
  const readout=point?available.filter(m=>finite(point[m.key])!=null):[];
  const hasTime=makeAxis(data,"time").kind==="time", hasDistance=makeAxis(data,"distance").kind==="distance";
  const timeAxis=useMemo(()=>makeAxis(filtered,"time"),[filtered]);
  useEffect(()=>{
    if(!playing||timeAxis.kind!=="time"||filtered.length<2)return;
    let previous=performance.now();
    const timer=window.setInterval(()=>{const now=performance.now();replayClock.current+=(now-previous)/1000*replaySpeed;previous=now;const first=timeAxis.values[0],last=timeAxis.values.at(-1)!;setCursor(nearestIndex(timeAxis.positions,(replayClock.current-first)/(last-first)));if(replayClock.current>=last)setPlaying(false)},100);
    return()=>window.clearInterval(timer);
  },[playing,replaySpeed,timeAxis,filtered.length]);
  useEffect(()=>{setPlaying(false)},[from,to,xMode]);
  const pick=useCallback((index:number)=>{setPlaying(false);setCursor(index);setHover(null)},[]);
  function replay(){if(playing){setPlaying(false);return}const index=current===filtered.length-1?0:current??0;replayClock.current=timeAxis.values[index]??0;setCursor(index);setPlaying(true)}
  function toggle(key:string){setSelected(previous=>previous.includes(key)?(previous.length>1?previous.filter(k=>k!==key):previous):[...previous,key])}
  function pointerIndex(event:React.PointerEvent<SVGSVGElement>|React.MouseEvent<SVGSVGElement>){
    const matrix=event.currentTarget.getScreenCTM();if(!matrix)return 0;
    const local=new DOMPoint(event.clientX,event.clientY).matrixTransform(matrix.inverse());
    const pad=mode==="stacked"?30:P;
    return nearestIndex(axis.positions,(local.x-pad)/(W-pad*2));
  }
  function move(event:React.PointerEvent<SVGSVGElement>){if(event.pointerType==="mouse")setHover(pointerIndex(event))}
  function axisLabel(index:number){
    const row=filtered[index];if(!row)return "—";
    if(axis.kind==="time")return timeLabel(row.elapsed_s);
    if(axis.kind==="distance")return `${finite(row.distance_km)?.toFixed(2)} km`;
    return `${de?"Punkt":"Point"} ${index+1}`;
  }
  function keySelect(event:React.KeyboardEvent){
    if(!filtered.length)return;const index=current??0;
    if(["ArrowLeft","ArrowRight","Home","End"].includes(event.key)){
      event.preventDefault();pick(event.key==="Home"?0:event.key==="End"?filtered.length-1:Math.max(0,Math.min(filtered.length-1,index+(event.key==="ArrowLeft"?-1:1))));
    }
  }
  function changeRange(value:number,start:boolean){setPlaying(false);if(start)setFrom(value);else setTo(value);setCursor(0);setHover(null)}
  useEffect(()=>{
    function seek(event:Event){const detail=(event as CustomEvent).detail;if(detail?.activityId!==activityId)return;const time=makeAxis(data,"time");if(time.kind!=="time")return;const first=time.values[0],last=time.values.at(-1)!;setPlaying(false);setFrom(0);setTo(100);setXMode("time");setCursor(nearestIndex(time.positions,(detail.elapsed-first)/(last-first)))}
    window.addEventListener("pengucoach-activity-seek",seek);return()=>window.removeEventListener("pengucoach-activity-seek",seek);
  },[activityId,data]);
  useEffect(()=>{
    const requested=new URLSearchParams(window.location.search).get("seek");if(requested==null||!data.length)return;
    const time=makeAxis(data,"time"),elapsed=Number(requested);if(time.kind!=="time"||!Number.isFinite(elapsed))return;
    setXMode("time");setCursor(nearestIndex(time.positions,(elapsed-time.values[0])/(time.values.at(-1)!-time.values[0])));
  },[activityId,data]);
  const steepest=useMemo(()=>{let index=-1,grade=3;filtered.forEach((r,i)=>{const value=finite(r.grade_pct);if(value!=null&&value>grade){grade=value;index=i}});return index},[filtered]);
  const interaction={onPointerMove:move,onPointerLeave:()=>setHover(null),onPointerDown:(event:React.PointerEvent<SVGSVGElement>)=>{if(event.pointerType!=="mouse")pick(pointerIndex(event))},onClick:(event:React.MouseEvent<SVGSVGElement>)=>pick(pointerIndex(event)),onKeyDown:keySelect,tabIndex:0};
  function tickLabel(fraction:number){
    if(!filtered.length)return "";
    const value=axis.values[0]+fraction*(axis.values.at(-1)!-axis.values[0]);
    return axis.kind==="time"?timeLabel(value):axis.kind==="distance"?`${value.toFixed(2)} km`:axisLabel(nearestIndex(axis.positions,fraction));
  }

  if(!data.length)return <div className="activity-chart-empty"><strong>{de?"Keine aufgezeichnete Zeitreihe oder Strecke verfügbar.":"No recorded time series or route available."}</strong><ClientLink prefetch={false} className="text-link" href="/activities">{de?"Datei mit Messwerten oder GPS importieren":"Import a file with readings or GPS"} →</ClientLink></div>;
  const mapShown=routePoints.length>0&&!!settings?.map_enabled&&!googleActive&&!settingsFailed;
  const cursorX=current!=null?(axis.positions[current]??0):null;
  const readoutCard=point?<div className={`chart-readout ${mapShown?"on-map":""}`} aria-live="polite" aria-label={de?"Messwerte an der ausgewählten Stelle":"Measurements at the selected point"}>
      {finite(point.elapsed_s)!=null&&<div><span>{de?"Zeit":"Time"}</span><strong>{timeLabel(point.elapsed_s)}</strong></div>}
      {finite(point.distance_km)!=null&&<div><span>{de?"Distanz":"Distance"}</span><strong>{finite(point.distance_km)!.toFixed(2)} km</strong></div>}
      {readout.map(metric=><div key={metric.key}><span>{de?metric.de:metric.en}</span><strong>{metricLabel(metric,point[metric.key])}</strong></div>)}
    </div>:null;
  const altitude=active.find(m=>m.key==="altitude_m");
  return <div className="activity-explorer" id={activityId?`activity-explorer-${activityId}`:undefined}>
    <div className="chart-toolbar">
      <div className="chart-chip-row" aria-label={de?"Messwerte":"Metrics"}>{available.map(metric=><button type="button" key={metric.key} className={`chart-chip ${selected.includes(metric.key)?"active":""}`} aria-pressed={selected.includes(metric.key)} onClick={()=>toggle(metric.key)}><span className="chart-dot" style={{background:metric.color}}/>{de?metric.de:metric.en}</button>)}<InfoTip label={de?"Wie lese ich das Diagramm?":"How do I read the chart?"} text={de?"Jede Kurve hat ihre eigene Skala. Fahre über Diagramm oder Strecke, um Werte live zu sehen; ein Klick setzt die Markierung. Lücken bleiben offen – es wird nichts dazugerechnet. Die Steigung wird aus Höhe und Distanz geschätzt.":"Each line has its own scale. Hover the chart or the route to see values live; a click sets the marker. Gaps stay open – nothing is filled in. Grade is estimated from elevation and distance."}/></div>
      <div className="chart-segmented"><button type="button" className={mode==="overlay"?"active":""} onClick={()=>setMode("overlay")}>{de?"Überlagert":"Overlay"}</button><button type="button" className={mode==="stacked"?"active":""} onClick={()=>setMode("stacked")}>{de?"Untereinander":"Stacked"}</button></div>
      <div className="chart-segmented"><button type="button" disabled={!hasTime} className={xMode==="time"?"active":""} onClick={()=>setXMode("time")}>{de?"Zeit":"Time"}</button><button type="button" disabled={!hasDistance} className={xMode==="distance"?"active":""} onClick={()=>setXMode("distance")}>{de?"Distanz":"Distance"}</button></div>
    </div>

    {routePoints.length>0&&<section className="route-explorer-panel">
      <div className={`route-view-grid ${googleActive?"google-open":""}`}><div className="route-map-area">
      {settingsFailed?<div className="map-state"><p>{de?"Karten-Einstellungen konnten nicht geladen werden.":"Could not load map settings."}</p><button type="button" className="ghost compact" onClick={loadSettings}>{de?"Erneut laden":"Retry"}</button></div>:!settings?<div className="map-state">{de?"Karten-Einstellungen werden geladen…":"Loading map settings…"}</div>:googleActive?<div className="map-state">{de?"Nach dem Schließen der Straßenansicht erscheint die Streckenkarte wieder.":"Close street-level view to return to the route map."}</div>:settings.map_enabled?<>
        <ActivityRouteMap data={filtered} index={current} colorMetric={colorMetric} onSelect={pick} onHover={setHover} de={de} annotations={mapAnnotations} overlay={readoutCard}/>
        <div className="route-map-controls"><label>{de?"Streckenfarbe":"Route colour"}<select value={colorKey} onChange={e=>setColorKey(e.target.value)}><option value="">{de?"Einheitlich":"Single colour"}</option>{available.map(metric=><option value={metric.key} key={metric.key}>{de?metric.de:metric.en}</option>)}</select></label><ClientLink prefetch={false} className="text-link" href="/settings/maps">{de?"Karten-Einstellungen":"Map settings"}</ClientLink></div>
      </>:<div className="map-state">{de?"Die Streckenkarte ist in deinen Einstellungen deaktiviert.":"The route map is disabled in your settings."}</div>}
      </div><ActivityPanorama settings={settings} point={routePoint} points={routePoints} de={de} onGoogleActive={setGoogleActive}/></div>
    </section>}

    {available.length>0&&(mode==="overlay"?<div className="chart-stage" ref={stage}>
      <svg className="activity-svg" viewBox={`0 0 ${W} ${H}`} role="img" aria-label={de?"Aktivitätsdiagramm. Pfeiltasten wählen eine Stelle.":"Activity chart. Arrow keys select a point."} {...interaction}>
        {TICKS.map(fraction=><line key={`h${fraction}`} x1={P} y1={TOP+fraction*(H-TOP-BOTTOM)} x2={W-P} y2={TOP+fraction*(H-TOP-BOTTOM)} className="chart-grid"/>)}
        {altitude&&<path d={areaPath(filtered,altitude,axis.positions)} className="chart-area" style={{fill:altitude.color}}/>}
        {active.map(metric=><path key={metric.key} d={linePath(filtered,metric,axis.positions,W,H,P,TOP,BOTTOM)} fill="none" stroke={metric.color} strokeWidth="2.2" strokeLinejoin="round" vectorEffect="non-scaling-stroke"/>)}
        {cursorX!=null&&<line x1={P+cursorX*(W-P*2)} y1={TOP-6} x2={P+cursorX*(W-P*2)} y2={H-BOTTOM} className="chart-cursor"/>}
        {cursorX!=null&&point&&active.map(metric=>{const y=valueY(filtered,metric,point[metric.key]);return y==null?null:<circle key={`c${metric.key}`} cx={P+cursorX*(W-P*2)} cy={y} r="5" fill={metric.color} className="chart-cursor-dot" vectorEffect="non-scaling-stroke"/>})}
        {TICKS.map(fraction=><text key={`x${fraction}`} x={P+fraction*(W-P*2)} y={H-8} textAnchor={fraction===0?"start":fraction===1?"end":"middle"} className="chart-axis-label">{tickLabel(fraction)}</text>)}
      </svg>
    </div>:<div className="stacked-charts">{active.map(metric=><MiniPanel key={metric.key} metric={metric} data={filtered} positions={axis.positions} cursor={current} interaction={interaction} de={de}/>)}</div>)}

    <div className="position-row">
      <span className="position-label">{point?axisLabel(current??0):"—"}</span>
      <input className="activity-position-slider" type="range" aria-label={de?"Position im Training":"Workout position"} min="0" max={Math.max(0,filtered.length-1)} step="1" value={current??0} disabled={filtered.length<2} onChange={event=>pick(Number(event.target.value))} aria-valuetext={axisLabel(current??0)}/>
      <span className="position-label end">{filtered.length?axisLabel(filtered.length-1):""}</span>
    </div>
    {!mapShown&&readoutCard}
    {point&&routePoints.length>0&&!routePoint&&<p className="map-status">{de?"An dieser Stelle fehlen GPS-Koordinaten; die Karte zeigt die nächste aufgezeichnete Position.":"This point has no GPS coordinates; the map shows the nearest recorded position."}</p>}

    <div className="replay-controls">
      <button type="button" disabled={timeAxis.kind!=="time"||filtered.length<2} onClick={replay} aria-pressed={playing}>{playing?"Ⅱ Pause":"▶ Replay"}</button>
      <label className="replay-speed"><span className="sr-only">{de?"Wiedergabe-Tempo":"Playback speed"}</span><select value={replaySpeed} onChange={e=>setReplaySpeed(Number(e.target.value))}>{[1,10,30,60,120].map(speed=><option key={speed} value={speed}>{speed}×</option>)}</select></label>
      <button type="button" className="ghost" onClick={()=>{setPlaying(false);setCursor(0);setHover(null)}} disabled={!filtered.length}>↺ {de?"Anfang":"Start"}</button>
      {steepest>=0&&<button type="button" className="ghost" onClick={()=>pick(steepest)}>{de?"Steilste Stelle":"Steepest point"} ↗</button>}
      <details className="range-details">
        <summary>{de?"Analysebereich":"Analysis range"} <span className="muted">{Math.min(from,to)}–{Math.max(from,to)} %</span></summary>
        <div className="range-panel"><div className="dual-range"><input aria-label={de?"Start des Analysebereichs":"Analysis range start"} type="range" min="0" max="100" value={from} onChange={e=>changeRange(Number(e.target.value),true)}/><input aria-label={de?"Ende des Analysebereichs":"Analysis range end"} type="range" min="0" max="100" value={to} onChange={e=>changeRange(Number(e.target.value),false)}/></div><div className="range-actions"><button type="button" className="ghost compact" onClick={()=>{setFrom(0);setTo(100);setCursor(0)}}>{de?"Gesamt":"All"}</button><button type="button" className="ghost compact" onClick={()=>{setFrom(0);setTo(50);setCursor(0)}}>{de?"1. Hälfte":"First half"}</button><button type="button" className="ghost compact" onClick={()=>{setFrom(50);setTo(100);setCursor(0)}}>{de?"2. Hälfte":"Second half"}</button></div></div>
      </details>
    </div>
    {axis.kind==="points"&&<small className="chart-scale-note">{de?"Ohne vollständige Zeit- oder Distanzwerte zeigt die Achse Aufzeichnungspunkte.":"Without complete time or distance values the axis displays recorded points."}</small>}
    {activityId&&routeSegments(data).flat().length>0&&<RouteBriefing activityId={activityId} data={data} pointIndex={point?data.indexOf(point):null} de={de} onAnnotations={setAnnotations} onSelect={index=>{setPlaying(false);setFrom(0);setTo(100);setCursor(index);setHover(null)}}/>}
    {activityId&&<RouteComparison activityId={activityId} start={Math.min(from,to)} end={Math.max(from,to)} axis={axis.kind} de={de} hasRoute={routePoints.length>=12}/>}
  </div>;

  function valueY(rows:Sample[],metric:Metric,raw:unknown){const v=finite(raw);if(v==null)return null;const [lo,hi]=extent(rows,metric.key);return TOP+(hi-v)/(hi-lo)*(H-TOP-BOTTOM)}
  function areaPath(rows:Sample[],metric:Metric,positions:number[]){
    const [lo,hi]=extent(rows,metric.key),base=H-BOTTOM;let path="",lastX=0;const state:{open:number|null}={open:null};
    rows.forEach((row,i)=>{const v=finite(row[metric.key]);const x=P+(positions[i]??0)*(W-P*2);
      if(v==null){if(state.open!=null){path+=` L${lastX.toFixed(1)} ${base} L${state.open.toFixed(1)} ${base} Z`;state.open=null}return}
      const y=TOP+(hi-v)/(hi-lo)*(H-TOP-BOTTOM);if(state.open==null){state.open=x;path+=`M${x.toFixed(1)} ${base} L${x.toFixed(1)} ${y.toFixed(1)}`}else path+=` L${x.toFixed(1)} ${y.toFixed(1)}`;lastX=x});
    if(state.open!=null)path+=` L${lastX.toFixed(1)} ${base} L${state.open.toFixed(1)} ${base} Z`;
    return path;
  }
}

function MiniPanel({metric,data,positions,cursor,interaction,de}:{metric:Metric;data:Sample[];positions:number[];cursor:number|null;interaction:Record<string,unknown>;de:boolean}){
  const W=MINI_W,height=150,padding=30,[lo,hi]=extent(data,metric.key);
  return <div className="mini-panel"><div className="mini-panel-title"><span className="chart-dot" style={{background:metric.color}}/><strong>{de?metric.de:metric.en}</strong><span>{metricLabel(metric,lo)}–{metricLabel(metric,hi)}</span></div><svg className="activity-svg mini" viewBox={`0 0 ${W} ${height}`} role="img" aria-label={de?metric.de:metric.en} {...interaction}><line x1={padding} y1={height/2} x2={W-padding} y2={height/2} className="chart-grid"/><path d={linePath(data,metric,positions,W,height,padding)} fill="none" stroke={metric.color} strokeWidth="2.5" vectorEffect="non-scaling-stroke"/>{cursor!=null&&<line x1={padding+(positions[cursor]??0)*(W-padding*2)} y1={padding/2} x2={padding+(positions[cursor]??0)*(W-padding*2)} y2={height-padding/2} className="chart-cursor"/>}</svg></div>;
}
