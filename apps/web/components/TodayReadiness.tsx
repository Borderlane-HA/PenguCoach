"use client";
// The daily readiness ("Tagesampel"): one gauge, one clear message, one next step, reasons on demand.
import {useState} from "react";
import Link from "next/link";
import {bi,type Lang} from "../lib/i18n";
import {ringDash} from "../lib/todayLayout";

type O=Record<string,any>;

export function readinessLabels(lang:Lang):O{return {sleep:bi(lang,"Schlaf","Sleep"),hrv:"HRV",resting_hr:bi(lang,"Ruhepuls","Resting HR"),stress:"Stress",body_battery:"Body Battery",provider_readiness:bi(lang,"Geräte-Bereitschaft","Device readiness"),energy:bi(lang,"Energie","Energy"),soreness:bi(lang,"Muskelkater","Soreness"),discomfort:bi(lang,"Beschwerden","Discomfort"),hard_feedback:bi(lang,"Trainingsfeedback","Training feedback"),feedback_discomfort:bi(lang,"Beschwerden nach Training","Post-training discomfort"),consecutive_days:bi(lang,"Trainingstage in Folge","Consecutive training days")}}

export default function TodayReadiness({data,loading,failed,lang,onRetry}:{data:O|null;loading:boolean;failed:boolean;lang:Lang;onRetry:()=>void}){
  const [why,setWhy]=useState(false);
  const de=lang==="de",readiness:O=data?.readiness||{},check:O=data?.checkin||{},labels=readinessLabels(lang);
  const state=!loading&&!failed&&["green","yellow","red"].includes(readiness.status)?readiness.status:"open";
  const score=state!=="open"&&Number.isFinite(readiness.score)?Math.round(readiness.score):null;
  const title=loading?bi(lang,"Wird eingeschätzt …","Assessing …"):failed?bi(lang,"Gerade nicht verfügbar","Not available right now"):state==="green"?bi(lang,"Training nach Plan","Train as planned"):state==="yellow"?bi(lang,"Locker trainieren","Keep it easy"):state==="red"?bi(lang,"Erholung einplanen","Make time for recovery"):bi(lang,"Noch offen","Not assessed yet");
  const sub=state==="green"?bi(lang,"Deine Werte sprechen für die geplante Belastung.","Your readings support the planned load."):state==="yellow"?bi(lang,"Etwas spricht für einen ruhigeren Tag.","Something points to an easier day."):state==="red"?bi(lang,"Heute hat Erholung Vorrang.","Recovery comes first today."):failed?"":bi(lang,"Ein kurzer Check-in reicht für eine Einschätzung.","A short check-in is enough for an assessment.");
  const factors=(readiness.components||[]).filter((x:O)=>x.impact!==0).sort((a:O,b:O)=>Math.abs(b.impact)-Math.abs(a.impact));
  const top=factors.slice(0,3);
  const confidence=({low:1,medium:2,high:3} as O)[readiness.confidence]||0;
  const next=data?.upcoming?.find((s:O)=>s.date===data?.date);
  const needsCheckin=!!data&&state==="open"&&check.energy==null&&check.soreness==null;
  const caution=data?.mode==="check_discomfort"||state==="red";
  const ask=(text:string)=>`/coach?prompt=${encodeURIComponent(text)}`;
  const action=loading||!data?null:needsCheckin?{label:bi(lang,"Check-in starten","Start check-in"),checkin:true}
    :caution?{label:bi(lang,"Erholung planen","Plan recovery"),href:ask(de?"Plane heute Erholung oder eine sehr leichte Alternative anhand meines Check-ins und meiner Daten.":"Plan recovery or a very easy alternative today using my check-in and data.")}
    :next&&check.minutes!==0?{label:state==="yellow"?bi(lang,"Einheit anpassen","Adjust workout"):bi(lang,"Heutige Einheit","Today's workout"),href:`/training?plan=${next.plan_id}${state==="yellow"?"&review=week":""}`}
    :{label:bi(lang,"Was passt heute?","What suits me today?"),href:ask(de?"Was soll ich heute trainieren? Nutze meine Daten, mein Profil und meinen Check-in. Antworte kurz mit Empfehlung und Begründung.":"What should I train today? Use my data, profile and check-in. Give a short recommendation and reason.")};
  const ring=ringDash(score,52);
  return <section className={`card today-readiness ready-${state} ${loading?"is-loading":""}`} aria-busy={loading}>
    <div className="ready-gauge" role="img" aria-label={score!=null?bi(lang,`Bereitschaft ${score} von 100 – ${title}`,`Readiness ${score} of 100 – ${title}`):title}>
      <svg viewBox="0 0 120 120" aria-hidden="true"><circle className="ready-track" cx="60" cy="60" r="52"/><circle className="ready-value" cx="60" cy="60" r="52" strokeDasharray={`${ring.dash} ${ring.length}`} transform="rotate(-90 60 60)"/></svg>
      <div className="ready-number"><strong>{score??"—"}</strong><small>{score!=null?"/ 100":bi(lang,"offen","open")}</small></div>
    </div>
    <div className="ready-body">
      <span className="eyebrow">{bi(lang,"Tagesampel","Daily readiness")}</span>
      <h2>{title}</h2>
      {sub&&<p className="ready-sub">{sub}</p>}
      {top.length>0&&<div className="ready-factors">{top.map((x:O)=><span key={x.key} className={x.impact<0?"down":"up"}><i aria-hidden="true">{x.impact<0?"↓":"↑"}</i>{labels[x.key]||x.key}</span>)}</div>}
      <div className="ready-actions">
        {failed?<button type="button" className="ghost" onClick={onRetry}>{bi(lang,"Erneut versuchen","Try again")}</button>
          :action?.checkin?<button type="button" onClick={()=>document.getElementById("today-checkin-trigger")?.click()}>{action.label} →</button>
          :action?<Link prefetch={false} className="primary-link" href={action.href!}>{action.label} →</Link>:null}
        {!loading&&!failed&&(factors.length>0||confidence>0)&&<button type="button" className="ghost compact ready-why" aria-expanded={why} onClick={()=>setWhy(v=>!v)}>{bi(lang,"Warum?","Why?")}</button>}
      </div>
      {why&&<div className="ready-details">
        {confidence>0&&<div className="ready-basis"><span>{bi(lang,"Datenbasis","Data basis")}</span><span className="ready-dots" aria-label={["",bi(lang,"wenig","limited"),bi(lang,"mittel","moderate"),bi(lang,"gut","good")][confidence]}>{[1,2,3].map(n=><i key={n} className={n<=confidence?"on":""}/>)}</span></div>}
        {factors.map((x:O)=><div className="ready-factor-row" key={x.key}><span>{labels[x.key]||x.key}</span><span className="ready-bar" aria-hidden="true"><i className={x.impact<0?"down":"up"} style={{width:`${Math.min(100,Math.abs(x.impact)*4)}%`}}/></span><b>{x.impact>0?"+":""}{x.impact}</b></div>)}
      </div>}
    </div>
  </section>;
}
