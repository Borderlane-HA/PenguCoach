"use client";
import {useEffect,useRef,useState} from "react";
import {api} from "../lib/api";
import {bi,type Lang} from "../lib/i18n";
import AssistantDialog,{AssistantIcon} from "./TodayAssistant";
type O=Record<string,any>;

export default function ReflectionAssistant({data,lang}:{data:O|null;lang:Lang}){
 const dialog=useRef<HTMLDialogElement>(null),heading=useRef<HTMLHeadingElement>(null),seq=useRef(0),request=useRef<AbortController|null>(null);
 const[records,setRecords]=useState<Record<string,O>>({}),[statusLoading,setStatusLoading]=useState(true),[statusError,setStatusError]=useState(false),[refresh,setRefresh]=useState(0);
 const[chosen,setChosen]=useState(""),[feeling,setFeeling]=useState(""),[note,setNote]=useState(""),[step,setStep]=useState(0),[loading,setLoading]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState("");
 const activities:O[]=data?.today_activities||[],ids=activities.map(a=>a.id).join("|"),activity=activities.find(a=>a.id===chosen);
 const ready=!!data?.briefing_ready;
 const tomorrow=data?.date?new Date(new Date(`${data.date}T12:00:00Z`).getTime()+86400000).toISOString().slice(0,10):null;
 const next:O[]=(data?.upcoming||[]).filter((s:O)=>s.date===tomorrow);
 const reviewed=activities.filter(a=>records[a.id]?.feeling).length,complete=activities.length>0&&reviewed===activities.length;
 const steps=activities.length?[bi(lang,"Aktivität","Activity"),bi(lang,"Befinden","Feeling"),bi(lang,"Abschluss","Wrap-up")]:[bi(lang,"Heute","Today"),bi(lang,"Morgen","Tomorrow")];
 const feelings=[['easy',bi(lang,"Zu leicht","Too easy")],['right',bi(lang,"Passend","About right")],['hard',bi(lang,"Zu schwer","Too hard")]];
 useEffect(()=>{
  const controller=new AbortController();setStatusLoading(true);setStatusError(false);setRecords({});
  if(!ready)return()=>controller.abort();
  void Promise.all(activities.map(async a=>{
   try{return [a.id,await api<O>(`/coach/feedback/${a.id}`,{signal:controller.signal})] as const}catch(e){if(!controller.signal.aborted)setStatusError(true);return [a.id,{}] as const}
  })).then(rows=>{if(!controller.signal.aborted){setRecords(Object.fromEntries(rows));setStatusLoading(false)}});
  return()=>controller.abort();
 },[data?.date,ids,ready,refresh]);
 useEffect(()=>{const update=()=>setRefresh(n=>n+1);window.addEventListener("pengucoach-feedback-updated",update);window.addEventListener("focus",update);return()=>{seq.current++;request.current?.abort();window.removeEventListener("pengucoach-feedback-updated",update);window.removeEventListener("focus",update)}},[]);
 async function loadActivity(id:string){
  const current=++seq.current;request.current?.abort();const controller=new AbortController();request.current=controller;
  setChosen(id);setFeeling("");setNote("");setError("");setLoading(true);
  try{const saved=await api<O>(`/coach/feedback/${id}`,{signal:controller.signal});if(current===seq.current){setFeeling(saved.feeling||"");setNote(saved.comment||"");setRecords(v=>({...v,[id]:saved}))}}
  catch(e){if(current===seq.current)setError(bi(lang,"Das bisherige Feedback konnte nicht geladen werden. Bitte erneut versuchen.","Could not load existing feedback. Please try again."))}
  finally{if(current===seq.current)setLoading(false)}
 }
 function open(){setStep(0);setError("");setChosen("");setFeeling("");setNote("");dialog.current?.showModal();if(activities.length)void loadActivity((activities.find(a=>!records[a.id]?.feeling)||activities[0]).id)}
 function navigate(nextStep:number){setStep(nextStep);requestAnimationFrame(()=>{dialog.current?.scrollTo({top:0});heading.current?.focus()})}
 function close(){seq.current++;request.current?.abort();setLoading(false);setError("")}
 async function save(){
  if(!activity||!feeling||loading)return;setBusy(true);setError("");const id=activity.id;
  try{
   const previous=await api<O>(`/coach/feedback/${id}`);
   const updated=await api<O>(`/coach/feedback/${id}`,{method:"PUT",body:JSON.stringify({feeling,comment:note,exertion:previous.exertion??null,discomfort:previous.discomfort||""})});
   setRecords(v=>({...v,[id]:{...previous,...updated,feeling,comment:note}}));dialog.current?.close();
   window.dispatchEvent(new CustomEvent("pengucoach-feedback-updated",{detail:{activityId:id}}));
  }catch(e){setError(bi(lang,"Speichern fehlgeschlagen. Dein Feedback bleibt hier erhalten.","Could not save. Your feedback is kept here."))}finally{setBusy(false)}
 }
 const state=complete?"complete":reviewed?"partial":"empty";
 const matched=activity&&(data?.today_comparison||[]).some((s:O)=>s.status==="matched"&&s.activity_id===activity.id);
 return <><button type="button" className={`today-assistant-tile reflection-tile status-${state}`} disabled={!ready} aria-haspopup="dialog" aria-controls="today-reflection-assistant" data-reflection-status={statusLoading?"loading":statusError?"unknown":state} onClick={open}>
  <AssistantIcon kind="reflection" complete={complete&&!statusLoading&&!statusError}/><span className="assistant-tile-copy"><span className="assistant-tile-heading"><strong>{bi(lang,"Dein Tagesabschluss","Your daily wrap-up")}</strong><span className="assistant-status">{!ready||statusLoading?bi(lang,"Wird geladen …","Loading …"):statusError?bi(lang,"Status offen","Status unknown"):complete?bi(lang,"Abgeschlossen","Complete"):reviewed?`${reviewed}/${activities.length} ${bi(lang,"erfasst","recorded")}`:bi(lang,"Noch offen","Not started")}</span></span><small>{activities.length?`${activities.length} ${bi(lang,"Aktivitäten · Feedback & Ausblick","activities · feedback and outlook")}`:bi(lang,"Dein Tag und morgen – auch ohne Training.","Today and tomorrow – even without training.")}</small><span className="assistant-tile-action">{complete?bi(lang,"Abschluss ansehen & ändern","View and edit wrap-up"):bi(lang,"Tagesabschluss starten","Start daily wrap-up")} <span aria-hidden="true">→</span></span></span>
 </button><AssistantDialog dialogRef={dialog} id="today-reflection-assistant" title={bi(lang,"Dein Tagesabschluss","Your daily wrap-up")} steps={steps} step={step} lang={lang} busy={busy} onClose={close} footer={<><button type="button" className="ghost" disabled={busy} onClick={()=>step?navigate(step-1):dialog.current?.close()}>{step?bi(lang,"Zurück","Back"):bi(lang,"Abbrechen","Cancel")}</button>{step<steps.length-1?<button type="button" disabled={busy||loading||!!error||(step===1&&activities.length>0&&!feeling)} onClick={()=>navigate(step+1)}>{bi(lang,"Weiter","Next")} →</button>:activities.length?<button type="button" disabled={busy||loading||!feeling} onClick={()=>void save()}>{busy?bi(lang,"Wird gespeichert …","Saving …"):bi(lang,"Tagesfeedback speichern","Save daily feedback")}</button>:<button type="button" onClick={()=>dialog.current?.close()}>{bi(lang,"Fertig","Done")}</button>}</>}>
  <fieldset disabled={busy||loading}><h3 ref={heading} tabIndex={-1}>{step===0?bi(lang,"Was hast du heute geschafft?","What did you do today?"):step===1&&activities.length?bi(lang,"Wie lief deine Einheit?","How did your workout feel?"):bi(lang,"Dein Ausblick auf morgen","Your outlook for tomorrow")}</h3>
  {step===0&&(activities.length?<><label>{bi(lang,"Heutige Aktivität","Today's activity")}<select value={chosen} aria-label={bi(lang,"Heutige Aktivität","Today's activity")} onChange={e=>void loadActivity(e.target.value)}>{activities.map(a=><option key={a.id} value={a.id}>{a.name}{records[a.id]?.feeling?" ✓":""}</option>)}</select></label>{activity&&<div className="assistant-activity-preview today-recorded-result"><span className="eyebrow">{matched?bi(lang,"Planeinheit zugeordnet","Planned session matched"):bi(lang,"Bewegung erfasst","Activity recorded")}</span><h4>{activity.name}</h4><div className="today-result-values">{activity.duration_seconds!=null&&<strong>{Math.round(activity.duration_seconds/60)} <small>min</small></strong>}{activity.distance_m!=null&&<strong>{(activity.distance_m/1000).toFixed(1)} <small>km</small></strong>}</div><a className="text-link" href={`/activities/${activity.id}`}>{bi(lang,"Ergebnis ansehen","View result")} →</a></div>}<small>{bi(lang,"Jede Aktivität erhält ihr eigenes Feedback.","Each activity has its own feedback.")}</small></>:<p className="muted">{bi(lang,"Heute ist noch keine abgeschlossene Aktivität erfasst. Auch ein ruhiger Tag darf dazugehören.","No completed activity has been recorded today yet. An easier day belongs here too.")}</p>)}
  {step===1&&activities.length>0&&<><p className="muted">{activity?.name}</p><div className="today-feedback-feelings assistant-choice-grid">{feelings.map(([key,label])=><button type="button" key={key} className={`ghost ${feeling===key?"active":""}`} aria-pressed={feeling===key} onClick={()=>setFeeling(key)}>{label}</button>)}</div><label>{bi(lang,"Kurze Notiz (optional)","Quick note (optional)")}<textarea aria-label={bi(lang,"Kurze Notiz","Quick note")} rows={3} maxLength={1000} value={note} onChange={e=>setNote(e.target.value)} placeholder={bi(lang,"Was lief gut? Was war schwierig?","What went well? What was difficult?")}/></label><small>{bi(lang,"Dein Feedback wird erst am Ende gespeichert.","Your feedback is only saved at the end.")}</small></>}
  {step===steps.length-1&&<>{activity&&<div className="assistant-feedback-review"><strong>{activity.name}</strong><span>{feelings.find(([key])=>key===feeling)?.[1]||"—"}</span>{note&&<p>{note}</p>}</div>}<div className="today-tomorrow"><span className="eyebrow">{bi(lang,"MORGEN","TOMORROW")}</span>{next.length?next.map(s=><a key={`${s.plan_id}-${s.id}`} href={`/training?plan=${s.plan_id}`}><strong>{s.name}</strong><span>{s.duration_min} min →</span></a>):<span className="muted">{bi(lang,"Keine Einheit im Kalender gespeichert.","No workout saved in the calendar.")}</span>}<a className="text-link" href="/training">{bi(lang,"Kalender öffnen","Open calendar")} →</a></div><small>{activities.length?bi(lang,"Speichert das Feedback zur gewählten Aktivität. Dein Trainingsplan wird dabei nicht verändert.","Saves feedback for the selected activity. Your training plan stays unchanged."):bi(lang,"Ohne erfasste Aktivität wird kein Trainingsfeedback gespeichert.","Without a recorded activity, no workout feedback is saved.")}</small></>}
  </fieldset>{loading&&<p role="status">{bi(lang,"Dein Feedback wird geladen …","Loading your feedback …")}</p>}{error&&<div role="alert"><p>{error}</p>{step===0&&<button type="button" className="ghost" disabled={busy||loading} onClick={()=>void loadActivity(chosen)}>{bi(lang,"Erneut laden","Retry")}</button>}</div>}
 </AssistantDialog></>;
}
