"use client";

import {FormEvent,useEffect,useRef,useState} from "react";
import AppShell from "../../components/AppShell";
import AiReport from "../../components/AiReport";
import TrainingZoneStatus from "../../components/TrainingZoneStatus";
import TrainingPlanCalendar from "../../components/TrainingPlanCalendar";
import AiQualityControl from "../../components/AiQualityControl";
import {api} from "../../lib/api";
import {bi,useI18n,type Lang} from "../../lib/i18n";
import {euro,type QualityId} from "../../lib/aiUsage";

type AnyObj=Record<string,any>;
type ContextData={training:boolean;zones:boolean;sleep_hrv:boolean;recovery:boolean;daily_activity:boolean};
const sleep=(ms:number)=>new Promise(r=>setTimeout(r,ms));
const GOALS=[
  ["muscle_gain","Muskelaufbau","Muscle gain"],["cardio_endurance","Cardio / Ausdauer","Cardio / endurance"],["hybrid","Hybrid · Kraft + Ausdauer","Hybrid · strength + endurance"],["cycling_endurance","Radsport-Ausdauer","Cycling endurance"],["running_5k","Laufen · 5 km","Running · 5K"],["running_10k","Laufen · 10 km","Running · 10K"],["half_marathon","Halbmarathon","Half marathon"],["marathon","Marathon","Marathon"],["strength","Kraft","Strength"],["general_fitness","Allgemeine Fitness","General fitness"],["mobility","Mobilität","Mobility"],["custom","Eigenes Ziel","Custom goal"],
];
const CONTEXT_DAYS=[3,7,14,21,28];

function progressTokens(progress:AnyObj|null){
  if(!progress)return"";
  const exact=progress.output_tokens_exact;
  const estimate=progress.output_tokens_estimate;
  const used=exact??estimate;
  if(used==null)return"";
  const max=progress.max_output_tokens;
  return `${exact==null?"≈ ":""}${Number(used).toLocaleString()}${max?` / ${Number(max).toLocaleString()}`:""} Tokens`;
}

function friendlyPlanError(raw:string,lang:Lang){
  const truncated=raw.match(/TRAINING_PLAN_SEGMENT_TRUNCATED:(\d+)-(\d+)/);
  if(truncated)return bi(lang,`Die Wochen ${truncated[1]}–${truncated[2]} konnten auch beim automatischen Wiederholungsversuch nicht vollständig erzeugt werden. Erhöhe „Max. Antwort“ oder das Kontextfenster; PenguCoach verwendet den Wert pro Planabschnitt.`,`Weeks ${truncated[1]}–${truncated[2]} could not be completed even after the automatic retry. Increase “Max response” or the context window; PenguCoach applies that value per plan segment.`);
  const invalid=raw.match(/TRAINING_PLAN_SEGMENT_INVALID:(\d+)-(\d+)/);
  if(invalid)return bi(lang,`Die Wochen ${invalid[1]}–${invalid[2]} lieferten kein gültiges strukturiertes Trainingsformat. PenguCoach hat den Abschnitt bereits automatisch erneut angefordert.`,`Weeks ${invalid[1]}–${invalid[2]} did not return a valid structured training format. PenguCoach already retried that segment automatically.`);
  return raw||bi(lang,"AI-Auftrag fehlgeschlagen","AI job failed");
}

