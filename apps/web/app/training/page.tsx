"use client";

import {FormEvent,useEffect,useRef,useState} from "react";
import ContextPicker,{defaultContext,type ContextData} from "../../components/ContextPicker";
import CoachPersonal from "../../components/CoachPersonal";
import AppShell from "../../components/AppShell";
import AiReport from "../../components/AiReport";
import TrainingZoneStatus from "../../components/TrainingZoneStatus";
import TrainingPlanCalendar from "../../components/TrainingPlanCalendar";
import AiQualityControl from "../../components/AiQualityControl";
import {api} from "../../lib/api";
import {bi,useI18n,type Lang} from "../../lib/i18n";
import {euro,type QualityId} from "../../lib/aiUsage";

type AnyObj=Record<string,any>;
type WizardStep=1|2|3|4;
const sleep=(ms:number)=>new Promise(r=>setTimeout(r,ms));
const GOALS=[
  ["muscle_gain","Muskelaufbau","Muscle gain"],["cardio_endurance","Cardio / Ausdauer","Cardio / endurance"],["hybrid","Hybrid · Kraft + Ausdauer","Hybrid · strength + endurance"],["cycling_endurance","Radsport-Ausdauer","Cycling endurance"],["running_5k","Laufen · 5 km","Running · 5K"],["running_10k","Laufen · 10 km","Running · 10K"],["half_marathon","Halbmarathon","Half marathon"],["marathon","Marathon","Marathon"],["strength","Kraft","Strength"],["general_fitness","Allgemeine Fitness","General fitness"],["mobility","Mobilität","Mobility"],["custom","Eigenes Ziel","Custom goal"],
];
const CONTEXT_DAYS=[3,7,14,21,28];
function defaultMonday(){const now=new Date();now.setHours(12,0,0,0);const iso=((now.getDay()+6)%7)+1;const add=iso===1?0:8-iso;now.setDate(now.getDate()+add);return now.toISOString().slice(0,10)}
function isMonday(value:string){if(!value)return false;const d=new Date(`${value}T12:00:00`);return Number.isFinite(d.getTime())&&d.getDay()===1}
function runId(x:AnyObj|null){return x?.id??x?.run_id??null}
function planTitle(x:AnyObj,lang:Lang){return x?.metadata?.structured_plan?.title??x?.metadata?.goal?.goal_text??x?.metadata?.goal?.goal_type??bi(lang,"Trainingsplan","Training plan")}
function planWeeks(x:AnyObj){return Number(x?.metadata?.structured_plan?.weeks??x?.metadata?.goal?.weeks??0)}
function planSessions(x:AnyObj){return Array.isArray(x?.metadata?.structured_plan?.sessions)?x.metadata.structured_plan.sessions.length:0}
function planStartValue(x:AnyObj){return x?.metadata?.goal?.start_date??""}
function formatDate(value:string,de:boolean){if(!value)return "—";const d=new Date(`${value}T12:00:00`);return Number.isFinite(d.getTime())?d.toLocaleDateString(de?"de-DE":"en-GB"):value}

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
  const[jobId,setJobId]=useState<string|null>(null),[jobProgress,setJobProgress]=useState<AnyObj|null>(null),[activeJobSummary,setActiveJobSummary]=useState<AnyObj|null>(null),[jobLookup,setJobLookup]=useState(true);
  const ignoredJobs=useRef<Set<string>>(new Set());
  const[deleteCandidate,setDeleteCandidate]=useState<AnyObj|null>(null),[deleteInfo,setDeleteInfo]=useState<AnyObj|null>(null),[deleteBusy,setDeleteBusy]=useState(false),[deleteStatus,setDeleteStatus]=useState("");
  const[usePersonal,setUsePersonal]=useState(true),[profileStatus,setProfileStatus]=useState("");
  const[goalType,setGoalType]=useState("hybrid"),[goalText,setGoalText]=useState(""),[experience,setExperience]=useState("intermediate"),[weeks,setWeeks]=useState(8),[days,setDays]=useState(4),[minutes,setMinutes]=useState(60),[equipment,setEquipment]=useState(""),[constraints,setConstraints]=useState("");
  const[planStart,setPlanStart]=useState(defaultMonday()),[weather,setWeather]=useState<AnyObj|null>(null),[includeWeather,setIncludeWeather]=useState(false);
  const[contextDays,setContextDays]=useState(7),[contextData,setContextData]=useState<ContextData>(defaultContext);
  const[model,setModel]=useState(""),[tokens,setTokens]=useState(4500),[ctx,setCtx]=useState(8192),[prompt,setPrompt]=useState(""),[quality,setQuality]=useState<QualityId>("standard");
  const[wizardStep,setWizardStep]=useState<WizardStep>(1),[plannerOpen,setPlannerOpen]=useState(false),[planOpen,setPlanOpen]=useState(false);
  const jobKey="pengucoach_training_plan_job";

  useEffect(()=>{
    const storedJob=localStorage.getItem(jobKey);
    void Promise.all([
      api<AnyObj>(`/coach/capabilities?locale=${lang}`),
      api<AnyObj[]>("/coach/training-plans?limit=30"),
      api<AnyObj>("/jobs/active?job_type=training_plan").catch(()=>({active:false})),
    ]).then(([c,h,a])=>{
      setCaps(c);setHistory(h);const t=c.tasks?.training_plan??{};setModel(t.default_model_id??"");setTokens(t.max_output_tokens??4500);setCtx(t.context_window_tokens??8192);setPrompt(t.default_prompt??"");setQuality((t.quality_profile??"standard") as QualityId);
      if(h.length){setResult(h[0]);setPlanOpen(false)}
      const activeId=(a?.active&&a?.task_id)?String(a.task_id):storedJob;
      if(activeId){
        localStorage.setItem(jobKey,activeId);setBusy(true);setJobId(activeId);setActiveJobSummary(a?.summary??null);setJobProgress(a?.progress??null);setPlannerOpen(false);setWizardStep(4);void poll(activeId);
      }else{
        localStorage.removeItem(jobKey);setBusy(false);setJobId(null);setActiveJobSummary(null);setPlannerOpen(!h.length);
      }
    }).catch(e=>setError(String(e))).finally(()=>setJobLookup(false));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  },[lang]);
  useEffect(()=>{void api<AnyObj>("/weather/settings").then(w=>{setWeather(w);setIncludeWeather(Boolean(w.enabled&&w.include_in_training_plans))}).catch(()=>{setWeather(null);setIncludeWeather(false)})},[]);

  const task=caps?.tasks?.training_plan??{};
  const models=caps?.eligible_models??[];
  const selected=models.find((x:AnyObj)=>x.id===model);
  const modelCtxMax=Math.max(2048,Math.min(1048576,Number(selected?.context_window??1048576)));
  const modelOutMax=Math.max(128,Math.min(65536,Number(selected?.provider_max_output_tokens??65536)));
  const meta=result?.metadata??result??{};
  const usage=result?.usage??meta.usage??{};
  const truncated=Boolean(result?.truncated??meta.truncated);
  const outputAdjusted=Boolean(result?.output_budget_adjusted??meta.output_budget_adjusted);
  const requestedOut=result?.requested_max_output_tokens??meta.requested_max_output_tokens;
  const expectedSessions=weeks*days;
  const chunkWeeks=Math.max(1,Math.min(3,Math.floor(10/Math.max(1,days))));
  const estimatedCalls=expectedSessions>12?Math.ceil(weeks/chunkWeeks):1;
  const selectedContextLabels=[contextData.training?bi(lang,"Training/FIT","Training/FIT"):null,contextData.zones?bi(lang,"Zonen","Zones"):null,contextData.sleep_hrv?bi(lang,"Schlaf/HRV","Sleep/HRV"):null,contextData.recovery?bi(lang,"Erholung","Recovery"):null,contextData.daily_activity?bi(lang,"Alltagsbewegung","Daily movement"):null,contextData.hydration?bi(lang,"Trinkmenge","Water intake"):null,contextData.body?bi(lang,"Körperwerte","Body metrics"):null].filter(Boolean) as string[];

  async function poll(id:string){
    setStatus(de?"Trainingsplan wird im Hintergrund erstellt…":"Training plan is being generated in the background…");
    for(let i=0;i<1800;i++){
      if(ignoredJobs.current.has(id))return;
      try{
        const j=await api<AnyObj>(`/jobs/${id}`);
        if(ignoredJobs.current.has(id))return;
        if(j.ready){
          localStorage.removeItem(jobKey);setBusy(false);setJobId(null);setJobProgress(null);setActiveJobSummary(null);
          if(j.successful&&j.result?.cancelled){setStatus(de?"Erstellung abgebrochen":"Generation cancelled");return}
          if(j.successful&&j.result){setResult(j.result);setHistory(v=>[j.result,...v.filter(x=>runId(x)!==runId(j.result))].slice(0,30));setStatus(de?"Plan fertig":"Plan ready");setPlanOpen(true);setPlannerOpen(false);setTimeout(()=>document.getElementById("training-plan-detail")?.scrollIntoView({behavior:"smooth",block:"start"}),80);return}
          setError(friendlyPlanError(j.error||"AI job failed",lang));return;
        }
        setJobProgress(j.progress??null);setStatus(j.progress?.message||(de?"Trainingsplan wird erstellt…":"Training plan is being generated…"));
      }catch{}
      await sleep(1000);
    }
    setBusy(false);setJobId(null);setActiveJobSummary(null);
  }

  async function generate(e:FormEvent){
    e.preventDefault();if(busy||jobLookup||!model)return;
    if(!isMonday(planStart)){setError(bi(lang,"Der Planstart muss ein Montag sein, damit Wochen, Wetter und Garmin-Kalender eindeutig zusammenpassen.","The plan start must be a Monday so weeks, weather and the Garmin calendar stay aligned."));return}
    setBusy(true);setError("");setJobProgress(null);setStatus(de?"Plan wird vorbereitet…":"Preparing plan…");
    try{
      const r=await api<AnyObj>("/coach/training-plan/jobs",{method:"POST",body:JSON.stringify({use_personal_context:usePersonal,goal_type:goalType,goal_text:goalText,experience,weeks,days_per_week:days,session_minutes:minutes,equipment,constraints,context_days:contextDays,context_data:contextData,start_date:planStart,include_weather:includeWeather,prompt:prompt||null,model_id:model,max_tokens:tokens,context_window_tokens:ctx,quality_profile:quality,locale:lang})});
      setJobId(r.task_id);setActiveJobSummary(r.summary??{goal_type:goalType,goal_text:goalText,weeks,days_per_week:days,session_minutes:minutes,start_date:planStart,model_id:model});localStorage.setItem(jobKey,r.task_id);setPlannerOpen(false);setWizardStep(4);void poll(r.task_id);
    }catch(e){setBusy(false);setError(e instanceof Error?e.message:String(e))}
  }

  async function cancelGeneration(){
    if(!jobId)return;const id=jobId;ignoredJobs.current.add(id);
    try{await api(`/jobs/${id}/cancel`,{method:"POST"})}catch{}
    localStorage.removeItem(jobKey);setBusy(false);setJobId(null);setJobProgress(null);setActiveJobSummary(null);setStatus(de?"Erstellung abgebrochen – Angaben können angepasst werden.":"Generation cancelled — you can adjust the request.");
  }

  async function changeQuality(value:QualityId,suggested:number){
    setQuality(value);setTokens(Math.max(128,Math.min(modelOutMax,suggested)));
    if(!caps)return;const tasks=caps.tasks??{};
    try{await api("/settings/ai-preferences",{method:"PUT",body:JSON.stringify({coach_chat:tasks.coach_chat?.quality_profile??"standard",activity_analysis:tasks.activity_analysis?.quality_profile??"standard",training_plan:value,monthly_budget_eur:caps.monthly_budget_eur??null})});setCaps((c:AnyObj)=>c?({...c,tasks:{...c.tasks,training_plan:{...c.tasks?.training_plan,quality_profile:value}}}):c)}catch{}
  }

  async function loadProfile(){
    try{
      const p=await api<AnyObj>("/coach/profile");
      setGoalText(p.goal||"");setEquipment(p.equipment||"");
      setConstraints([p.constraints,p.preferences?`${bi(lang,"Präferenzen","Preferences")}: ${p.preferences}`:"",p.avoidances?`${bi(lang,"Vermeiden","Avoid")}: ${p.avoidances}`:"",p.training_days?.length?`${bi(lang,"Verfügbare ISO-Wochentage","Available ISO weekdays")}: ${p.training_days.join(", ")}`:""].filter(Boolean).join("\n"));
      if(p.session_minutes)setMinutes(Number(p.session_minutes));setUsePersonal(p.enabled!==false);setProfileStatus(bi(lang,"Coach-Profil übernommen.","Coach profile applied."));
    }catch(e){setProfileStatus(e instanceof Error?e.message:String(e))}
  }

  async function askDelete(x:AnyObj){const id=runId(x);if(!id)return;setDeleteCandidate(x);setDeleteInfo(null);setDeleteStatus("");try{setDeleteInfo(await api<AnyObj>(`/coach/training-plans/${id}/delete-info`))}catch(e){setDeleteStatus(e instanceof Error?e.message:String(e))}}
  function removeLocalResult(id:string){setHistory(prev=>{const next=prev.filter(x=>runId(x)!==id);setResult(current=>runId(current)===id?(next[0]??null):current);if(runId(result)===id)setPlanOpen(false);return next})}
  async function deletePlan(mode:"local"|"garmin"){
    const id=runId(deleteCandidate);if(!id||deleteBusy)return;setDeleteBusy(true);setDeleteStatus(mode==="garmin"?bi(lang,"Garmin-Kalender wird bereinigt…","Cleaning Garmin calendar…"):bi(lang,"Plan wird gelöscht…","Deleting plan…"));
    try{
      if(mode==="local"){await api(`/coach/training-plans/${id}`,{method:"DELETE"});removeLocalResult(id)}else{
        const q=await api<AnyObj>(`/garmin/workout-export/delete-plan/${id}/jobs`,{method:"POST"});let completed=false;
        for(let i=0;i<900;i++){const j=await api<AnyObj>(`/jobs/${q.task_id}`);if(j.ready){if(!j.successful)throw new Error(j.error||"Garmin cleanup failed");if(!j.result?.deleted)throw new Error(bi(lang,"Einige Garmin-Einträge konnten nicht gelöscht werden. Der Plan bleibt erhalten und kann erneut bereinigt werden.","Some Garmin entries could not be removed. The plan is kept so cleanup can be retried."));removeLocalResult(id);completed=true;break}setDeleteStatus(j.progress?.message||bi(lang,"Garmin-Kalender wird bereinigt…","Cleaning Garmin calendar…"));await sleep(1200)}
        if(!completed)throw new Error(bi(lang,"Die Garmin-Bereinigung läuft länger als erwartet. Der Plan wurde nicht lokal gelöscht; bitte Status prüfen und erneut versuchen.","Garmin cleanup is taking longer than expected. The local plan was not deleted; please check status and try again."));
      }
      setDeleteCandidate(null);setDeleteInfo(null);setDeleteStatus("");
    }catch(e){setDeleteStatus(e instanceof Error?e.message:String(e))}finally{setDeleteBusy(false)}
  }

  function openPlan(x:AnyObj){setResult(x);setPlanOpen(true);setPlannerOpen(false);setTimeout(()=>document.getElementById("training-plan-detail")?.scrollIntoView({behavior:"smooth",block:"start"}),60)}
  function openLatest(){if(history[0])openPlan(history[0])}
  function showRunningJob(){setPlanOpen(false);setPlannerOpen(true);setWizardStep(4);setTimeout(()=>document.getElementById("training-planner")?.scrollIntoView({behavior:"smooth",block:"start"}),60)}
  function startPlanner(){if(busy){showRunningJob();return}setPlanOpen(false);setPlannerOpen(true);setWizardStep(1);setTimeout(()=>document.getElementById("training-planner")?.scrollIntoView({behavior:"smooth",block:"start"}),60)}
  function goCoach(){const q=de?"Prüfe meinen aktuellen Trainingsplan anhand meiner aktuellen Readiness, der letzten Trainings, meines Profils und des Wetters. Schlage nur Änderungen vor, wenn sie sinnvoll sind.":"Review my current training plan using my current readiness, recent training, profile and weather. Only suggest changes when they are useful.";window.location.href=`/coach?prompt=${encodeURIComponent(q)}`}

  const stepLabels=[bi(lang,"Ziel","Goal"),bi(lang,"Rahmen","Framework"),bi(lang,"Daten","Data"),bi(lang,"Prüfen","Review")];
  const latest=history[0]??null;
  const activeGoal=GOALS.find(x=>x[0]===activeJobSummary?.goal_type);
  const activeGoalLabel=activeGoal?(de?activeGoal[1]:activeGoal[2]):bi(lang,"Trainingsplan","Training plan");

  return <AppShell>
    <div className="coach-modern-head"><div><span className="eyebrow">AI TRAINING PLANNER</span><h1>{bi(lang,"Training","Training")}</h1><p className="muted">{bi(lang,"Planen, verwalten und mit deinem Coach anpassen – ohne alle Details gleichzeitig sehen zu müssen.","Plan, manage and adapt with your coach without showing every detail at once.")}</p></div><div className="coach-model-chip"><span className={`ai-local-dot ${selected?.local?"local":"cloud"}`}/><div><small>{bi(lang,"Aktives Modell","Active model")}</small><strong>{selected?.display_name??model??"—"}</strong><span>{selected?.provider??""}</span></div></div></div>

    <section className="card training-assistant-home">
      <div className="training-assistant-copy"><span className="eyebrow">PENGUCOACH</span><h2>{bi(lang,"Was möchtest du machen?","What would you like to do?")}</h2><p className="muted">{bi(lang,"Der Assistent zeigt dir nur die Einstellungen, die du im jeweiligen Schritt brauchst.","The assistant only shows the settings you need in each step.")}</p></div>
      <div className="training-assistant-actions">
        <button type="button" disabled={jobLookup} className={`${plannerOpen?"active":""} ${busy?"job-running":""}`} onClick={startPlanner}><span>{busy?"●":"＋"}</span><strong>{jobLookup?bi(lang,"Planstatus wird geprüft…","Checking plan status…"):busy?bi(lang,"Plan wird bereits erstellt","Plan is already being generated"):bi(lang,"Neuen Plan erstellen","Create a new plan")}</strong><small>{busy?bi(lang,"Laufenden Auftrag ansehen – kein zweiter Plan wird gestartet","View the running job — no second plan will be started"):bi(lang,"Geführt in vier kurzen Schritten","Guided in four short steps")}</small></button>
        <button type="button" disabled={!latest} onClick={openLatest}><span>▣</span><strong>{bi(lang,"Aktuellen Plan ansehen","View current plan")}</strong><small>{latest?`${planWeeks(latest)||"—"} ${bi(lang,"Wochen","weeks")} · ${planSessions(latest)} ${bi(lang,"Einheiten","sessions")}`:bi(lang,"Noch kein Plan vorhanden","No plan yet")}</small></button>
        <button type="button" disabled={!latest} onClick={goCoach}><span>✦</span><strong>{bi(lang,"Plan mit Coach prüfen","Review plan with Coach")}</strong><small>{bi(lang,"Readiness, Training, Profil & Wetter","Readiness, training, profile & weather")}</small></button>
      </div>
    </section>

    {busy&&<section className="card training-running-job" role="status" aria-live="polite"><div className="training-running-job-main"><span className="training-running-pulse"/><div><span className="eyebrow">{bi(lang,"PLANERSTELLUNG LÄUFT","PLAN GENERATION RUNNING")}</span><h3>{activeGoalLabel}{activeJobSummary?.weeks?` · ${activeJobSummary.weeks} ${bi(lang,"Wochen","weeks")}`:""}</h3><p className="muted">{status||bi(lang,"Trainingsplan wird im Hintergrund erstellt…","Training plan is being generated in the background…")}</p><div className="training-running-meta">{jobProgress?.chunk_index&&jobProgress?.chunk_count&&<span>{bi(lang,"Teil","Part")} {jobProgress.chunk_index}/{jobProgress.chunk_count}</span>}{progressTokens(jobProgress)&&<span>{progressTokens(jobProgress)}</span>}{activeJobSummary?.start_date&&<span>{bi(lang,"Start","Start")}: {formatDate(activeJobSummary.start_date,de)}</span>}</div></div></div><div className="training-running-job-actions"><button type="button" className="ghost" onClick={showRunningJob}>{bi(lang,"Details ansehen","View details")}</button><button type="button" className="ghost danger" onClick={cancelGeneration}>{bi(lang,"Abbrechen","Cancel")}</button></div></section>}

    <CoachPersonal/>

    {plannerOpen&&<form id="training-planner" className="card training-modern training-wizard" onSubmit={generate}>
      <div className="planner-head"><div><span className="eyebrow">NEW TRAINING PLAN</span><h2>{bi(lang,"Trainingsplan-Assistent","Training plan assistant")}</h2></div><button type="button" className="ghost compact" onClick={()=>setPlannerOpen(false)}>{bi(lang,"Schließen","Close")}</button></div>
      <div className="planner-stepper" role="tablist" aria-label={bi(lang,"Schritte der Trainingsplanung","Training planning steps")}>{stepLabels.map((label,i)=>{const n=(i+1) as WizardStep;return <button type="button" key={label} className={`${wizardStep===n?"active":""} ${wizardStep>n?"done":""}`} aria-current={wizardStep===n?"step":undefined} onClick={()=>setWizardStep(n)}><span>{wizardStep>n?"✓":String(n).padStart(2,"0")}</span><strong>{label}</strong></button>})}</div>

      {wizardStep===1&&<section className="planner-panel">
        <div className="training-step"><span>01</span><div><h2>{bi(lang,"Was möchtest du erreichen?","What do you want to achieve?")}</h2><p className="muted">{bi(lang,"Zuerst nur das Ziel. Details zu Zeit, Daten und KI folgen danach.","Start with the goal. Time, data and AI details come later.")}</p></div></div>
        <div className="planner-profile-row"><button type="button" className="ghost" onClick={loadProfile}>{bi(lang,"Mein Coach-Profil übernehmen","Use my Coach profile")}</button><label className="checkline"><input type="checkbox" checked={usePersonal} onChange={e=>setUsePersonal(e.target.checked)}/>{bi(lang,"Profil, Merksätze & Feedback einbeziehen","Include profile, memories & feedback")}</label></div>
        {profileStatus&&<p role="status" className="muted">{profileStatus}</p>}
        <label>{bi(lang,"Ziel","Goal")}<select value={goalType} onChange={e=>setGoalType(e.target.value)}>{GOALS.map(x=><option key={x[0]} value={x[0]}>{de?x[1]:x[2]}</option>)}</select></label>
        <label>{bi(lang,"Dein konkretes Ziel","Your specific goal")}<textarea value={goalText} onChange={e=>setGoalText(e.target.value)} placeholder={bi(lang,"z. B. 10 km unter 50 Minuten, mehr Muskelmasse und trotzdem zweimal Rad pro Woche …","e.g. run 10K under 50 minutes, gain muscle while cycling twice a week …")}/></label>
      </section>}

      {wizardStep===2&&<section className="planner-panel">
        <div className="training-step"><span>02</span><div><h2>{bi(lang,"Wie soll dein Training aussehen?","What should your training look like?")}</h2><p className="muted">{bi(lang,"Nur die Rahmenbedingungen, die den Plan wirklich verändern.","Only the constraints that materially change the plan.")}</p></div></div>
        <div className="training-form-grid"><label>{bi(lang,"Erfahrung","Experience")}<select value={experience} onChange={e=>setExperience(e.target.value)}><option value="beginner">{bi(lang,"Einsteiger","Beginner")}</option><option value="intermediate">{bi(lang,"Fortgeschritten","Intermediate")}</option><option value="advanced">{bi(lang,"Sehr erfahren","Advanced")}</option></select></label><label>{bi(lang,"Wochen","Weeks")}<input type="number" min={1} max={24} value={weeks} onChange={e=>setWeeks(Math.max(1,Math.min(24,Number(e.target.value)||1)))}/></label><label>{bi(lang,"Trainingstage / Woche","Training days / week")}<input type="number" min={1} max={7} value={days} onChange={e=>setDays(Math.max(1,Math.min(7,Number(e.target.value)||1)))}/></label><label>{bi(lang,"Typische Session","Typical session")}<div className="input-suffix"><input type="number" min={10} max={480} value={minutes} onChange={e=>setMinutes(Math.max(10,Math.min(480,Number(e.target.value)||10)))}/><span>min</span></div></label><label>{bi(lang,"Planstart (Montag)","Plan start (Monday)")}<input type="date" value={planStart} onChange={e=>setPlanStart(e.target.value)}/>{!isMonday(planStart)&&<small className="status-warn">{bi(lang,"Bitte einen Montag wählen.","Please select a Monday.")}</small>}</label></div>
        <div className="grid2"><label>{bi(lang,"Equipment / Möglichkeiten","Equipment / facilities")}<textarea value={equipment} onChange={e=>setEquipment(e.target.value)} placeholder={bi(lang,"Fitnessstudio, Hantelbank, Rennrad, Laufband …","Gym, bench, road bike, treadmill …")}/></label><label>{bi(lang,"Einschränkungen / feste Tage","Constraints / fixed days")}<textarea value={constraints} onChange={e=>setConstraints(e.target.value)} placeholder={bi(lang,"Mittwoch frei, werktags max. 90 Minuten …","Wednesday unavailable, max 90 minutes on weekdays …")}/></label></div>
      </section>}

      {wizardStep===3&&<section className="planner-panel">
        <div className="training-step"><span>03</span><div><h2>{bi(lang,"Welche Daten soll PenguCoach berücksichtigen?","Which data should PenguCoach use?")}</h2><p className="muted">{bi(lang,"Die sinnvollen Standards sind bereits aktiv. Passe nur an, wenn du bewusst etwas ausschließen möchtest.","Useful defaults are already enabled. Customize only when you intentionally want to exclude something.")}</p></div></div>
        <div className="planner-context-summary"><div><span>{bi(lang,"Zeitraum","Period")}</span><strong>{contextDays} {bi(lang,"Tage","days")}</strong></div><div><span>{bi(lang,"Datenbereiche","Data categories")}</span><strong>{selectedContextLabels.length} / 7</strong></div><div><span>{bi(lang,"Wetter","Weather")}</span><strong>{includeWeather&&weather?.enabled?"✓":"—"}</strong></div><div><span>{bi(lang,"Garmin-Zonen","Garmin zones")}</span><strong>{contextData.zones?"✓":"—"}</strong></div></div>
        <div className="training-weather-row"><label className="checkline"><input type="checkbox" checked={includeWeather} disabled={!weather?.enabled||busy} onChange={e=>setIncludeWeather(e.target.checked)}/>{bi(lang,"Wetter berücksichtigen","Use weather")}</label><div className="training-weather-summary"><strong>{weather?.enabled?(weather.location_name||bi(lang,"Wetter aktiv","Weather active")):bi(lang,"Wetter noch nicht eingerichtet","Weather not configured")}</strong><small>{weather?.enabled?bi(lang,"Bis zu 16 Tage Forecast werden als weicher Faktor für Outdoor-Einheiten genutzt. Spätere Wochen bleiben wetterneutral.","Up to 16 forecast days are used as a soft factor for outdoor sessions. Later weeks remain weather-neutral."):<>{bi(lang,"Unter Wetter kannst du kostenlos Open-Meteo konfigurieren.","Configure free Open-Meteo weather under Weather.")} <a className="text-link" href="/settings/weather">{bi(lang,"Einrichten","Set up")} →</a></>}</small></div></div>
        <details className="planner-advanced-details"><summary><span><strong>{bi(lang,"Datenquellen anpassen","Customize data sources")}</strong><small>{bi(lang,"Zeitraum und einzelne Kategorien ändern","Change period and individual categories")}</small></span><b>⌄</b></summary><div className="planner-advanced-body"><div><strong>{bi(lang,"Zeitraum","Period")}</strong><div className="context-preset-row">{CONTEXT_DAYS.map(v=><button type="button" className={contextDays===v?"active":""} key={v} onClick={()=>setContextDays(v)}>{v} {bi(lang,"Tage","days")}</button>)}</div></div><ContextPicker value={contextData} onChange={setContextData} days={contextDays} disabled={busy}/>{contextData.zones&&<TrainingZoneStatus/>}</div></details>
      </section>}

      {wizardStep===4&&<section className="planner-panel">
        <div className="training-step"><span>04</span><div><h2>{bi(lang,"Prüfen & erstellen","Review & create")}</h2><p className="muted">{bi(lang,"Einmal kompakt prüfen. Technische KI-Einstellungen bleiben optional.","Review the essentials once. Technical AI settings remain optional.")}</p></div></div>
        <div className="planner-review-grid"><div><span>{bi(lang,"Ziel","Goal")}</span><strong>{de?(GOALS.find(x=>x[0]===goalType)?.[1]??goalType):(GOALS.find(x=>x[0]===goalType)?.[2]??goalType)}</strong><small>{goalText||bi(lang,"Kein Zusatztext","No additional goal text")}</small></div><div><span>{bi(lang,"Umfang","Scope")}</span><strong>{weeks} {bi(lang,"Wochen","weeks")} · {days}× / {bi(lang,"Woche","week")}</strong><small>{minutes} min · {bi(lang,"Start","start")} {formatDate(planStart,de)}</small></div><div><span>{bi(lang,"Kontext","Context")}</span><strong>{contextDays} {bi(lang,"Tage","days")} · {selectedContextLabels.length}/7</strong><small>{includeWeather&&weather?.enabled?`✓ ${weather.location_name||bi(lang,"Wetter","Weather")}`:bi(lang,"ohne Wetter","without weather")}</small></div><div><span>{bi(lang,"KI","AI")}</span><strong>{selected?.display_name??model??"—"}</strong><small>{quality} · ctx {ctx.toLocaleString()} · out {tokens.toLocaleString()}</small></div></div>
        {(equipment||constraints)&&<div className="planner-notes-review">{equipment&&<div><strong>{bi(lang,"Equipment","Equipment")}</strong><p>{equipment}</p></div>}{constraints&&<div><strong>{bi(lang,"Einschränkungen","Constraints")}</strong><p>{constraints}</p></div>}</div>}
        <details className="planner-advanced-details ai"><summary><span><strong>{bi(lang,"Erweiterte KI-Einstellungen","Advanced AI settings")}</strong><small>{bi(lang,"Modell, Kontext, Antwortbudget, Qualität und Prompt","Model, context, response budget, quality and prompt")}</small></span><b>⌄</b></summary><div className="planner-advanced-body"><div className="ai-analysis-settings"><label>{bi(lang,"Modell","Model")}<select value={model} onChange={e=>setModel(e.target.value)}>{models.map((x:AnyObj)=><option key={x.id} value={x.id}>{x.display_name} · {x.provider} · {x.local?"LOCAL":"CLOUD"}</option>)}</select></label><label>{bi(lang,"Kontextfenster","Context window")}<div className="ai-number-control"><input type="number" min={2048} max={modelCtxMax} step={1024} value={ctx} onChange={e=>setCtx(Math.max(2048,Math.min(modelCtxMax,Number(e.target.value))))}/><span>tokens</span></div></label><label>{bi(lang,"Max. Antwort","Max response")}<div className="ai-number-control"><input type="number" min={128} max={modelOutMax} step={1} value={tokens} onChange={e=>setTokens(Math.max(128,Math.min(modelOutMax,Number(e.target.value))))}/><span>tokens</span></div></label><div className="card subtle ai-budget"><span>{bi(lang,"Trainingskontext","Training context")}</span><strong>{contextDays} {bi(lang,"Tage","days")}</strong><small>{[...selectedContextLabels,...(includeWeather&&weather?.enabled?[`Weather · ${weather.location_name}`]:[])].join(" · ")||bi(lang,"nur Zielangaben","goal details only")}</small><small>ctx {ctx.toLocaleString()} · out {tokens.toLocaleString()}</small></div></div><AiQualityControl lang={lang} profile={quality} onChange={(v,t)=>void changeQuality(v,t)} options={task.quality_profiles??[]} model={selected} contextWindow={ctx} maxOutput={tokens} calls={estimatedCalls}/><p className="muted ai-budget-note">{bi(lang,"Größere Pläne werden automatisch in Wochenblöcke geteilt, validiert und anschließend zusammengeführt. Max. Antwort gilt pro KI-Aufruf/Planabschnitt.","Larger plans are automatically generated in weekly chunks, validated and merged. The response budget applies per plan segment.")}</p><details className="ai-prompt-details"><summary>{bi(lang,"Planungs-Prompt anzeigen / anpassen","Show / edit planning prompt")}</summary><textarea className="prompt-editor modern" value={prompt} onChange={e=>setPrompt(e.target.value)}/></details></div></details>
      </section>}

      <div className="planner-footer"><button type="button" className="ghost" disabled={wizardStep===1||busy} onClick={()=>setWizardStep(Math.max(1,wizardStep-1) as WizardStep)}>← {bi(lang,"Zurück","Back")}</button><div className="planner-status">{status&&<span className={`ai-job-status ${busy?"running":""}`}>{busy&&<i/>}<span>{status}</span>{busy&&progressTokens(jobProgress)&&<b className="ai-token-live">{progressTokens(jobProgress)}</b>}</span>}{error&&<div className="status-bad">{error}</div>}</div>{wizardStep<4?<button type="button" onClick={()=>setWizardStep(Math.min(4,wizardStep+1) as WizardStep)}>{bi(lang,"Weiter","Continue")} →</button>:<div className="row">{busy&&<button type="button" className="ghost danger" onClick={cancelGeneration}>{bi(lang,"Abbrechen","Cancel")}</button>}<button type="submit" disabled={busy||jobLookup||!model||!isMonday(planStart)}>{busy?bi(lang,"Plan läuft…","Plan running…"):bi(lang,"Trainingsplan erstellen","Create training plan")}</button></div>}</div>
    </form>}

    {history.length>0&&<section className="card training-plan-library" id="training-plan-library"><div className="between training-plan-library-head"><div><span className="eyebrow">TRAINING PLANS</span><h2>{bi(lang,"Deine Trainingspläne","Your training plans")}</h2><p className="muted">{bi(lang,"Beim Öffnen dieser Seite bleiben alle Pläne bewusst eingeklappt.","All plans intentionally stay collapsed when this page opens.")}</p></div><span className="badge">{history.length}</span></div><div className="training-plan-list">{history.map((x:AnyObj,i:number)=><article className={`training-plan-card ${runId(result)===runId(x)&&planOpen?"active":""}`} key={runId(x)}><div className="training-plan-card-main"><div className="training-plan-card-title"><span className="training-plan-index">{i===0?bi(lang,"Aktuell","Current"):String(i+1).padStart(2,"0")}</span><div><strong>{planTitle(x,lang)}</strong><small>{x.created_at?new Date(x.created_at).toLocaleString(de?"de-DE":"en-GB"):""}</small></div></div><div className="training-plan-card-meta"><span>{planWeeks(x)||"—"} {bi(lang,"Wochen","weeks")}</span><span>{planSessions(x)} {bi(lang,"Einheiten","sessions")}</span><span>{formatDate(planStartValue(x),de)}</span><span>{x.model??x.model_name??"AI"}</span></div></div><div className="training-plan-card-actions"><button type="button" className="ghost" onClick={()=>openPlan(x)}>{bi(lang,"Plan öffnen","Open plan")}</button><button type="button" className="icon-danger" title={bi(lang,"Plan löschen","Delete plan")} onClick={()=>askDelete(x)}>×</button></div></article>)}</div></section>}

    {planOpen&&result&&<section id="training-plan-detail" className="card ai-result-modern training-plan-detail"><div className="ai-result-head"><div><span className="eyebrow">AI TRAINING PLAN</span><h2>{planTitle(result,lang)}</h2><p className="muted">{planWeeks(result)||"—"} {bi(lang,"Wochen","weeks")} · {planSessions(result)} {bi(lang,"Einheiten","sessions")} · {formatDate(planStartValue(result),de)}</p></div><div className="training-plan-detail-actions"><button type="button" className="ghost compact" onClick={()=>setPlanOpen(false)}>{bi(lang,"Plan einklappen","Collapse plan")}</button></div></div>
      {outputAdjusted&&<div className="ai-truncated-warning">ℹ {bi(lang,`Das effektive Antwortbudget wurde wegen des Kontextfensters von ${requestedOut??"?"} auf ${result?.max_output_tokens??"?"} Token reduziert.`,`The effective response budget was reduced by the context window from ${requestedOut??"?"} to ${result?.max_output_tokens??"?"} tokens.`)}</div>}
      {truncated&&<div className="ai-truncated-warning">⚠ {bi(lang,"Das Modell hat trotz budgetierter Kompaktausgabe das harte Antwortlimit erreicht. Erhöhe Max. Antwort bzw. das Kontextfenster oder reduziere Wochen/Trainingstage.","The model reached the hard response limit despite compact budget-aware output. Increase max response/context window or reduce weeks/training days.")}</div>}
      <details className="training-plan-section"><summary><span><strong>{bi(lang,"Planbeschreibung","Plan description")}</strong><small>{bi(lang,"Ziel, Begründung und Wochenstruktur","Goal, rationale and weekly structure")}</small></span><b>⌄</b></summary><div className="ai-content modern"><AiReport content={result.content}/></div></details>
      <details className="training-calendar-details"><summary><span><strong>{bi(lang,"Trainingskalender","Training calendar")}</strong><small>{bi(lang,"Wochen und Einheiten einzeln öffnen, verschieben oder zu Garmin übertragen","Open weeks and sessions individually, move them or export to Garmin")}</small></span><b>⌄</b></summary><TrainingPlanCalendar key={result.id??result.run_id} result={result} lang={lang}/></details>
      <details className="training-plan-section technical"><summary><span><strong>{bi(lang,"Technische Details","Technical details")}</strong><small>{bi(lang,"Modell, Tokens, Kosten und einzelne KI-Aufrufe","Model, tokens, cost and individual AI calls")}</small></span><b>⌄</b></summary><div className="training-plan-tech"><div className="ai-run-meta-modern"><strong>{result.model??result.model_name}</strong><div><span>{result.provider??result.provider_name}</span><span>{meta.training_context?.days??result.lookback_days??"—"}d</span>{meta.training_context?.weather&&<span>☁ {meta.training_context?.weather_location??bi(lang,"Wetter","Weather")}</span>}<span>ctx {result.context_window_tokens??meta.context_window_tokens??"—"}</span><span>{result.max_output_tokens??"—"} out</span></div></div><div className="ai-result-stats"><span>{usage.input_tokens??"?"} in</span><span>{usage.output_tokens??"?"} out</span><span>{meta.quality_profile??result.quality_profile??"standard"}</span>{(meta.cost_eur??result.cost_eur)!=null&&<span><strong>{euro(Number(meta.cost_eur??result.cost_eur))}</strong></span>}<span>{meta.stop_reason??result.stop_reason??"stop"}</span></div>{Array.isArray(meta.generation_calls)&&meta.generation_calls.length>0&&<div className="ai-usage-details open"><div>{meta.generation_calls.map((c:AnyObj,i:number)=><div key={i}><span>{bi(lang,"Teil","Part")} {c.chunk_index}/{c.chunk_count} · {bi(lang,"Versuch","attempt")} {c.attempt}</span><span>{Number(c.usage?.input_tokens??0).toLocaleString()} in · {Number(c.usage?.output_tokens??0).toLocaleString()} out{c.elapsed_seconds!=null?` · ${Number(c.elapsed_seconds).toFixed(1)}s`:""}{c.tokens_per_second!=null?` · ${Number(c.tokens_per_second).toFixed(1)} out/s`:""}{c.cost_eur!=null?` · ${euro(Number(c.cost_eur))}`:""}</span></div>)}</div></div>}</div></details>
    </section>}

    {deleteCandidate&&<div className="modal-backdrop" role="dialog" aria-modal="true"><div className="card delete-plan-dialog"><span className="eyebrow">DELETE TRAINING PLAN</span><h2>{bi(lang,"Trainingsplan löschen?","Delete training plan?")}</h2><p>{bi(lang,"Der gespeicherte PenguCoach-Plan und seine lokale Historie werden entfernt.","The stored PenguCoach plan and its local history will be removed.")}</p>{Number(deleteInfo?.garmin_exported??0)>0?<div className="status-warn">{bi(lang,`${deleteInfo?.garmin_exported??0} Einheit(en) dieses Plans wurden zu Garmin exportiert. Soll PenguCoach diese auch aus dem Garmin-Kalender und den Garmin-Workouts entfernen?`,`${deleteInfo?.garmin_exported??0} session(s) from this plan were exported to Garmin. Should PenguCoach also remove them from the Garmin calendar and Garmin workouts?`)}</div>:deleteInfo===null?<p className="muted">{bi(lang,"Prüfe Garmin-Exportstatus…","Checking Garmin export status…")}</p>:<p className="muted">{bi(lang,"Für diesen Plan sind keine von PenguCoach exportierten Garmin-Einträge gespeichert.","No PenguCoach-exported Garmin entries are recorded for this plan.")}</p>}{deleteStatus&&<div className="muted">{deleteStatus}</div>}<div className="form-actions">{Number(deleteInfo?.garmin_exported??0)>0&&<button disabled={deleteBusy} onClick={()=>deletePlan("garmin")}>{bi(lang,"Auch aus Garmin löschen","Delete from Garmin too")}</button>}<button className="ghost danger" disabled={deleteBusy||deleteInfo===null} onClick={()=>deletePlan("local")}>{bi(lang,"Nur in PenguCoach löschen","Delete only in PenguCoach")}</button><button className="ghost" disabled={deleteBusy} onClick={()=>{setDeleteCandidate(null);setDeleteInfo(null);setDeleteStatus("")}}>{bi(lang,"Abbrechen","Cancel")}</button></div></div></div>}
  </AppShell>
}
