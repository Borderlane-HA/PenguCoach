"use client";
import {useEffect,useRef,useState} from "react";
import {api} from "../lib/api";
import {bi,type Lang} from "../lib/i18n";
type O=Record<string,any>;
const pause=(ms:number)=>new Promise(resolve=>setTimeout(resolve,ms));
export default function AiContinuation({run,lang,onResult,onBusy}:{run:O;lang:Lang;onResult:(run:O)=>void;onBusy?:(busy:boolean)=>void}){
 const id=String(run.run_id??run.id??""),meta=run.metadata??run,state=meta.continuation??run.continuation??{};
 const formatRetry=state.reason==="invalid_plan";
 const[busy,setBusy]=useState(false),[job,setJob]=useState(""),[status,setStatus]=useState(""),[error,setError]=useState("");
 const seq=useRef(0),resultRef=useRef(onResult),busyRef=useRef(onBusy);resultRef.current=onResult;busyRef.current=onBusy;
 const key=`pengucoach_continue_${id}`;
 const messages:Record<string,[string,string]>={CONTINUATION_CONTEXT_FULL:["Das Modellkontextfenster reicht für diese Fortsetzung nicht aus.","The model context window is too small for this continuation."],CONTINUATION_MODEL_LIMIT:["Das Modell erlaubt kein höheres Antwortbudget für diesen Versuch.","This model does not allow a higher response budget for this attempt."],CONVERSATION_CHANGED_RELOAD:["Das Gespräch wurde inzwischen fortgeführt. Lade den aktuellen Stand.","The conversation has moved on. Reload its current state."],AI_RUN_CHANGED_RELOAD:["Die Antwort wurde inzwischen geändert. Bitte erneut prüfen.","The answer changed elsewhere. Review it again."],NO_ELIGIBLE_LLM_MODEL_CONFIGURED:["Das Modell ist nicht verfügbar oder Cloud-KI wurde gesperrt.","The model is unavailable or cloud AI has been blocked."]};
 function readable(value:string){const found=Object.keys(messages).find(k=>value.includes(k));return found?messages[found][lang==="de"?0:1]:value}
 async function poll(jobId:string,ticket:number){
  for(let i=0;i<2400&&ticket===seq.current;i++){
   try{const response=await api<O>(`/jobs/${jobId}`);if(ticket!==seq.current)return;
    if(response.ready){localStorage.removeItem(key);setBusy(false);busyRef.current?.(false);setJob("");setStatus("");
     if(response.successful&&response.result&&!response.result.cancelled){resultRef.current(response.result);return}
     if(!response.result?.cancelled)setError(readable(response.error||"AI_JOB_FAILED"));
     try{const fresh=await api<O>(`/coach/runs/${id}`);if(ticket===seq.current)resultRef.current(fresh)}catch{}return;
    }setStatus(response.progress?.message||bi(lang,"Antwort wird fortgesetzt …","Continuing the answer …"));
   }catch{if(ticket===seq.current)setStatus(bi(lang,"Verbindung wird wiederhergestellt …","Reconnecting …"))}
   await pause(1000);
  }
 }
 useEffect(()=>{const ticket=++seq.current,stored=id?localStorage.getItem(key):null;if(stored){setBusy(true);busyRef.current?.(true);setJob(stored);void poll(stored,ticket)}return()=>{seq.current++}},[id]);
 async function start(){if(busy||!id)return;setBusy(true);busyRef.current?.(true);setError("");try{const r=await api<O>(`/coach/runs/${id}/continue`,{method:"POST",body:JSON.stringify({revision:state.revision??0,additional_tokens:formatRetry?0:8000})});localStorage.setItem(key,r.task_id);setJob(r.task_id);void poll(r.task_id,++seq.current)}catch(e){setError(readable(String(e)));setBusy(false);busyRef.current?.(false);try{resultRef.current(await api<O>(`/coach/runs/${id}`))}catch{}}}
 async function cancel(){if(!job)return;try{await api(`/jobs/${job}/cancel`,{method:"POST"});seq.current++;localStorage.removeItem(key);setBusy(false);busyRef.current?.(false);setJob("");setStatus(bi(lang,"Fortsetzung abgebrochen. Der bisherige Text bleibt erhalten.","Continuation cancelled. Your previous text is preserved."));resultRef.current(await api<O>(`/coach/runs/${id}`))}catch(e){setError(readable(String(e)))}}
 if(!id||!state.available&&!busy&&!error)return null;
 return <div className="ai-continuation"><div><strong>{formatRetry?bi(lang,"Planabschnitt konnte nicht geprüft werden","Plan section could not be validated"):bi(lang,"Antwortlimit erreicht","Response limit reached")}</strong><small>{formatRetry?bi(lang,`Gültige Abschnitte bleiben erhalten (${meta.validated_weeks??0} Wochen). Nur der offene Abschnitt wird neu angefordert. Das Antwortbudget bleibt gleich.`,`Valid sections are preserved (${meta.validated_weeks??0} weeks). Only the pending section is retried, using the same response budget.`):meta.empty_due_to_limit?bi(lang,"Noch kein sichtbarer Antworttext. Ein neuer Versuch erhält ein höheres Budget.","No visible answer yet. A new attempt receives a higher budget."):bi(lang,"Deine bisherige Ausgabe bleibt erhalten. Die Fortsetzung ist eine weitere KI-Anfrage.","Your existing output is preserved. Continuing starts another AI request.")}</small></div><div className="form-actions"><button type="button" disabled={busy||!state.available} onClick={start}>{busy?bi(lang,"Wird fortgesetzt …","Continuing …"):formatRetry?bi(lang,"Offenen Abschnitt erneut versuchen","Retry pending section"):bi(lang,"Mit +8.000 Token fortsetzen","Continue with +8,000 tokens")}</button>{busy&&<button type="button" className="ghost" onClick={cancel}>{bi(lang,"Abbrechen","Cancel")}</button>}</div>{formatRetry&&meta.structured_plan_error&&<details className="training-intel-details"><summary>{bi(lang,"Technische Fehlerdetails","Technical error details")}</summary><pre style={{whiteSpace:"pre-wrap",overflowWrap:"anywhere"}}>{String(meta.structured_plan_error)}</pre></details>}{status&&<small role="status">{status}</small>}{error&&<p role="alert">{error}</p>}</div>
}
