"use client";

import {bi,Lang} from "../lib/i18n";
import {estimatedMaxCost,euro,qualityHint,qualityLabel,QualityId} from "../lib/aiUsage";

type AnyObj=Record<string,any>;

type Props={
  lang:Lang;
  profile:QualityId;
  onChange:(value:QualityId,suggestedTokens:number)=>void;
  options?:{id:string;max_output_tokens:number}[];
  model?:AnyObj|null;
  contextWindow:number;
  maxOutput:number;
  calls?:number;
};

export default function AiQualityControl({lang,profile,onChange,options=[],model,contextWindow,maxOutput,calls=1}:Props){
  const de=lang!=="en";
  const estimate=estimatedMaxCost(model,contextWindow,maxOutput,calls);
  const suggested=(id:QualityId)=>options.find(x=>x.id===id)?.max_output_tokens??maxOutput;
  return <div className="ai-quality-control">
    <div className="ai-quality-head"><div><strong>{bi(lang,"Antwortprofil","Response profile")}</strong><small>{qualityHint(profile,de)}</small></div>{estimate!=null&&<span className="ai-cost-estimate">{bi(lang,"bis ca.","up to approx.")} {euro(estimate)}{calls>1?` · ${calls} ${bi(lang,"Aufrufe","calls")}`:""}</span>}</div>
    <div className="ai-quality-buttons">{(["very_low","low","standard","high"] as QualityId[]).map(id=><button type="button" key={id} className={profile===id?"active":"ghost"} onClick={()=>onChange(id,suggested(id))}><strong>{qualityLabel(id,de)}</strong><small>{suggested(id).toLocaleString()} out</small></button>)}</div>
    {estimate!=null&&<small className="muted">{bi(lang,"Schätzung aus Kontext- und maximalem Outputbudget; tatsächliche Provider-Kosten werden nach Abschluss aus den Usage-Werten gespeichert. Retries können zusätzliche Kosten verursachen.","Estimate from context and maximum output budget; actual provider cost is stored from usage values after completion. Retries may add cost.")}</small>}
  </div>;
}
