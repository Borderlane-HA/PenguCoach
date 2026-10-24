"use client";
// One health value: average for the period, trend, tiny curve, explanation and "ask the coach".
import Link from "next/link";
import InfoTip from "./InfoTip";
import {bi,type Lang} from "../lib/i18n";
import {changeText,coachPrompt,display,sparkPath,type MetricDef,type Summary} from "../lib/healthInsights";

export function CoachSpark(){return <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="m12 3 1.2 3.4L16.5 8l-3.3 1.6L12 13l-1.2-3.4L7.5 8l3.3-1.6L12 3Z"/><path d="m18.5 13 .8 2.2 2.2.8-2.2.8-.8 2.2-.8-2.2-2.2-.8 2.2-.8.8-2.2Z"/></svg>}

export default function HealthTile({def,s,lang,periodLabel,loading,extra}:{def:MetricDef;s:Summary;lang:Lang;periodLabel:string;loading?:boolean;extra?:React.ReactNode}){
  const name=def.label[lang],path=sparkPath(s.values.map(v=>v.value),120,34);
  const trendClass=s.good==null?"neutral":s.good?"good":"bad";
  return <article className={`health-tile tone-${def.tone} ${loading?"is-loading":""}`} aria-busy={loading}>
    <header><span className="health-tile-name">{name}</span><InfoTip label={bi(lang,`Was ist ${name}?`,`What is ${name}?`)} text={def.info[lang]}/>
      <Link prefetch={false} className="health-tile-ai" href={`/coach?prompt=${encodeURIComponent(coachPrompt(def,s,lang,periodLabel))}`} aria-label={bi(lang,`${name} mit dem Coach besprechen`,`Discuss ${name} with the coach`)} title={bi(lang,"Mit dem Coach besprechen","Discuss with the coach")}><CoachSpark/></Link>
    </header>
    <div className="health-tile-value">{loading?<span className="metric-skeleton"/>:display(def,s.avg,lang)}</div>
    <div className="health-tile-foot">
      {s.trend&&<span className={`health-trend ${trendClass}`}><i aria-hidden="true">{s.trend==="up"?"↗":s.trend==="down"?"↘":"→"}</i>{changeText(def,s,lang)}</span>}
      <small>{s.count?bi(lang,`Ø ${periodLabel}`,`avg ${periodLabel}`):bi(lang,"Keine Daten","No data")}</small>
    </div>
    {path&&<svg className="health-tile-spark" viewBox="0 0 120 34" preserveAspectRatio="none" aria-hidden="true"><path d={path}/></svg>}
    {extra}
  </article>;
}
