import {bi,type Lang} from "../lib/i18n";

type Readiness = {status?:string;score?:number|null;confidence?:string;available_factors?:number;components?:{key:string;impact:number}[]};
export default function ReadinessIndicator({readiness,labels,lang,loading=false,failed=false}:{readiness:Readiness;labels:Record<string,string>;lang:Lang;loading?:boolean;failed?:boolean}){
 const state=!loading&&!failed&&["green","yellow","red"].includes(readiness.status||"")?readiness.status!:"insufficient";
 const title=loading?bi(lang,"Bereitschaft wird geprüft …","Checking readiness …"):failed?bi(lang,"Bereitschaft nicht verfügbar","Readiness unavailable"):state==="green"?bi(lang,"Training nach Plan","Train as planned"):state==="yellow"?bi(lang,"Locker trainieren","Keep it easy"):state==="red"?bi(lang,"Erholung einplanen","Make time for recovery"):bi(lang,"Check-in ergänzen","Add your check-in");
 const color=state==="green"?bi(lang,"Grün","Green"):state==="yellow"?bi(lang,"Gelb","Yellow"):state==="red"?bi(lang,"Rot","Red"):bi(lang,"Noch offen","Not assessed yet");
 const drivers=loading||failed?[]:(readiness.components||[]).filter(x=>x.impact<0).slice(0,2);
 const score=state!=="insufficient"&&Number.isFinite(readiness.score)?Math.max(0,Math.min(100,readiness.score!)):null;
 const confidence=({low:1,medium:2,high:3} as Record<string,number>)[readiness.confidence||""]||0;
 return <div className={`readiness-card readiness-${state} ${loading?"readiness-loading":""}`} aria-busy={loading}>
  <div className="readiness-lights" role="img" aria-label={loading?title:`${bi(lang,"Ampel","Traffic light")}: ${color}`}>
   {(["red","yellow","green"] as const).map(light=><span key={light} className={`readiness-light lamp-${light} ${state===light?"is-active":""}`} aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">{light==="green"?<path d="m6 12 4 4 8-8"/>:light==="yellow"?<path d="M6 12h12"/>:<path d="M9 6v12M15 6v12"/>}</svg></span>)}
  </div>
  <div className="readiness-copy"><span className="metric-label">Pengu Readiness</span><strong role={loading?"status":undefined}>{title}</strong>{state==="insufficient"&&!loading&&!failed&&<small>{bi(lang,"Noch nicht genug Daten","Not enough data yet")}</small>}{!loading&&!failed&&confidence>0&&<span className="readiness-basis"><span>{bi(lang,"Datenbasis","Data basis")}</span><span className="readiness-confidence-bars" role="img" aria-label={`${confidence} / 3`}>{[1,2,3].map(n=><i key={n} className={n<=confidence?"filled":""}/>)}</span></span>}</div>
  <div className="readiness-score readiness-dial" aria-label={score!=null?`${score} ${bi(lang,"von 100 Punkten","out of 100 points")}`:undefined}><svg viewBox="0 0 84 84" aria-hidden="true"><circle className="readiness-dial-track" cx="42" cy="42" r="36"/><circle className="readiness-dial-value" cx="42" cy="42" r="36" strokeDasharray={`${score==null?0:score/100*226.2} 226.2`} transform="rotate(-90 42 42)"/></svg><div><strong>{score??"—"}</strong>{score!=null&&<small>/ 100</small>}</div></div>
  {drivers.length>0&&<div className="readiness-drivers" aria-label={bi(lang,"Aktuelle Belastungsfaktoren","Current strain factors")}>{drivers.map(x=><span key={x.key}><span aria-hidden="true">↓</span> {labels[x.key]||x.key}</span>)}</div>}
 </div>;
}
