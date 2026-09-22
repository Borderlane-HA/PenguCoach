"use client";

import {useEffect,useMemo,useState} from "react";
import {api} from "../lib/api";
import {bi,type Lang} from "../lib/i18n";

type AnyObj=Record<string,any>;
const sleep=(ms:number)=>new Promise(r=>setTimeout(r,ms));
const DAYS_DE=["Mo","Di","Mi","Do","Fr","Sa","So"];
const DAYS_EN=["Mon","Tue","Wed","Thu","Fri","Sat","Sun"];

function localDateString(value:Date){
  const y=value.getFullYear(),m=String(value.getMonth()+1).padStart(2,"0"),d=String(value.getDate()).padStart(2,"0");
  return `${y}-${m}-${d}`;
}
function defaultMonday(){
  const now=new Date();now.setHours(12,0,0,0);
  const iso=((now.getDay()+6)%7)+1;
  const add=iso===1?0:8-iso;
  now.setDate(now.getDate()+add);
  return localDateString(now);
}
function isMonday(value:string){if(!value)return false;const d=new Date(`${value}T12:00:00`);return d.getDay()===1}
function sportIcon(sport:string){return ({running:"🏃",cycling:"🚴",swimming:"🏊",walking:"🚶",hiking:"🥾",strength:"🏋️"} as AnyObj)[sport]??"●"}
function stepText(step:AnyObj,de:boolean):string{
  if(step.type==="repeat")return `${step.repeat}× (${(step.steps??[]).map((x:AnyObj)=>stepText(x,de)).join(" / ")})`;
  const label=({warmup:de?"Warm-up":"Warm-up",work:de?"Hauptteil":"Main",interval:de?"Intervall":"Interval",recovery:de?"Erholung":"Recovery",cooldown:"Cool-down",rest:de?"Pause":"Rest"} as AnyObj)[step.type]??step.type;
  const end=step.duration_seconds?`${Math.round(step.duration_seconds/60)} min`:step.distance_meters?`${step.distance_meters>=1000?(step.distance_meters/1000).toFixed(1)+" km":step.distance_meters+" m"}`:"";
  const target=step.target?.type==="heart_rate_zone"?`${de?"HF":"HR"} Z${step.target.zone}`:step.target?.type==="power_zone"?`Power Z${step.target.zone}`:"";
  return [label,end,target].filter(Boolean).join(" · ");
}

