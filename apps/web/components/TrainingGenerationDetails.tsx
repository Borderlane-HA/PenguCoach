"use client";

import {bi,type Lang} from "../lib/i18n";
import {euro} from "../lib/aiUsage";

type Call=Record<string,any>;
const duration=(value:number)=>{const whole=Math.round(value);return `${Math.floor(whole/60)}:${(whole%60).toString().padStart(2,"0")}`};

export default function TrainingGenerationDetails({calls,lang}:{calls:Call[];lang:Lang}){
  if(!Array.isArray(calls)||!calls.length)return null;
  const retries=calls.filter(c=>Number(c.attempt)>1);
  const seconds=calls.reduce((s,c)=>s+(Number(c.elapsed_seconds)||0),0);
  const retrySeconds=retries.reduce((s,c)=>s+(Number(c.elapsed_seconds)||0),0);
  return <div className="training-generation-details">
    <p className="muted training-generation-summary">{calls.length} {bi(lang,"KI-Aufrufe","AI calls")}
      {seconds>0&&` · ${duration(seconds)} ${bi(lang,"Min. Anfragezeit","min request time")}`}
      {retries.length>0&&` · ${retries.length} ${bi(lang,"erneute Versuche","retries")}${retrySeconds>0?` (${duration(retrySeconds)} Min.)`:""}`}
    </p>
    <div className="training-generation-calls">{calls.map((c,i)=>{
      const timing=c.provider_timing??{};
      return <article className="training-generation-call" key={i}>
        <div className="training-generation-call-head"><strong>{bi(lang,"Teil","Part")} {c.chunk_index}/{c.chunk_count} · {bi(lang,"Versuch","attempt")} {c.attempt}</strong>
          {typeof c.validation_valid==="boolean"&&<span>{c.validation_valid?bi(lang,"Gültig","Valid"):c.stop_reason==="request_failed"||c.stop_reason==="cancelled"?bi(lang,"Anfrage unterbrochen","Request interrupted"):bi(lang,"Prüfung fehlgeschlagen","Validation failed")}</span>}
        </div>
        <p>{c.usage?.input_tokens==null?"—":Number(c.usage.input_tokens).toLocaleString()} in · {c.usage?.output_tokens==null?"—":Number(c.usage.output_tokens).toLocaleString()} out
          {c.elapsed_seconds!=null?` · ${Number(c.elapsed_seconds).toFixed(1)}s`:""}
          {c.tokens_per_second!=null?` · ${Number(c.tokens_per_second).toFixed(1)} ${bi(lang,"out/s gesamt","out/s overall")}`:""}
          {c.cost_eur!=null?` · ${euro(Number(c.cost_eur))}`:""}
        </p>
        {timing.generation_seconds!=null&&<p className="training-generation-timing">
          {bi(lang,"Ollama","Ollama")}: {[
            timing.load_seconds!=null?`${bi(lang,"Laden","Loading")} ${Number(timing.load_seconds).toFixed(1)}s`:null,
            timing.prompt_seconds!=null?`${bi(lang,"Eingabe","Input")} ${Number(timing.prompt_seconds).toFixed(1)}s`:null,
            `${bi(lang,"Ausgabe","Output")} ${Number(timing.generation_seconds).toFixed(1)}s`,
            timing.generation_tokens_per_second!=null?`${Number(timing.generation_tokens_per_second).toFixed(1)} ${bi(lang,"Token/s Generierung","tokens/s generation")}`:null,
          ].filter(Boolean).join(" · ")}
        </p>}
        {c.validation_error&&<details className="training-generation-error"><summary>{bi(lang,"Prüfgrund anzeigen","Show validation reason")}</summary><pre>{String(c.validation_error)}</pre></details>}
      </article>;
    })}</div>
  </div>;
}
