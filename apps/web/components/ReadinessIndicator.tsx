import {bi,type Lang} from "../lib/i18n";

type Readiness = {status?:string;score?:number|null;components?:{key:string;impact:number}[]};
export default function ReadinessIndicator({readiness,labels,lang,loading=false}:{readiness:Readiness;labels:Record<string,string>;lang:Lang;loading?:boolean}){
 const state=["green","yellow","red"].includes(readiness.status||"")?readiness.status!:"insufficient";
 const title=loading?bi(lang,"Wird geladen …","Loading …"):state==="green"?bi(lang,"Training nach Plan","Train as planned"):state==="yellow"?bi(lang,"Locker trainieren","Keep it easy"):state==="red"?bi(lang,"Erholung einplanen","Make time for recovery"):bi(lang,"Check-in ergänzen","Add your check-in");
 const color=state==="green"?bi(lang,"Grün","Green"):state==="yellow"?bi(lang,"Gelb","Yellow"):state==="red"?bi(lang,"Rot","Red"):bi(lang,"Noch offen","Not assessed yet");
 const drivers=(readiness.components||[]).filter(x=>x.impact<0).slice(0,3);
 return <div className={`readiness-card readiness-${state}`}>
  <div className="readiness-lights" role="img" aria-label={loading?title:`${bi(lang,"Ampel","Traffic light")}: ${color}`}>
   {(["red","yellow","green"] as const).map(light=><span key={light} className={`readiness-light lamp-${light} ${state===light?"is-active":""}`} aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">{light==="green"?<path d="m6 12 4 4 8-8"/>:light==="yellow"?<path d="M6 12h12"/>:<path d="M9 6v12M15 6v12"/>}</svg></span>)}
  </div>
  <div className="readiness-copy"><span className="metric-label">Pengu Readiness</span><strong>{title}</strong>{state==="insufficient"&&!loading&&<small>{bi(lang,"Noch nicht genug Daten","Not enough data yet")}</small>}</div>
  <div className="readiness-score" aria-label={state!=="insufficient"&&readiness.score!=null?`${readiness.score} ${bi(lang,"von 100 Punkten","out of 100 points")}`:undefined}><strong>{state==="insufficient"?"—":readiness.score??"—"}</strong>{state!=="insufficient"&&readiness.score!=null&&<small>/ 100</small>}</div>
  {drivers.length>0&&<div className="readiness-drivers" aria-label={bi(lang,"Aktuelle Belastungsfaktoren","Current strain factors")}>{drivers.map(x=><span key={x.key}><span aria-hidden="true">↓</span> {labels[x.key]||x.key}</span>)}</div>}
 </div>;
}
