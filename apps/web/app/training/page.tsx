"use client";

import {FormEvent,useEffect,useState} from "react";
import AppShell from "../../components/AppShell";
import AiReport from "../../components/AiReport";
import {api} from "../../lib/api";
import {bi,useI18n} from "../../lib/i18n";

type AnyObj=Record<string,any>;

const GOALS=[
  ["muscle_gain","Muskelaufbau","Muscle gain"],
  ["cardio_endurance","Cardio / Ausdauer","Cardio / endurance"],
  ["hybrid","Hybrid · Kraft + Ausdauer","Hybrid · strength + endurance"],
  ["cycling_endurance","Radsport-Ausdauer","Cycling endurance"],
  ["running_5k","Laufen · 5 km","Running · 5K"],
  ["running_10k","Laufen · 10 km","Running · 10K"],
  ["half_marathon","Halbmarathon","Half marathon"],
  ["marathon","Marathon","Marathon"],
  ["strength","Kraft","Strength"],
  ["general_fitness","Allgemeine Fitness","General fitness"],
  ["mobility","Mobilität","Mobility"],
  ["custom","Eigenes Ziel","Custom goal"],
];

export default function Training(){
  const{lang}=useI18n();const de=lang!=="en";
  const[caps,setCaps]=useState<AnyObj|null>(null),[history,setHistory]=useState<AnyObj[]>([]),[result,setResult]=useState<AnyObj|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState("");
  const[goalType,setGoalType]=useState("hybrid"),[goalText,setGoalText]=useState(""),[experience,setExperience]=useState("intermediate"),[weeks,setWeeks]=useState(8),[days,setDays]=useState(4),[minutes,setMinutes]=useState(60),[equipment,setEquipment]=useState(""),[constraints,setConstraints]=useState("");
  const[model,setModel]=useState(""),[tokens,setTokens]=useState(2200),[prompt,setPrompt]=useState("");
  useEffect(()=>{void Promise.all([api<AnyObj>("/coach/capabilities"),api<AnyObj[]>("/coach/training-plans")]).then(([c,h])=>{setCaps(c);setHistory(h);const t=c.tasks?.training_plan??{};setModel(t.default_model_id??"");setTokens(t.max_output_tokens??2200);setPrompt(t.default_prompt??"");if(h.length)setResult(h[0])}).catch(e=>setError(String(e)))},[]);
  const task=caps?.tasks?.training_plan??{};const models=caps?.eligible_models??[];const selected=models.find((x:AnyObj)=>x.id===model);
  async function generate(e:FormEvent){e.preventDefault();if(busy||!model)return;setBusy(true);setError("");try{const r=await api<AnyObj>("/coach/training-plan",{method:"POST",body:JSON.stringify({goal_type:goalType,goal_text:goalText,experience,weeks,days_per_week:days,session_minutes:minutes,equipment,constraints,prompt:prompt||null,model_id:model,max_tokens:tokens})});setResult(r);setHistory(v=>[r,...v].slice(0,10))}catch(e){setError(e instanceof Error?e.message:String(e))}finally{setBusy(false)}}
  return <AppShell>
    <section className="card hero"><span className="badge">AI TRAINING PLANNER</span><h1>{bi(lang,"Trainingsplanung","Training planning")}</h1><p className="muted">{bi(lang,"Erstellt einen periodisierten Plan aus deinem Ziel und deinen Garmin-/FIT-Daten der letzten 7 und 28 Tage. Garmin bleibt read-only.","Creates a periodized plan from your goal and your Garmin/FIT data from the previous 7 and 28 days. Garmin remains read-only.")}</p></section>

    <form className="card stack" onSubmit={generate}>
      <div className="between"><div><h2>{bi(lang,"Neuen Trainingsplan erstellen","Create a new training plan")}</h2><p className="muted">{bi(lang,"Ziel, verfügbare Trainingstage und Rahmenbedingungen festlegen. Die AI berücksichtigt die zuletzt aufgezeichnete Belastung und Erholung, sofern Daten vorhanden sind.","Set your goal, available training days and constraints. The AI considers recently recorded load and recovery when data is available.")}</p></div><div className="ai-model-badge"><span>{bi(lang,"Standardmodell","Default model")}</span><strong>{task.default_model??"—"}</strong><small>{task.default_provider??""}</small></div></div>
      <div className="training-form-grid"><label>{bi(lang,"Ziel","Goal")}<select value={goalType} onChange={e=>setGoalType(e.target.value)}>{GOALS.map(x=><option key={x[0]} value={x[0]}>{de?x[1]:x[2]}</option>)}</select></label><label>{bi(lang,"Erfahrung","Experience")}<select value={experience} onChange={e=>setExperience(e.target.value)}><option value="beginner">{bi(lang,"Einsteiger","Beginner")}</option><option value="intermediate">{bi(lang,"Fortgeschritten","Intermediate")}</option><option value="advanced">{bi(lang,"Erfahren","Advanced")}</option></select></label><label>{bi(lang,"Wochen","Weeks")}<input type="number" min={1} max={24} value={weeks} onChange={e=>setWeeks(Number(e.target.value))}/></label><label>{bi(lang,"Trainingstage / Woche","Training days / week")}<input type="number" min={1} max={7} value={days} onChange={e=>setDays(Number(e.target.value))}/></label><label>{bi(lang,"Typische Session","Typical session")}<div className="input-suffix"><input type="number" min={15} max={240} value={minutes} onChange={e=>setMinutes(Number(e.target.value))}/><span>min</span></div></label><label>{bi(lang,"AI Modell","AI model")}<select value={model} onChange={e=>setModel(e.target.value)}>{models.map((x:AnyObj)=><option key={x.id} value={x.id}>{x.display_name} · {x.provider} · {x.local?"LOCAL":"CLOUD"}</option>)}</select></label></div>
      <label>{bi(lang,"Dein konkretes Ziel","Your specific goal")}<textarea value={goalText} onChange={e=>setGoalText(e.target.value)} placeholder={bi(lang,"z. B. mehr Muskelmasse aufbauen und trotzdem 2× pro Woche Rad fahren; 10 km unter 50 Minuten; 150-km-Radtour vorbereiten …","e.g. gain muscle while cycling twice a week; run 10K under 50 minutes; prepare for a 150 km ride …")}/></label>
      <div className="grid2"><label>{bi(lang,"Equipment / Möglichkeiten","Equipment / facilities")}<textarea value={equipment} onChange={e=>setEquipment(e.target.value)} placeholder={bi(lang,"Fitnessstudio, Hantelbank, Rennrad, Laufband …","Gym, bench, road bike, treadmill …")}/></label><label>{bi(lang,"Einschränkungen / feste Tage","Constraints / fixed days")}<textarea value={constraints} onChange={e=>setConstraints(e.target.value)} placeholder={bi(lang,"z. B. Mittwoch frei, maximal 90 Minuten werktags …","e.g. Wednesday off, max 90 minutes on weekdays …")}/></label></div>
      <div className="grid2"><label>{bi(lang,"Max. Antwort-Tokens","Max response tokens")}<input type="number" min={128} max={task.max_output_tokens??8192} value={tokens} onChange={e=>setTokens(Number(e.target.value))}/><small>{bi(lang,"Kostenlimit. Servermaximum","Cost limit. Server maximum")}: {task.max_output_tokens??"—"}</small></label><div className="card subtle ai-budget"><span>{bi(lang,"Kontext","Context")}</span><strong>7d + 28d Garmin/FIT</strong><small>{bi(lang,"Input-Budget grob","Approx. input budget")}: ≈ {Math.round((task.max_context_chars??0)/4).toLocaleString()} tokens</small></div></div>
      <label>{bi(lang,"Planungs-Prompt","Planning prompt")}<textarea className="prompt-editor" value={prompt} onChange={e=>setPrompt(e.target.value)}/></label>
      <div className="between"><small>{selected?`${selected.display_name} · ${selected.provider} · ${selected.local?"LOCAL":"CLOUD"}`:""}</small><button disabled={busy||!model}>{busy?bi(lang,"Plan wird erstellt…","Creating plan…"):bi(lang,"Trainingsplan erstellen","Create training plan")}</button></div>
      {error&&<div className="status-bad">{error}</div>}
    </form>

    {result&&<section className="card ai-result"><div className="between"><div><span className="badge">AI TRAINING PLAN</span><h2 style={{marginTop:10}}>{bi(lang,"Aktueller Plan","Current plan")}</h2></div><div className="ai-run-meta"><strong>{result.model??result.model_name}</strong><small>{result.provider??result.provider_name} · max {result.max_output_tokens??"—"} tokens</small></div></div><div className="ai-content"><AiReport content={result.content}/></div>{result.usage&&<small>Tokens: {result.usage.input_tokens??"?"} in · {result.usage.output_tokens??"?"} out</small>}</section>}

    {history.length>1&&<section className="card"><h2>{bi(lang,"Frühere Pläne","Previous plans")}</h2><div className="plan-history">{history.slice(0,8).map((x:AnyObj)=><button className="history-row" type="button" key={x.id??x.run_id} onClick={()=>setResult(x)}><span><strong>{x.metadata?.goal?.goal_type??bi(lang,"Trainingsplan","Training plan")}</strong><small>{x.created_at?new Date(x.created_at).toLocaleString(de?"de-DE":"en-GB"):""}</small></span><span>{x.model??x.model_name}</span></button>)}</div></section>}
  </AppShell>
}
