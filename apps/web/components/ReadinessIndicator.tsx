import {bi,type Lang} from "../lib/i18n";

type Readiness = {status?:string;score?:number|null;confidence?:string;available_factors?:number;components?:{key:string;impact:number}[]};
export default function ReadinessIndicator({readiness,labels,lang,loading=false,failed=false}:{readiness:Readiness;labels:Record<string,string>;lang:Lang;loading?:boolean;failed?:boolean}){
 const state=!loading&&!failed&&["green","yellow","red"].includes(readiness.status||"")?readiness.status!:"insufficient";
 const title=loading?bi(lang,"Bereitschaft wird geprüft …","Checking readiness …"):failed?bi(lang,"Bereitschaft nicht verfügbar","Readiness unavailable"):state==="green"?bi(lang,"Training nach Plan","Train as planned"):state==="yellow"?bi(lang,"Locker trainieren","Keep it easy"):state==="red"?bi(lang,"Erholung einplanen","Make time for recovery"):bi(lang,"Check-in ergänzen","Add your check-in");
 const color=state==="green"?bi(lang,"Grün","Green"):state==="yellow"?bi(lang,"Gelb","Yellow"):state==="red"?bi(lang,"Rot","Red"):bi(lang,"Noch offen","Not assessed yet");
 const drivers=loading||failed?[]:(readiness.components||[]).filter(x=>x.impact<0).slice(0,2);
 const score=state!=="insufficient"&&Number.isFinite(readiness.score)?Math.max(0,Math.min(100,readiness.score!)):null;
 const confidence=({low:1,medium:2,high:3} as Record<string,number>)[readiness.confidence||""]||0;
 const basis=({low:bi(lang,"Wenig","Limited"),medium:bi(lang,"Mittel","Moderate"),high:bi(lang,"Gut","Good")} as Record<string,string>)[readiness.confidence||""];
 return <div className={`readiness-card readiness-v2 readiness-${state} ${loading?"readiness-loading":""}`} aria-busy={loading}>
  <div className="readiness-main"><span className="readiness-emblem" role="img" aria-label={loading?title:`${bi(lang,"Tagesampel","Daily readiness")}: ${color}`}><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{state==="green"?<path d="m6 12 4 4 8-8"/>:state==="yellow"?<path d="M3 13h4l3-5 4 9 3-5h4"/>:state==="red"?<><path d="M9 7v10M15 7v10"/><circle cx="12" cy="12" r="9"/></>:<><circle cx="12" cy="12" r="9"/><path d="M8 12h.01M12 12h.01M16 12h.01"/></>}</svg></span><div className="readiness-copy"><span className="metric-label">{bi(lang,"Deine Tagesampel","Your daily readiness")}</span><strong role={loading?"status":undefined}>{title}</strong>{state==="insufficient"&&!loading&&!failed&&<small>{bi(lang,"Noch nicht genug Daten","Not enough data yet")}</small>}</div></div>
  <div className="readiness-score readiness-score-pill" aria-label={score!=null?`Pengu Readiness: ${score} ${bi(lang,"von 100 Punkten","out of 100 points")}`:undefined}><strong>{score??"—"}</strong>{score!=null&&<small>/ 100</small>}</div>
  <div className="readiness-meter" aria-hidden="true">{Array.from({length:20},(_,n)=><span key={n} className={score!=null&&n<Math.ceil(score/5)?"filled":""}/>)}</div>
  {(!loading&&!failed&&confidence>0||drivers.length>0)&&<div className="readiness-footer">{!loading&&!failed&&confidence>0&&<span className="readiness-basis"><span>{bi(lang,"Datenbasis","Data basis")}</span><span className="readiness-confidence-bars" role="img" aria-label={basis}>{[1,2,3].map(n=><i key={n} className={n<=confidence?"filled":""}/>)}</span></span>}{drivers.length>0&&<div className="readiness-drivers" aria-label={bi(lang,"Aktuelle Belastungsfaktoren","Current strain factors")}>{drivers.map(x=><span key={x.key}><span aria-hidden="true">↓</span> {labels[x.key]||x.key}</span>)}</div>}</div>}
 </div>;
}