export default function Training(){
  const{lang}=useI18n();const de=lang!=="en";
  const[caps,setCaps]=useState<AnyObj|null>(null),[history,setHistory]=useState<AnyObj[]>([]),[result,setResult]=useState<AnyObj|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState(""),[status,setStatus]=useState("");
  const[jobId,setJobId]=useState<string|null>(null),[jobProgress,setJobProgress]=useState<AnyObj|null>(null);
  const ignoredJobs=useRef<Set<string>>(new Set());
  const[deleteCandidate,setDeleteCandidate]=useState<AnyObj|null>(null),[deleteInfo,setDeleteInfo]=useState<AnyObj|null>(null),[deleteBusy,setDeleteBusy]=useState(false),[deleteStatus,setDeleteStatus]=useState("");
  const[goalType,setGoalType]=useState("hybrid"),[goalText,setGoalText]=useState(""),[experience,setExperience]=useState("intermediate"),[weeks,setWeeks]=useState(8),[days,setDays]=useState(4),[minutes,setMinutes]=useState(60),[equipment,setEquipment]=useState(""),[constraints,setConstraints]=useState("");
  const[contextDays,setContextDays]=useState(7),[contextData,setContextData]=useState<ContextData>({training:true,zones:true,sleep_hrv:true,recovery:true,daily_activity:false});
  const[model,setModel]=useState(""),[tokens,setTokens]=useState(4500),[ctx,setCtx]=useState(8192),[prompt,setPrompt]=useState(""),[quality,setQuality]=useState<QualityId>("standard");
  const jobKey="pengucoach_training_plan_job";

  useEffect(()=>{
    void Promise.all([api<AnyObj>(`/coach/capabilities?locale=${lang}`),api<AnyObj[]>("/coach/training-plans?limit=30")]).then(([c,h])=>{
      setCaps(c);setHistory(h);const t=c.tasks?.training_plan??{};setModel(t.default_model_id??"");setTokens(t.max_output_tokens??4500);setCtx(t.context_window_tokens??8192);setPrompt(t.default_prompt??"");setQuality((t.quality_profile??"standard") as QualityId);if(h.length)setResult(h[0]);
    }).catch(e=>setError(String(e)));
    const j=localStorage.getItem(jobKey);if(j){setBusy(true);setJobId(j);void poll(j)}
  },[lang]);

  const task=caps?.tasks?.training_plan??{};const models=caps?.eligible_models??[];const selected=models.find((x:AnyObj)=>x.id===model);const modelCtxMax=Math.max(2048,Math.min(1048576,Number(selected?.context_window??1048576)));const modelOutMax=Math.max(128,Math.min(65536,Number(selected?.provider_max_output_tokens??65536)));const meta=result?.metadata??result??{};const usage=result?.usage??meta.usage??{};const truncated=Boolean(result?.truncated??meta.truncated);const outputAdjusted=Boolean(result?.output_budget_adjusted??meta.output_budget_adjusted);const requestedOut=result?.requested_max_output_tokens??meta.requested_max_output_tokens;
  const expectedSessions=weeks*days;const chunkWeeks=Math.max(1,Math.min(3,Math.floor(10/Math.max(1,days))));const estimatedCalls=expectedSessions>12?Math.ceil(weeks/chunkWeeks):1;
  const selectedContextLabels=[contextData.training?bi(lang,"Training/FIT","Training/FIT"):null,contextData.zones?bi(lang,"Zonen","Zones"):null,contextData.sleep_hrv?bi(lang,"Schlaf/HRV","Sleep/HRV"):null,contextData.recovery?bi(lang,"Erholung","Recovery"):null,contextData.daily_activity?bi(lang,"Schritte/Hydration","Steps/hydration"):null].filter(Boolean);

  async function poll(id:string){
    setStatus(de?"Trainingsplan wird im Hintergrund erstellt…":"Training plan is being generated in the background…");
    for(let i=0;i<1800;i++){
      if(ignoredJobs.current.has(id))return;
      try{
        const j=await api<AnyObj>(`/jobs/${id}`);
        if(ignoredJobs.current.has(id))return;
        if(j.ready){
          localStorage.removeItem(jobKey);setBusy(false);setJobId(null);setJobProgress(null);
          if(j.successful&&j.result?.cancelled){setStatus(de?"Erstellung abgebrochen":"Generation cancelled");return}
          if(j.successful&&j.result){setResult(j.result);setHistory(v=>[j.result,...v].slice(0,30));setStatus(de?"Plan fertig":"Plan ready");return}
          setError(friendlyPlanError(j.error||"AI job failed",lang));return;
        }
        setJobProgress(j.progress??null);setStatus(j.progress?.message||(de?"Trainingsplan wird erstellt…":"Training plan is being generated…"));
      }catch{}
      await sleep(1000);
    }
    setBusy(false);setJobId(null);
  }

  async function generate(e:FormEvent){
    e.preventDefault();if(busy||!model)return;setBusy(true);setError("");setJobProgress(null);setStatus(de?"Plan wird vorbereitet…":"Preparing plan…");
    try{
      const r=await api<AnyObj>("/coach/training-plan/jobs",{method:"POST",body:JSON.stringify({goal_type:goalType,goal_text:goalText,experience,weeks,days_per_week:days,session_minutes:minutes,equipment,constraints,context_days:contextDays,context_data:contextData,prompt:prompt||null,model_id:model,max_tokens:tokens,context_window_tokens:ctx,quality_profile:quality,locale:lang})});
      setJobId(r.task_id);localStorage.setItem(jobKey,r.task_id);void poll(r.task_id);
    }catch(e){setBusy(false);setError(e instanceof Error?e.message:String(e))}
  }

  async function cancelGeneration(){
    if(!jobId)return;const id=jobId;ignoredJobs.current.add(id);
    try{await api(`/jobs/${id}/cancel`,{method:"POST"})}catch{}
    localStorage.removeItem(jobKey);setBusy(false);setJobId(null);setJobProgress(null);setStatus(de?"Erstellung abgebrochen – Angaben können angepasst werden.":"Generation cancelled — you can adjust the request.");
  }

  async function changeQuality(value:QualityId,suggested:number){
    setQuality(value);setTokens(Math.max(128,Math.min(modelOutMax,suggested)));
    if(!caps)return;const tasks=caps.tasks??{};
    try{await api("/settings/ai-preferences",{method:"PUT",body:JSON.stringify({coach_chat:tasks.coach_chat?.quality_profile??"standard",activity_analysis:tasks.activity_analysis?.quality_profile??"standard",training_plan:value,monthly_budget_eur:caps.monthly_budget_eur??null})});setCaps((c:AnyObj)=>c?({...c,tasks:{...c.tasks,training_plan:{...c.tasks?.training_plan,quality_profile:value}}}):c)}catch{}
  }

  function setContextFlag(key:keyof ContextData,value:boolean){setContextData(v=>({...v,[key]:value}))}
  const runId=(x:AnyObj|null)=>x?.id??x?.run_id??null;
  async function askDelete(x:AnyObj){const id=runId(x);if(!id)return;setDeleteCandidate(x);setDeleteInfo(null);setDeleteStatus("");try{setDeleteInfo(await api<AnyObj>(`/coach/training-plans/${id}/delete-info`))}catch(e){setDeleteStatus(e instanceof Error?e.message:String(e))}}
  function removeLocalResult(id:string){setHistory(prev=>{const next=prev.filter(x=>runId(x)!==id);setResult(current=>runId(current)===id?(next[0]??null):current);return next})}
  async function deletePlan(mode:"local"|"garmin"){
    const id=runId(deleteCandidate);if(!id||deleteBusy)return;setDeleteBusy(true);setDeleteStatus(mode==="garmin"?bi(lang,"Garmin-Kalender wird bereinigt…","Cleaning Garmin calendar…"):bi(lang,"Plan wird gelöscht…","Deleting plan…"));
    try{
      if(mode==="local"){await api(`/coach/training-plans/${id}`,{method:"DELETE"});removeLocalResult(id)}else{
        const q=await api<AnyObj>(`/garmin/workout-export/delete-plan/${id}/jobs`,{method:"POST"});let completed=false;
        for(let i=0;i<900;i++){const j=await api<AnyObj>(`/jobs/${q.task_id}`);if(j.ready){if(!j.successful)throw new Error(j.error||"Garmin cleanup failed");if(!j.result?.deleted)throw new Error(bi(lang,"Einige Garmin-Einträge konnten nicht gelöscht werden. Der Plan bleibt erhalten und kann erneut bereinigt werden.","Some Garmin entries could not be removed. The plan is kept so cleanup can be retried."));removeLocalResult(id);completed=true;break}setDeleteStatus(j.progress?.message||bi(lang,"Garmin-Kalender wird bereinigt…","Cleaning Garmin calendar…"));await sleep(1000)}
        if(!completed)throw new Error(bi(lang,"Die Garmin-Bereinigung läuft länger als erwartet. Der Plan wurde nicht lokal gelöscht; bitte Status prüfen und erneut versuchen.","Garmin cleanup is taking longer than expected. The local plan was not deleted; please check status and try again."));
      }
      setDeleteCandidate(null);setDeleteInfo(null);setDeleteStatus("");
    }catch(e){setDeleteStatus(e instanceof Error?e.message:String(e))}finally{setDeleteBusy(false)}
  }

  return <AppShell>
    <div className="coach-modern-head"><div><span className="eyebrow">AI TRAINING PLANNER</span><h1>{bi(lang,"Trainingsplanung","Training planning")}</h1><p className="muted">{bi(lang,"Ziel definieren und der KI gezielt den aktuellen Trainings- und Erholungsstand mitgeben.","Define your goal and explicitly choose the recent training and recovery context shared with the AI.")}</p></div><div className="coach-model-chip"><span className={`ai-local-dot ${selected?.local?"local":"cloud"}`}/><div><small>{bi(lang,"Aktives Modell","Active model")}</small><strong>{selected?.display_name??task.default_model??"—"}</strong><span>{selected?.provider??task.default_provider??""}</span></div></div></div>

    <form className="card training-modern" onSubmit={generate}>
      <div className="training-step"><span>01</span><div><h2>{bi(lang,"Ziel & Rahmen","Goal & framework")}</h2><p className="muted">{bi(lang,"Was willst du erreichen und wie viel Zeit steht realistisch zur Verfügung?","What do you want to achieve and how much time is realistically available?")}</p></div></div>
      <div className="training-form-grid"><label>{bi(lang,"Ziel","Goal")}<select value={goalType} onChange={e=>setGoalType(e.target.value)}>{GOALS.map(x=><option key={x[0]} value={x[0]}>{de?x[1]:x[2]}</option>)}</select></label><label>{bi(lang,"Erfahrung","Experience")}<select value={experience} onChange={e=>setExperience(e.target.value)}><option value="beginner">{bi(lang,"Einsteiger","Beginner")}</option><option value="intermediate">{bi(lang,"Fortgeschritten","Intermediate")}</option><option value="advanced">{bi(lang,"Erfahren","Advanced")}</option></select></label><label>{bi(lang,"Wochen","Weeks")}<input type="number" min={1} max={24} value={weeks} onChange={e=>setWeeks(Number(e.target.value))}/></label><label>{bi(lang,"Trainingstage / Woche","Training days / week")}<input type="number" min={1} max={7} value={days} onChange={e=>setDays(Number(e.target.value))}/></label><label>{bi(lang,"Typische Session","Typical session")}<div className="ai-number-control"><input type="number" min={15} max={240} value={minutes} onChange={e=>setMinutes(Number(e.target.value))}/><span>min</span></div></label></div>
      <label>{bi(lang,"Dein konkretes Ziel","Your specific goal")}<textarea value={goalText} onChange={e=>setGoalText(e.target.value)} placeholder={bi(lang,"z. B. 10 km unter 50 Minuten, mehr Muskelmasse und trotzdem zweimal Rad pro Woche …","e.g. run 10K under 50 minutes, gain muscle while cycling twice a week …")}/></label>
      <div className="grid2"><label>{bi(lang,"Equipment / Möglichkeiten","Equipment / facilities")}<textarea value={equipment} onChange={e=>setEquipment(e.target.value)} placeholder={bi(lang,"Fitnessstudio, Hantelbank, Rennrad, Laufband …","Gym, bench, road bike, treadmill …")}/></label><label>{bi(lang,"Einschränkungen / feste Tage","Constraints / fixed days")}<textarea value={constraints} onChange={e=>setConstraints(e.target.value)} placeholder={bi(lang,"Mittwoch frei, werktags max. 90 Minuten …","Wednesday off, max 90 minutes on weekdays …")}/></label></div>

      <div className="training-step"><span>02</span><div><h2>{bi(lang,"Trainingskontext","Training context")}</h2><p className="muted">{bi(lang,"So wie beim Gespräch mit einem Coach: Zeitraum und die relevanten Daten auswählen. Standard sind die letzten 7 Tage.","Like briefing a coach: choose the recent period and which relevant data to share. The default is the last 7 days.")}</p></div></div>
      <div className="training-context-box">
        <div><strong>{bi(lang,"Zeitraum","Period")}</strong><div className="context-preset-row">{CONTEXT_DAYS.map(v=><button type="button" className={contextDays===v?"active":""} key={v} onClick={()=>setContextDays(v)}>{v} {bi(lang,"Tage","days")}</button>)}</div></div>
        <div><strong>{bi(lang,"Daten für den Coach","Data for the coach")}</strong><div className="context-data-grid">
          <label><input type="checkbox" checked={contextData.training} onChange={e=>setContextFlag("training",e.target.checked)}/><span><b>{bi(lang,"Training & FIT","Training & FIT")}</b><small>{bi(lang,"Einheiten, Umfang, Belastung und lokale FIT-Analytics","Sessions, volume, load and local FIT analytics")}</small></span></label>
          <label><input type="checkbox" checked={contextData.zones} onChange={e=>setContextFlag("zones",e.target.checked)}/><span><b>{bi(lang,"Garmin-Zonen","Garmin zones")}</b><small>{bi(lang,"Herzfrequenz- und Leistungszonen","Heart-rate and power zones")}</small></span></label>
          <label><input type="checkbox" checked={contextData.sleep_hrv} onChange={e=>setContextFlag("sleep_hrv",e.target.checked)}/><span><b>{bi(lang,"Schlaf & HRV","Sleep & HRV")}</b><small>{bi(lang,"Schlafdauer/-score und HRV-Verlauf","Sleep duration/score and HRV trend")}</small></span></label>
          <label><input type="checkbox" checked={contextData.recovery} onChange={e=>setContextFlag("recovery",e.target.checked)}/><span><b>{bi(lang,"Erholung & Stress","Recovery & stress")}</b><small>{bi(lang,"Ruhepuls, Stress, Body Battery, Readiness, VO₂max","Resting HR, stress, Body Battery, readiness, VO₂max")}</small></span></label>
          <label><input type="checkbox" checked={contextData.daily_activity} onChange={e=>setContextFlag("daily_activity",e.target.checked)}/><span><b>{bi(lang,"Schritte & Hydration","Steps & hydration")}</b><small>{bi(lang,"Optional – meist weniger wichtig für die Planstruktur","Optional — usually less important for plan structure")}</small></span></label>
        </div></div>
      </div>

      <div className="training-step"><span>03</span><div><h2>{bi(lang,"AI Budget","AI budget")}</h2><p className="muted">{bi(lang,"Kontext und Antwortlänge bewusst steuern. Bei Ollama wird num_ctx direkt gesetzt.","Control context and response length explicitly. For Ollama, num_ctx is set directly.")}</p></div></div>
      <div className="ai-analysis-settings"><label>{bi(lang,"Modell","Model")}<select value={model} onChange={e=>setModel(e.target.value)}>{models.map((x:AnyObj)=><option key={x.id} value={x.id}>{x.display_name} · {x.provider} · {x.local?"LOCAL":"CLOUD"}</option>)}</select></label><label>{bi(lang,"Kontextfenster","Context window")}<div className="ai-number-control"><input type="number" min={2048} max={modelCtxMax} step={1024} value={ctx} onChange={e=>setCtx(Math.max(2048,Math.min(modelCtxMax,Number(e.target.value))))}/><span>tokens</span></div></label><label>{bi(lang,"Max. Antwort","Max response")}<div className="ai-number-control"><input type="number" min={128} max={modelOutMax} step={1} value={tokens} onChange={e=>setTokens(Math.max(128,Math.min(modelOutMax,Number(e.target.value))))}/><span>tokens</span></div></label><div className="card subtle ai-budget"><span>{bi(lang,"Trainingskontext","Training context")}</span><strong>{contextDays} {bi(lang,"Tage","days")}</strong><small>{selectedContextLabels.length?selectedContextLabels.join(" · "):bi(lang,"nur Zielangaben","goal details only")}</small><small>ctx {ctx.toLocaleString()} · out {tokens.toLocaleString()}</small></div></div>
      <AiQualityControl lang={lang} profile={quality} onChange={(v,t)=>void changeQuality(v,t)} options={task.quality_profiles??[]} model={selected} contextWindow={ctx} maxOutput={tokens} calls={estimatedCalls}/>
      <p className="muted ai-budget-note">{bi(lang,`Die AI kennt ihr effektives Antwortlimit. Größere Pläne mit mehr als 12 Einheiten werden automatisch in Wochenblöcke geteilt, validiert und anschließend zusammengeführt. Max. Antwort gilt pro KI-Aufruf/Planabschnitt und ist nicht mehr auf den 8.000-Token-Taskstandard begrenzt; Modell-, Provider- und Kontextlimit bleiben maßgeblich.`,`The AI knows its effective response limit. Larger plans with more than 12 sessions are generated in week chunks, validated and merged automatically. Max response applies per AI call/plan segment and is no longer capped by the 8,000-token task default; model, provider and context limits still apply.`)}</p>
      {contextData.zones&&<TrainingZoneStatus/>}
      <details className="ai-prompt-details"><summary>{bi(lang,"Planungs-Prompt anzeigen / anpassen","Show / edit planning prompt")}</summary><textarea className="prompt-editor modern" value={prompt} onChange={e=>setPrompt(e.target.value)}/></details>
      <div className="between"><div>{status&&<span className={`ai-job-status ${busy?"running":""}`}>{busy&&<i/>}<span>{status}</span>{busy&&progressTokens(jobProgress)&&<b className="ai-token-live">{progressTokens(jobProgress)}</b>}</span>}{error&&<div className="status-bad">{error}</div>}</div><div className="row">{busy&&<button type="button" className="ghost danger" onClick={cancelGeneration}>{bi(lang,"Abbrechen","Cancel")}</button>}<button disabled={busy||!model}>{busy?bi(lang,"Plan läuft im Hintergrund…","Plan running in background…"):bi(lang,"Trainingsplan erstellen","Create training plan")}</button></div></div>
    </form>

    {result&&<section className="card ai-result-modern"><div className="ai-result-head"><div><span className="eyebrow">AI TRAINING PLAN</span><h2>{bi(lang,"Aktueller Plan","Current plan")}</h2></div><div className="ai-run-meta-modern"><strong>{result.model??result.model_name}</strong><div><span>{result.provider??result.provider_name}</span><span>{meta.training_context?.days??result.lookback_days??"—"}d</span><span>ctx {result.context_window_tokens??meta.context_window_tokens??"—"}</span><span>{result.max_output_tokens??"—"} out</span></div></div></div>{outputAdjusted&&<div className="ai-truncated-warning">ℹ {bi(lang,`Das effektive Antwortbudget wurde wegen des Kontextfensters von ${requestedOut??"?"} auf ${result?.max_output_tokens??"?"} Token reduziert.`,`The effective response budget was reduced by the context window from ${requestedOut??"?"} to ${result?.max_output_tokens??"?"} tokens.`)}</div>}{truncated&&<div className="ai-truncated-warning">⚠ {bi(lang,"Das Modell hat trotz budgetierter Kompaktausgabe das harte Antwortlimit erreicht. Erhöhe Max. Antwort bzw. das Kontextfenster oder reduziere Wochen/Trainingstage.","The model reached the hard response limit despite compact budget-aware output. Increase max response/context window or reduce weeks/training days.")}</div>}<div className="ai-content modern"><AiReport content={result.content}/></div><details className="training-calendar-details" open><summary>{bi(lang,"Kalender & Garmin","Calendar & Garmin")}</summary><TrainingPlanCalendar result={result} lang={lang}/></details><div className="ai-result-stats"><span>{usage.input_tokens??"?"} in</span><span>{usage.output_tokens??"?"} out</span><span>{meta.quality_profile??result.quality_profile??"standard"}</span>{(meta.cost_eur??result.cost_eur)!=null&&<span><strong>{euro(Number(meta.cost_eur??result.cost_eur))}</strong></span>}<span>{meta.stop_reason??result.stop_reason??"stop"}</span></div>{Array.isArray(meta.generation_calls)&&meta.generation_calls.length>0&&<details className="ai-usage-details"><summary>{bi(lang,"KI-Aufrufe & Tokenkosten anzeigen","Show AI calls & token cost")}</summary><div>{meta.generation_calls.map((c:AnyObj,i:number)=><div key={i}><span>{bi(lang,"Teil","Part")} {c.chunk_index}/{c.chunk_count} · {bi(lang,"Versuch","attempt")} {c.attempt}</span><span>{Number(c.usage?.input_tokens??0).toLocaleString()} in · {Number(c.usage?.output_tokens??0).toLocaleString()} out{c.elapsed_seconds!=null?` · ${Number(c.elapsed_seconds).toFixed(1)}s`:""}{c.tokens_per_second!=null?` · ${Number(c.tokens_per_second).toFixed(1)} out/s`:""}{c.cost_eur!=null?` · ${euro(Number(c.cost_eur))}`:""}</span></div>)}</div></details>}</section>}

    {history.length>0&&<section className="card"><div className="between"><div><h2>{bi(lang,"Trainingspläne verwalten","Manage training plans")}</h2><p className="muted">{bi(lang,"Auch Pläne aus früheren PenguCoach-Versionen können hier gelöscht werden.","Plans created by earlier PenguCoach versions can also be deleted here.")}</p></div><span className="badge">{history.length}</span></div><div className="plan-history">{history.map((x:AnyObj)=><div className={`history-row managed ${runId(result)===runId(x)?"active":""}`} key={runId(x)}><button className="history-row-main" type="button" onClick={()=>setResult(x)}><span><strong>{x.metadata?.goal?.goal_type??bi(lang,"Trainingsplan","Training plan")}</strong><small>{x.created_at?new Date(x.created_at).toLocaleString(de?"de-DE":"en-GB"):""}</small></span><span>{x.model??x.model_name}</span></button><button type="button" className="icon-danger" title={bi(lang,"Plan löschen","Delete plan")} onClick={()=>askDelete(x)}>×</button></div>)}</div></section>}

    {deleteCandidate&&<div className="modal-backdrop" role="dialog" aria-modal="true"><div className="card delete-plan-dialog"><span className="eyebrow">DELETE TRAINING PLAN</span><h2>{bi(lang,"Trainingsplan löschen?","Delete training plan?")}</h2><p>{bi(lang,"Der gespeicherte PenguCoach-Plan und seine lokale Historie werden entfernt.","The stored PenguCoach plan and its local history will be removed.")}</p>{Number(deleteInfo?.garmin_exported??0)>0?<div className="status-warn">{bi(lang,`${deleteInfo?.garmin_exported??0} Einheit(en) dieses Plans wurden zu Garmin exportiert. Soll PenguCoach diese auch aus dem Garmin-Kalender und den Garmin-Workouts entfernen?`,`${deleteInfo?.garmin_exported??0} session(s) from this plan were exported to Garmin. Should PenguCoach also remove them from the Garmin calendar and Garmin workouts?`)}</div>:deleteInfo===null?<p className="muted">{bi(lang,"Prüfe Garmin-Exportstatus…","Checking Garmin export status…")}</p>:<p className="muted">{bi(lang,"Für diesen Plan sind keine von PenguCoach exportierten Garmin-Einträge gespeichert.","No PenguCoach-exported Garmin entries are recorded for this plan.")}</p>}{deleteStatus&&<div className="muted">{deleteStatus}</div>}<div className="form-actions">{Number(deleteInfo?.garmin_exported??0)>0&&<button disabled={deleteBusy} onClick={()=>deletePlan("garmin")}>{bi(lang,"Auch aus Garmin löschen","Delete from Garmin too")}</button>}<button className="ghost danger" disabled={deleteBusy||deleteInfo===null} onClick={()=>deletePlan("local")}>{bi(lang,"Nur in PenguCoach löschen","Delete only in PenguCoach")}</button><button className="ghost" disabled={deleteBusy} onClick={()=>{setDeleteCandidate(null);setDeleteInfo(null);setDeleteStatus("")}}>{bi(lang,"Abbrechen","Cancel")}</button></div></div></div>}
  </AppShell>
}