export default function TrainingPlanCalendar({result,lang}:{result:AnyObj,lang:Lang}){
  const de=lang!=="en";
  const meta=result?.metadata??{};
  const plan=meta.structured_plan as AnyObj|undefined;
  const runId=result?.id??result?.run_id;
  const[startDate,setStartDate]=useState(defaultMonday());
  const[garmin,setGarmin]=useState<AnyObj|null>(null);
  const[preview,setPreview]=useState<AnyObj|null>(null);
  const[selected,setSelected]=useState<Set<string>>(new Set());
  const[busy,setBusy]=useState(false),[message,setMessage]=useState(""),[error,setError]=useState("");
  const[expanded,setExpanded]=useState<Set<string>>(new Set());
  const exportJobKey="pengucoach_garmin_workout_export_job";

  const sessions=useMemo(()=>Array.isArray(plan?.sessions)?plan.sessions:[],[plan]);
  useEffect(()=>{
    if(!plan||!runId)return;
    setSelected(new Set(sessions.filter((x:AnyObj)=>!x.optional).map((x:AnyObj)=>x.id)));
    void api<AnyObj>("/garmin/workout-export/status").then(setGarmin).catch(()=>setGarmin(null));
    const job=localStorage.getItem(exportJobKey);if(job){setBusy(true);void poll(job)}
  // eslint-disable-next-line react-hooks/exhaustive-deps
  },[runId]);
  useEffect(()=>{if(plan&&runId&&isMonday(startDate))void loadPreview()},[runId,startDate]);

  async function loadPreview(){
    try{setError("");const p=await api<AnyObj>("/garmin/workout-export/preview",{method:"POST",body:JSON.stringify({plan_run_id:runId,start_date:startDate})});setPreview(p)}
    catch(e){setPreview(null);setError(e instanceof Error?e.message:String(e))}
  }
  async function poll(jobId:string){
    setMessage(de?"Garmin-Export läuft…":"Garmin export is running…");
    for(let i=0;i<900;i++){
      try{const j=await api<AnyObj>(`/jobs/${jobId}`);if(j.ready){localStorage.removeItem(exportJobKey);setBusy(false);if(j.successful){const r=j.result??{};const extras=[r.already_exported?`${r.already_exported} ${de?"bereits vorhanden":"already present"}`:"",r.unsupported?`${r.unsupported} ${de?"nur im Plan":"plan only"}`:"",r.failed?`${r.failed} ${de?"fehlgeschlagen":"failed"}`:""].filter(Boolean).join(" · ");setMessage(`${r.exported??0} ${de?"Einheiten zu Garmin übertragen":"sessions exported to Garmin"}${extras?` · ${extras}`:""}.`);await loadPreview();return}setError(j.error||"Garmin export failed");return}setMessage(j.progress?.message??message)}catch{}await sleep(1200)
    }
    setBusy(false);
  }
  async function exportSelected(){
    if(!runId||!isMonday(startDate)||busy)return;
    const allowed=new Set((preview?.items??[]).filter((x:AnyObj)=>x.exportable&&x.export_status!=="exported").map((x:AnyObj)=>x.session_id));
    const ids=[...selected].filter(id=>allowed.has(id));
    if(!ids.length){setMessage(de?"Keine neuen exportierbaren Einheiten ausgewählt.":"No new exportable sessions selected.");return}
    if(!confirm(de?`${ids.length} ausgewählte Trainingseinheiten im Garmin-Connect-Kalender anlegen?`:`Create ${ids.length} selected training sessions in the Garmin Connect calendar?`))return;
    setError("");setBusy(true);setMessage(de?"Export wird vorbereitet…":"Preparing export…");
    try{const r=await api<AnyObj>("/garmin/workout-export/jobs",{method:"POST",body:JSON.stringify({plan_run_id:runId,start_date:startDate,session_ids:ids})});localStorage.setItem(exportJobKey,r.task_id);void poll(r.task_id)}
    catch(e){setBusy(false);setError(e instanceof Error?e.message:String(e))}
  }
  function toggle(id:string){setSelected(prev=>{const next=new Set(prev);next.has(id)?next.delete(id):next.add(id);return next})}
  function toggleExpanded(id:string){setExpanded(prev=>{const next=new Set(prev);next.has(id)?next.delete(id):next.add(id);return next})}

  if(!plan)return <div className="plan-calendar-unavailable"><strong>{bi(lang,"Kalenderansicht für diesen Plan nicht verfügbar","Calendar view is not available for this plan")}</strong><p className="muted">{bi(lang,"Dieser Plan wurde mit einer älteren PenguCoach-Version oder ohne gültige strukturierte Plandaten erzeugt. Neu generierte Pläne können direkt für Garmin vorbereitet werden.","This plan was created with an older PenguCoach version or without valid structured plan data. Newly generated plans can be prepared directly for Garmin.")}</p></div>;

  const days=de?DAYS_DE:DAYS_EN;
  const byWeek=Array.from({length:plan.weeks??0},(_,i)=>sessions.filter((x:AnyObj)=>x.week===i+1));
  const previewMap=new Map((preview?.items??[]).map((x:AnyObj)=>[x.session_id,x]));
  const newSelected=[...selected].filter(id=>{const x=previewMap.get(id) as AnyObj|undefined;return x?.exportable&&x?.export_status!=="exported"}).length;

  return <div className="training-calendar-wrap">
    <div className="training-calendar-toolbar">
      <div><span className="eyebrow">PLAN CALENDAR</span><h3>{plan.title}</h3><p className="muted">{plan.summary}</p></div>
      <div className="training-calendar-start"><label>{bi(lang,"Montag · Woche 1","Monday · week 1")}<input type="date" value={startDate} onChange={e=>setStartDate(e.target.value)}/></label>{!isMonday(startDate)&&<small className="status-warn">{bi(lang,"Bitte einen Montag wählen.","Please select a Monday.")}</small>}</div>
    </div>

    <div className="training-calendar-actions"><button type="button" className="ghost" onClick={()=>setSelected(new Set((preview?.items??sessions).filter((x:AnyObj)=>x.exportable!==false&&!x.optional).map((x:AnyObj)=>x.session_id??x.id)))}>{bi(lang,"Pflichteinheiten","Required sessions")}</button><button type="button" className="ghost" onClick={()=>setSelected(new Set((preview?.items??sessions).filter((x:AnyObj)=>x.exportable!==false).map((x:AnyObj)=>x.session_id??x.id)))}>{bi(lang,"Alle möglichen","All exportable")}</button><button type="button" className="ghost" onClick={()=>setSelected(new Set())}>{bi(lang,"Auswahl leeren","Clear selection")}</button></div>

    <div className="training-calendar-weeks">{byWeek.map((weekSessions:AnyObj[],wi:number)=><section className="training-calendar-week" key={wi}><div className="training-week-label"><strong>{bi(lang,"Woche","Week")} {wi+1}</strong><small>{weekSessions.reduce((n,x)=>n+(x.duration_min??0),0)} min</small></div><div className="training-week-grid">{days.map((day,di)=>{const session=weekSessions.find(x=>x.day===di+1);if(!session)return <div className="training-day empty" key={day}><span>{day}</span><small>—</small></div>;const p=previewMap.get(session.id) as AnyObj|undefined;const disabled=p&&!p.exportable;const exported=p?.export_status==="exported";const exportError=p?.export_status==="error";return <div className={`training-day ${selected.has(session.id)?"selected":""} ${disabled?"unsupported":""} ${exported?"exported":""} ${exportError?"export-error":""}`} key={day}><div className="training-day-top"><span>{day}{p?.date?<small>{new Date(`${p.date}T12:00:00`).toLocaleDateString(de?"de-DE":"en-GB",{day:"2-digit",month:"2-digit"})}</small>:null}</span><input aria-label={bi(lang,"Einheit auswählen","Select session")} type="checkbox" disabled={Boolean(disabled||exported)} checked={selected.has(session.id)&&!disabled&&!exported} onChange={()=>toggle(session.id)}/></div><button type="button" className="training-session-open" onClick={()=>toggleExpanded(session.id)}><span className="training-sport-icon">{sportIcon(session.sport)}</span><strong>{session.name}</strong><small>{session.duration_min} min · {session.sport}{session.optional?` · ${bi(lang,"optional","optional")}`:""}</small></button>{exported&&<span className="training-export-badge ok">✓ Garmin</span>}{exportError&&<span className="training-export-badge error">{bi(lang,"Exportfehler","Export error")}</span>}{disabled&&<span className="training-export-badge warn">{bi(lang,"Nur Plan","Plan only")}</span>}{expanded.has(session.id)&&<div className="training-session-detail">{session.notes&&<p>{session.notes}</p>}{(session.steps??[]).map((step:AnyObj,i:number)=><div key={i}>• {stepText(step,de)}</div>)}{(session.strength_exercises??[]).map((ex:AnyObj,i:number)=><div key={`s${i}`}>• {ex.name}: {ex.sets}×{ex.reps} · {ex.rest_seconds}s</div>)}{p?.reason&&<small className="status-warn">{p.reason}</small>}{p?.error&&<small className="status-bad">{p.error}</small>}</div>}</div>})}</div></section>)}</div>

    <div className={`garmin-export-panel ${garmin?.enabled&&garmin?.connected?"ready":""}`}><div><span className="eyebrow">GARMIN CALENDAR</span><strong>{garmin?.connected?bi(lang,"Garmin verbunden","Garmin connected"):bi(lang,"Garmin nicht verbunden","Garmin not connected")}</strong><small>{garmin?.enabled?bi(lang,"Workout-Export freigegeben · Datensync bleibt read-only","Workout export enabled · data sync remains read-only"):bi(lang,"Workout-Export ist standardmäßig gesperrt","Workout export is disabled by default")}</small></div><div className="garmin-export-cta"><span>{newSelected} {bi(lang,"neue Einheiten ausgewählt","new sessions selected")}</span>{(!garmin?.connected||!garmin?.enabled)&&<a className="button ghost" href="/settings/garmin">{bi(lang,"Garmin-Einstellungen","Garmin settings")}</a>}<button type="button" disabled={busy||!garmin?.connected||!garmin?.enabled||!isMonday(startDate)||newSelected===0} onClick={exportSelected}>{busy?bi(lang,"Übertragung läuft…","Exporting…"):bi(lang,"Zu Garmin übertragen","Export to Garmin")}</button></div></div>
    {message&&<div className="ai-toast">{message}</div>}{error&&<div className="status-bad">{error}</div>}
    <p className="muted training-calendar-note">{bi(lang,"PenguCoach legt einzelne strukturierte Workouts im Garmin-Connect-Kalender an. Es wird kein eigener Garmin-Coach-Plan erzeugt. Bereits erfolgreich exportierte Einheit/Datum-Kombinationen werden nicht dupliziert.","PenguCoach creates individual structured workouts in the Garmin Connect calendar. It does not create a Garmin Coach plan. Successfully exported session/date combinations are not duplicated.")}</p>
  </div>;
}
