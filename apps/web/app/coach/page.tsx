"use client";

import {FormEvent,useEffect,useRef,useState} from "react";
import AppShell from "../../components/AppShell";
import AiReport from "../../components/AiReport";
import TrainingZoneStatus from "../../components/TrainingZoneStatus";
import {api} from "../../lib/api";
import {bi,useI18n} from "../../lib/i18n";

type M={role:"user"|"assistant";content:string;meta?:string;warning?:boolean};
type AnyObj=Record<string,any>;
const sleep=(ms:number)=>new Promise(r=>setTimeout(r,ms));

function progressTokens(progress:AnyObj|null){
  if(!progress)return"";const exact=progress.output_tokens_exact;const estimate=progress.output_tokens_estimate;const used=exact??estimate;if(used==null)return"";const max=progress.max_output_tokens;return `${exact==null?"≈ ":""}${Number(used).toLocaleString()}${max?` / ${Number(max).toLocaleString()}`:""} Tokens`;
}

export default function Coach(){
  const{lang}=useI18n();const de=lang!=="en";
  const[text,setText]=useState(""),[msgs,setMsgs]=useState<M[]>([]),[cid,setCid]=useState<string|undefined>(),[busy,setBusy]=useState(false),[jobText,setJobText]=useState("");
  const[jobId,setJobId]=useState<string|null>(null),[jobProgress,setJobProgress]=useState<AnyObj|null>(null),[pendingPrompt,setPendingPrompt]=useState("");
  const ignoredJobs=useRef<Set<string>>(new Set());
  const[caps,setCaps]=useState<AnyObj|null>(null),[model,setModel]=useState(""),[tokens,setTokens]=useState(2500),[ctx,setCtx]=useState(8192),[contextMode,setContextMode]=useState("auto"),[settingsOpen,setSettingsOpen]=useState(false);
  const task=caps?.tasks?.coach_chat??{};const models=caps?.eligible_models??[];const selected=models.find((x:AnyObj)=>x.id===model);
  const estimatedInput=Math.max(0,ctx-tokens-768);

  useEffect(()=>{void api<AnyObj>(`/coach/capabilities?locale=${lang}`).then(c=>{setCaps(c);const t=c.tasks?.coach_chat??{};setModel(t.default_model_id??"");setTokens(t.max_output_tokens??2500);setCtx(t.context_window_tokens??8192)}).catch(()=>{})},[lang]);
  useEffect(()=>{const j=localStorage.getItem("pengucoach_coach_job");if(j){setBusy(true);setJobId(j);setPendingPrompt(localStorage.getItem("pengucoach_coach_pending_prompt")??"");void poll(j)}const c=localStorage.getItem("pengucoach_conversation");if(c)setCid(c)},[]);

  async function poll(id:string){
    setJobText(de?"Coach denkt…":"Coach is thinking…");
    for(let i=0;i<1200;i++){
      if(ignoredJobs.current.has(id))return;
      try{
        const j=await api<AnyObj>(`/jobs/${id}`);if(ignoredJobs.current.has(id))return;
        if(j.ready){
          localStorage.removeItem("pengucoach_coach_job");localStorage.removeItem("pengucoach_coach_pending_prompt");setBusy(false);setJobId(null);setJobProgress(null);
          if(j.successful&&j.result?.cancelled){setJobText(de?"Anfrage abgebrochen":"Request cancelled");return}
          if(j.successful&&j.result){const r=j.result;setCid(r.conversation_id);localStorage.setItem("pengucoach_conversation",r.conversation_id);const u=r.usage??{};const meta=`${r.local?"LOCAL":"CLOUD"} · ${r.model} · ${r.data_used?.context_days??0}d · ${u.input_tokens??"?"} in / ${u.output_tokens??"?"} out · ctx ${r.context_window_tokens??"?"}`;setMsgs(v=>[...v,{role:"assistant",content:r.content,meta,warning:Boolean(r.truncated)}]);setJobText("");setPendingPrompt("");return}
          setMsgs(v=>[...v,{role:"assistant",content:j.error||"AI job failed"}]);setJobText("");return;
        }
        setJobProgress(j.progress??null);setJobText(j.progress?.message||(de?"Coach denkt…":"Coach is thinking…"));
      }catch{}
      await sleep(1000);
    }
    setBusy(false);setJobId(null);setJobText(de?"Job läuft weiter – Seite kann später neu geladen werden.":"Job is still running — you can reload later.");
  }

  async function submit(e:FormEvent){
    e.preventDefault();if(!text.trim()||busy||!model)return;const q=text.trim();setText("");setPendingPrompt(q);localStorage.setItem("pengucoach_coach_pending_prompt",q);setMsgs(v=>[...v,{role:"user",content:q}]);setBusy(true);setJobProgress(null);
    try{const r=await api<AnyObj>("/coach/chat/jobs",{method:"POST",body:JSON.stringify({message:q,conversation_id:cid,model_id:model,max_tokens:tokens,context_window_tokens:ctx,context_mode:contextMode,locale:lang})});setJobId(r.task_id);localStorage.setItem("pengucoach_coach_job",r.task_id);void poll(r.task_id)}catch(e){setBusy(false);setJobId(null);setMsgs(v=>[...v,{role:"assistant",content:e instanceof Error?e.message:"Error"}])}
  }

  async function cancelJob(){
    if(!jobId)return;const id=jobId;ignoredJobs.current.add(id);try{await api(`/jobs/${id}/cancel`,{method:"POST"})}catch{}
    localStorage.removeItem("pengucoach_coach_job");localStorage.removeItem("pengucoach_coach_pending_prompt");setBusy(false);setJobId(null);setJobProgress(null);setJobText(de?"Anfrage abgebrochen – Text wurde wiederhergestellt.":"Request cancelled — text restored.");if(pendingPrompt)setText(pendingPrompt);
  }

  const budgetPct=Math.min(100,Math.max(0,(estimatedInput/ctx)*100));
  return <AppShell>
    <div className="coach-modern-head"><div><span className="eyebrow">PENGUCOACH AI</span><h1>{bi(lang,"Coach","Coach")}</h1><p className="muted">{bi(lang,"Frag frei – PenguCoach fügt Trainingsdaten nur hinzu, wenn sie zur Frage passen.","Ask freely — PenguCoach only adds training context when it is relevant to your question.")}</p></div><div className="coach-model-chip"><span className={`ai-local-dot ${selected?.local?"local":"cloud"}`}/><div><small>{bi(lang,"Aktives Modell","Active model")}</small><strong>{selected?.display_name??task.default_model??"—"}</strong><span>{selected?.provider??task.default_provider??""}</span></div></div></div>

    <div className="coach-layout">
      <section className="card coach-thread">
        <div className="coach-thread-top"><div><strong>{bi(lang,"Neue Unterhaltung","New conversation")}</strong><small>{contextMode==="auto"?bi(lang,"Kontext automatisch","Context automatic"):contextMode==="none"?bi(lang,"Ohne Trainingskontext","No training context"):`${contextMode}d Garmin/FIT`}</small></div><div className="ai-live-group">{jobText&&<span className="ai-running"><i/> {jobText}{busy&&progressTokens(jobProgress)&&<b className="ai-token-live">{progressTokens(jobProgress)}</b>}</span>}{busy&&<button type="button" className="ghost danger compact" onClick={cancelJob}>{bi(lang,"Abbrechen","Cancel")}</button>}</div></div>
        <div className="coach-messages">{msgs.length?msgs.map((m,i)=><div key={i} className={`coach-message ${m.role}`}><div className="coach-message-role">{m.role==="user"?(de?"Du":"You"):"PenguCoach"}</div><div className="coach-message-body">{m.role==="assistant"?<AiReport content={m.content}/>:m.content}</div>{m.warning&&<div className="ai-truncated-warning">⚠ {bi(lang,"Antwortlimit erreicht – die Antwort ist möglicherweise abgeschnitten.","Response limit reached — the answer may be truncated.")}</div>}{m.meta&&<small>{m.meta}</small>}</div>):<div className="coach-empty"><div className="coach-orb">✦</div><h2>{bi(lang,"Was möchtest du wissen?","What would you like to know?")}</h2><p>{bi(lang,"Zum Beispiel: „Analysiere meine letzten 7 Tage“, „Warum war meine letzte Ausfahrt so hart?“ oder auch eine allgemeine Frage ohne Trainingskontext.","For example: “Analyse my last 7 days”, “Why was my last ride so hard?” or a general question without training context.")}</p><div className="coach-suggestions">{(de?["Analysiere meine Belastung der letzten 7 Tage","Wie entwickelt sich meine Ausdauer?","Was wäre heute ein sinnvolles Training?"]: ["Analyse my load over the last 7 days","How is my endurance developing?","What would be a sensible session today?"]).map(x=><button type="button" className="ghost" key={x} onClick={()=>setText(x)}>{x}</button>)}</div></div>}</div>
        <form className="coach-composer" onSubmit={submit}><textarea value={text} onChange={e=>setText(e.target.value)} placeholder={bi(lang,"Frage an PenguCoach…","Ask PenguCoach…")}/><div className="coach-composer-actions"><button type="button" className="ghost compact" onClick={()=>setSettingsOpen(v=>!v)}>⚙ {bi(lang,"Kontext & Modell","Context & model")}</button><button disabled={busy||!model||!text.trim()}>{busy?"…":bi(lang,"Senden","Send")}</button></div></form>
      </section>

      <aside className={`card coach-side ${settingsOpen?"open":""}`}><div className="between"><div><h2>{bi(lang,"AI Einstellungen","AI settings")}</h2><p className="muted">{bi(lang,"Pro Anfrage anpassbar","Adjustable per request")}</p></div></div>
        <label>{bi(lang,"Modell","Model")}<select value={model} onChange={e=>setModel(e.target.value)}>{models.length===0&&<option value="">{bi(lang,"Keine Modelle verfügbar","No models available")}</option>}{models.map((x:AnyObj)=><option value={x.id} key={x.id}>{x.display_name} · {x.provider} · {x.local?"LOCAL":"CLOUD"}</option>)}</select></label>
        {models.length===0&&<div className="cloud-model-empty"><strong>{bi(lang,"Kein freigegebenes KI-Modell","No permitted AI model")}</strong><span>{bi(lang,"Wenn du nur ein externes Modell eingerichtet hast, prüfe die Cloud-KI-Freigabe unter Datenschutz.","If you configured only an external model, check the cloud AI permission under Privacy.")}</span><a href="/settings/privacy">{bi(lang,"Datenschutz öffnen","Open privacy")}</a></div>}
        <label>{bi(lang,"Trainingskontext","Training context")}<select value={contextMode} onChange={e=>setContextMode(e.target.value)}><option value="auto">{bi(lang,"Auto · nur wenn relevant","Auto · only when relevant")}</option><option value="none">{bi(lang,"Kein Kontext","No context")}</option><option value="7">7 {bi(lang,"Tage","days")}</option><option value="28">28 {bi(lang,"Tage","days")}</option></select></label>
        <label>{bi(lang,"Kontextfenster","Context window")}<div className="ai-number-control"><input type="number" min={2048} max={task.context_window_tokens??262144} step={1024} value={ctx} onChange={e=>setCtx(Math.min(task.context_window_tokens??262144,Number(e.target.value)))}/><span>tokens</span></div></label>
        <div className="ai-preset-row">{[4096,8192,16384,32768,65536].filter(v=>v<=(task.context_window_tokens??8192)).map(v=><button type="button" className={ctx===v?"active":""} key={v} onClick={()=>setCtx(v)}>{v/1024}K</button>)}</div>
        <label>{bi(lang,"Max. Antwort","Max response")}<div className="ai-number-control"><input type="number" min={128} max={task.max_output_tokens??8192} step={1} value={tokens} onChange={e=>setTokens(Math.min(task.max_output_tokens??8192,Number(e.target.value)))}/><span>tokens</span></div></label>
        <div className="coach-budget"><div><span>{bi(lang,"Input-Budget","Input budget")}</span><strong>≈ {estimatedInput.toLocaleString()}</strong></div><div><span>{bi(lang,"Antwort","Response")}</span><strong>{tokens.toLocaleString()}</strong></div><div className="coach-budget-track"><i style={{width:`${budgetPct}%`}}/></div></div>
        <small>{selected?.local?bi(lang,"Ollama: Ausgabe wird live gestreamt; Tokenfortschritt ist während der Generierung sichtbar.","Ollama: output is streamed live; token progress is visible while generating."):bi(lang,"Cloud: Tokenlimits begrenzen die Anfrage und helfen Kosten zu kontrollieren.","Cloud: token limits cap the request and help control cost.")}</small>
        <TrainingZoneStatus compact/>
      </aside>
    </div>
  </AppShell>
}
