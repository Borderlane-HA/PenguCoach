"use client";

import {useCallback,useEffect,useMemo,useRef,useState} from "react";
import ActivityRouteMap from "./ActivityRouteMap";
import ActivityPanorama from "./ActivityPanorama";
import RouteBriefing from "./RouteBriefing";
import RouteComparison from "./RouteComparison";
import {api} from "../lib/api";
import {AxisMode,extent,finite,linePath,makeAxis,MapSettings,METRICS,Metric,metricLabel,nearestIndex,routeSegments,Sample,timeLabel} from "../lib/activityExplorer";

const W=1200,H=330,P=44;
const DEFAULTS=["heart_rate","speed_kmh","altitude_m","power"];
const TICKS=[0,.25,.5,.75,1];

export default function ActivityExplorer({data,lang,activityId}:{data:Sample[];lang:string;activityId?:string}){
  const de=lang!=="en";
  const available=useMemo(()=>METRICS.filter(m=>data.some(row=>finite(row[m.key])!=null)),[data]);
  const initial=useMemo(()=>{const keys=available.filter(m=>DEFAULTS.includes(m.key));return (keys.length?keys:available.slice(0,3)).map(m=>m.key)},[available]);
  const [selected,setSelected]=useState<string[]>([]),[mode,setMode]=useState<"overlay"|"stacked">("overlay"),[xMode,setXMode]=useState<AxisMode>("time");
  const [from,setFrom]=useState(0),[to,setTo]=useState(100),[cursor,setCursor]=useState<number|null>(0),[pinned,setPinned]=useState(false);
  const [annotations,setAnnotations]=useState<Record<string,any>[]>([]);
  const [settings,setSettings]=useState<MapSettings|null>(null),[settingsFailed,setSettingsFailed]=useState(false);
  const [playing,setPlaying]=useState(false),[replaySpeed,setReplaySpeed]=useState(60);
  const replayClock=useRef(0);
  const [colorKey,setColorKey]=useState(""),[googleActive,setGoogleActive]=useState(false);
  async function loadSettings(){try{setSettings(await api<MapSettings>("/settings/maps",{cache:"no-store"}));setSettingsFailed(false)}catch{setSettingsFailed(true)}}
  useEffect(()=>{void loadSettings()},[]);
  useEffect(()=>{setSelected(previous=>{const valid=previous.filter(k=>available.some(m=>m.key===k));return valid.length?valid:initial})},[available,initial]);
  useEffect(()=>{setPlaying(false);setCursor(0);setPinned(false);setFrom(0);setTo(100);if(makeAxis(data,"time").kind==="points"&&makeAxis(data,"distance").kind!=="points")setXMode("distance")},[data]);
  const fullAxis=useMemo(()=>makeAxis(data,xMode),[data,xMode]);
  const filtered=useMemo(()=>{
    const lo=Math.min(from,to)/100,hi=Math.max(from,to)/100;
    return data.filter((_,i)=>fullAxis.positions[i]>=lo&&fullAxis.positions[i]<=hi);
  },[data,fullAxis,from,to]);
  const axis=useMemo(()=>makeAxis(filtered,xMode),[filtered,xMode]);
  const route=useMemo(()=>routeSegments(filtered),[filtered]);
  const routePoints=useMemo(()=>route.flat(),[route]);
  const current=cursor==null?null:Math.max(0,Math.min(filtered.length-1,cursor));
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
  const pick=useCallback((index:number)=>{setPlaying(false);setCursor(index);setPinned(true)},[]);
  function replay(){if(playing){setPlaying(false);return}const index=current===filtered.length-1?0:current??0;replayClock.current=timeAxis.values[index]??0;setCursor(index);setPinned(true);setPlaying(true)}
  function toggle(key:string){setSelected(previous=>previous.includes(key)?(previous.length>1?previous.filter(k=>k!==key):previous):[...previous,key])}
  function pointerIndex(event:React.PointerEvent<SVGSVGElement>|React.MouseEvent<SVGSVGElement>){
    const matrix=event.currentTarget.getScreenCTM();if(!matrix)return 0;
    const local=new DOMPoint(event.clientX,event.clientY).matrixTransform(matrix.inverse());
    const pad=mode==="stacked"?30:P;
    return nearestIndex(axis.positions,(local.x-pad)/(W-pad*2));
  }
  function move(event:React.PointerEvent<SVGSVGElement>){if(!pinned)setCursor(pointerIndex(event))}
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
    }else if(event.key==="Enter"){event.preventDefault();setPinned(value=>!value)}
  }
  function changeRange(value:number,start:boolean){setPlaying(false);if(start)setFrom(value);else setTo(value);setCursor(0);setPinned(false)}
  useEffect(()=>{
    function seek(event:Event){const detail=(event as CustomEvent).detail;if(detail?.activityId!==activityId)return;const time=makeAxis(data,"time");if(time.kind!=="time")return;const first=time.values[0],last=time.values.at(-1)!;setPlaying(false);setFrom(0);setTo(100);setXMode("time");setPinned(true);setCursor(nearestIndex(time.positions,(detail.elapsed-first)/(last-first)))}
    window.addEventListener("pengucoach-activity-seek",seek);return()=>window.removeEventListener("pengucoach-activity-seek",seek);
  },[activityId,data]);
  useEffect(()=>{
    const requested=new URLSearchParams(window.location.search).get("seek");if(requested==null||!data.length)return;
    const time=makeAxis(data,"time"),elapsed=Number(requested);if(time.kind!=="time"||!Number.isFinite(elapsed))return;
    setXMode("time");setPinned(true);setCursor(nearestIndex(time.positions,(elapsed-time.values[0])/(time.values.at(-1)!-time.values[0])));
  },[activityId,data]);
  const steepest=useMemo(()=>{let index=-1,grade=3;filtered.forEach((r,i)=>{const value=finite(r.grade_pct);if(value!=null&&value>grade){grade=value;index=i}});return index},[filtered]);
  const interaction={onPointerMove:move,onPointerDown:(event:React.PointerEvent<SVGSVGElement>)=>{if(event.pointerType!=="mouse")pick(pointerIndex(event))},onClick:(event:React.MouseEvent<SVGSVGElement>)=>pick(pointerIndex(event)),onKeyDown:keySelect,tabIndex:0};
  function tickLabel(fraction:number){
    if(!filtered.length)return "";
    const value=axis.values[0]+fraction*(axis.values.at(-1)!-axis.values[0]);
    return axis.kind==="time"?timeLabel(value):axis.kind==="distance"?`${value.toFixed(2)} km`:axisLabel(nearestIndex(axis.positions,fraction));
  }

  if(!data.length)return <div className="activity-chart-empty"><strong>{de?"Keine aufgezeichnete Zeitreihe oder Strecke verfügbar.":"No recorded time series or route available."}</strong><a className="text-link" href="/activities">{de?"Datei mit Messwerten oder GPS importieren":"Import a file with readings or GPS"} →</a></div>;
  return <div className="activity-explorer" id={activityId?`activity-explorer-${activityId}`:undefined}>
    <div className="chart-toolbar">
      <div className="chart-chip-row" aria-label={de?"Messwerte":"Metrics"}>{available.map(metric=><button type="button" key={metric.key} className={`chart-chip ${selected.includes(metric.key)?"active":""}`} aria-pressed={selected.includes(metric.key)} onClick={()=>toggle(metric.key)}><span className="chart-dot" style={{background:metric.color}}/>{de?metric.de:metric.en}</button>)}</div>
      <div className="chart-segmented"><button type="button" className={mode==="overlay"?"active":""} onClick={()=>setMode("overlay")}>{de?"Überlagert":"Overlay"}</button><button type="button" className={mode==="stacked"?"active":""} onClick={()=>setMode("stacked")}>{de?"Untereinander":"Stacked"}</button></div>
      <div className="chart-segmented"><button type="button" disabled={!hasTime} className={xMode==="time"?"active":""} onClick={()=>setXMode("time")}>{de?"Zeit":"Time"}</button><button type="button" disabled={!hasDistance} className={xMode==="distance"?"active":""} onClick={()=>setXMode("distance")}>{de?"Distanz":"Distance"}</button></div>
    </div>

    {routePoints.length>0&&<section className="route-explorer-panel">
      <div className="between"><div><strong>{de?"Deine aufgezeichnete Strecke":"Your recorded route"}</strong><small className="panorama-subtitle">{de?"Diagramm bewegen oder eine Stelle auf der Strecke anklicken":"Move over the chart or click a point on the route"}</small></div><a className="text-link" href="/settings/maps">{de?"Karten-Einstellungen":"Map settings"}</a></div>
      <div className={`route-view-grid ${googleActive?"google-open":""}`}><div className="route-map-area">
      {settingsFailed?<div className="map-state"><p>{de?"Karten-Einstellungen konnten nicht geladen werden.":"Could not load map settings."}</p><button type="button" className="ghost compact" onClick={loadSettings}>{de?"Erneut laden":"Retry"}</button></div>:!settings?<div className="map-state">{de?"Karten-Einstellungen werden geladen…":"Loading map settings…"}</div>:googleActive?<div className="map-state">{de?"Nach dem Schließen der Straßenansicht erscheint die Streckenkarte wieder.":"Close street-level view to return to the route map."}</div>:settings.map_enabled?<>
        <div className="route-map-controls"><label>{de?"Streckenfarbe":"Route color"}<select value={colorKey} onChange={e=>setColorKey(e.target.value)}><option value="">{de?"Einheitlich":"Single color"}</option>{available.map(metric=><option value={metric.key} key={metric.key}>{de?metric.de:metric.en}</option>)}</select></label><span className="muted">{routePoints.length.toLocaleString(de?"de-DE":"en-GB")} {de?"GPS-Punkte":"GPS points"}{route.length>1?` · ${route.length} ${de?"Abschnitte":"segments"}`:""}</span></div>
        <ActivityRouteMap data={filtered} index={current} colorMetric={colorMetric} onSelect={pick} de={de} annotations={annotations}/>
      </>:<div className="map-state">{de?"Die Streckenkarte ist in deinen Einstellungen deaktiviert.":"The route map is disabled in your settings."}</div>}
      </div><ActivityPanorama settings={settings} point={routePoint} points={routePoints} de={de} onGoogleActive={setGoogleActive}/></div>
    </section>}

    {available.length>0&&(mode==="overlay"?<div className="chart-stage">
      <svg className="activity-svg" viewBox={`0 0 ${W} ${H}`} role="img" aria-label={de?"Aktivitätsdiagramm. Pfeiltasten wählen eine Stelle, Enter fixiert oder löst die Auswahl.":"Activity chart. Arrow keys select a point; Enter locks or unlocks the selection."} {...interaction}>
        {TICKS.map(fraction=><line key={`g${fraction}`} x1={P+fraction*(W-P*2)} y1={P} x2={P+fraction*(W-P*2)} y2={H-P} className="chart-grid"/>)}
        {TICKS.map(fraction=><line key={`h${fraction}`} x1={P} y1={P+fraction*(H-P*2)} x2={W-P} y2={P+fraction*(H-P*2)} className="chart-grid"/>)}
        {active.map(metric=><path key={metric.key} d={linePath(filtered,metric,axis.positions,W,H,P)} fill="none" stroke={metric.color} strokeWidth="3" strokeLinejoin="round" vectorEffect="non-scaling-stroke"/>)}
        {current!=null&&<line x1={P+(axis.positions[current]??0)*(W-P*2)} y1={P} x2={P+(axis.positions[current]??0)*(W-P*2)} y2={H-P} className="chart-cursor"/>}
        {TICKS.map(fraction=><text key={`x${fraction}`} x={P+fraction*(W-P*2)} y={H-10} textAnchor={fraction===0?"start":fraction===1?"end":"middle"} className="chart-axis-label">{tickLabel(fraction)}</text>)}
      </svg>
      <div className="chart-scale-note">{de?"Jede Kurve nutzt ihre eigene Skala. Die Werte unten zeigen die ausgewählte Stelle; Datenlücken bleiben offen.":"Each line has its own scale. Values below describe the selected point; missing data leaves gaps."}</div>
    </div>:<div className="stacked-charts">{active.map(metric=><MiniPanel key={metric.key} metric={metric} data={filtered} positions={axis.positions} cursor={current} interaction={interaction} de={de}/>)}</div>)}

    <div className="replay-controls"><button type="button" disabled={timeAxis.kind!=="time"||filtered.length<2} onClick={replay} aria-pressed={playing}>{playing?(de?"Ⅱ Pause":"Ⅱ Pause"):(de?"▶ Replay":"▶ Replay")}</button><button type="button" className="ghost" onClick={()=>{setPlaying(false);setCursor(0);setPinned(true)}} disabled={!filtered.length}>{de?"↺ Start":"↺ Start"}</button>{steepest>=0&&<button type="button" className="ghost" onClick={()=>pick(steepest)}>{de?"Steilste Stelle":"Steepest point"} ↗</button>}<label>{de?"Geschwindigkeit":"Playback speed"}<select value={replaySpeed} onChange={e=>setReplaySpeed(Number(e.target.value))}>{[1,10,30,60,120].map(speed=><option key={speed} value={speed}>{speed}×</option>)}</select></label><span className="muted">{timeAxis.kind!=="time"?(de?"Replay braucht aufgezeichnete Zeitangaben.":"Replay needs recorded times."):(de?"Karte & Messwerte folgen der Aufnahme. Straßenansicht an der Pausenposition.":"Map & readings follow the recording. Street-level view at the paused position.")}</span></div>
    <div className="route-point-controls"><div><strong>{point?axisLabel(current??0):de?"Keine Punkte im Analysebereich":"No points in analysis range"}</strong><small>{de?"Klick fixiert die Auswahl. Der Regler funktioniert auch per Finger.":"Click to lock the selection. The slider also works with touch."}</small></div><button type="button" className="ghost compact" onClick={()=>{setPlaying(false);setPinned(!pinned)}} disabled={!point} aria-pressed={pinned}>{pinned?(de?"Auswahl lösen":"Unlock selection"):(de?"Auswahl fixieren":"Lock selection")}</button></div>
    <input className="activity-position-slider" type="range" aria-label={de?"Position im Training":"Workout position"} min="0" max={Math.max(0,filtered.length-1)} step="1" value={current??0} disabled={filtered.length<2} onChange={event=>pick(Number(event.target.value))} aria-valuetext={axisLabel(current??0)}/>
    <div className="chart-readout" aria-label={de?"Messwerte an der ausgewählten Stelle":"Measurements at the selected point"}>
      {point&&finite(point.elapsed_s)!=null&&<div><span>{de?"Zeit":"Time"}</span><strong>{timeLabel(point.elapsed_s)}</strong></div>}
      {point&&finite(point.distance_km)!=null&&<div><span>{de?"Distanz":"Distance"}</span><strong>{finite(point.distance_km)!.toFixed(2)} km</strong></div>}
      {readout.map(metric=><div key={metric.key}><span>{de?metric.de:metric.en}</span><strong>{metricLabel(metric,point![metric.key])}</strong></div>)}
    </div>
    {point&&routePoints.length>0&&!routePoint&&<p className="map-status">{de?"An dieser Stelle fehlen GPS-Koordinaten; der Kartenmarker und die Straßenansicht sind deshalb nicht verfügbar.":"This point has no GPS coordinates; its map marker and street-level view are unavailable."}</p>}
    {available.some(m=>m.key==="grade_pct")&&<small className="chart-scale-note">{de?"Steigung wird geglättet aus Höhe und Distanz berechnet und ist eine Näherung.":"Grade is estimated from smoothed elevation and distance."}</small>}
    {axis.kind==="points"&&<small className="chart-scale-note">{de?"Ohne vollständige Zeit- oder Distanzwerte zeigt die Achse Aufzeichnungspunkte.":"Without complete time or distance values the axis displays recorded points."}</small>}
    <div className="range-panel"><div className="between"><strong>{de?"Analysebereich":"Analysis range"}</strong><span className="muted">{Math.min(from,to)}–{Math.max(from,to)} %</span></div><div className="dual-range"><input aria-label={de?"Start des Analysebereichs":"Analysis range start"} type="range" min="0" max="100" value={from} onChange={e=>changeRange(Number(e.target.value),true)}/><input aria-label={de?"Ende des Analysebereichs":"Analysis range end"} type="range" min="0" max="100" value={to} onChange={e=>changeRange(Number(e.target.value),false)}/></div><div className="range-actions"><button type="button" className="ghost compact" onClick={()=>{setFrom(0);setTo(100);setCursor(0)}}>{de?"Gesamt":"All"}</button><button type="button" className="ghost compact" onClick={()=>{setFrom(0);setTo(50);setCursor(0)}}>{de?"1. Hälfte":"First half"}</button><button type="button" className="ghost compact" onClick={()=>{setFrom(50);setTo(100);setCursor(0)}}>{de?"2. Hälfte":"Second half"}</button></div></div>
    {activityId&&routeSegments(data).flat().length>0&&<RouteBriefing activityId={activityId} data={data} pointIndex={point?data.indexOf(point):null} de={de} onAnnotations={setAnnotations} onSelect={index=>{setPlaying(false);setFrom(0);setTo(100);setCursor(index);setPinned(true)}}/>}
    {activityId&&<RouteComparison activityId={activityId} start={Math.min(from,to)} end={Math.max(from,to)} axis={axis.kind} de={de} hasRoute={routePoints.length>=12}/>}
  </div>;
}

function MiniPanel({metric,data,positions,cursor,interaction,de}:{metric:Metric;data:Sample[];positions:number[];cursor:number|null;interaction:Record<string,unknown>;de:boolean}){
  const height=150,padding=30,[lo,hi]=extent(data,metric.key);
  return <div className="mini-panel"><div className="mini-panel-title"><span className="chart-dot" style={{background:metric.color}}/><strong>{de?metric.de:metric.en}</strong><span>{metricLabel(metric,lo)}–{metricLabel(metric,hi)}</span></div><svg className="activity-svg mini" viewBox={`0 0 ${W} ${height}`} role="img" aria-label={de?metric.de:metric.en} {...interaction}><line x1={padding} y1={height/2} x2={W-padding} y2={height/2} className="chart-grid"/><path d={linePath(data,metric,positions,W,height,padding)} fill="none" stroke={metric.color} strokeWidth="2.5" vectorEffect="non-scaling-stroke"/>{cursor!=null&&<line x1={padding+(positions[cursor]??0)*(W-padding*2)} y1={padding/2} x2={padding+(positions[cursor]??0)*(W-padding*2)} y2={height-padding/2} className="chart-cursor"/>}</svg></div>;
}
