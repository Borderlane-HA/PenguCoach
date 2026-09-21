"use client";

import {FormEvent,useEffect,useState} from "react";
import AppShell from "../../components/AppShell";
import {api} from "../../lib/api";
import {bi,useI18n} from "../../lib/i18n";

type M={role:"user"|"assistant";content:string;meta?:string};
type AnyObj=Record<string,any>;

export default function Coach(){
  const{lang}=useI18n();const de=lang!=="en";
  const[text,setText]=useState(""),[msgs,setMsgs]=useState<M[]>([]),[cid,setCid]=useState<string|undefined>(),[busy,setBusy]=useState(false);
  const[caps,setCaps]=useState<AnyObj|null>(null),[model,setModel]=useState(""),[tokens,setTokens]=useState(1200);
  useEffect(()=>{void api<AnyObj>("/coach/capabilities").then(c=>{setCaps(c);const t=c.tasks?.coach_chat??{};setModel(t.default_model_id??"");setTokens(t.max_output_tokens??1200)}).catch(()=>{})},[]);
  const task=caps?.tasks?.coach_chat??{};const models=caps?.eligible_models??[];
  async function submit(e:FormEvent){e.preventDefault();if(!text.trim()||busy)return;const q=text.trim();setText("");setMsgs(v=>[...v,{role:"user",content:q}]);setBusy(true);try{const r=await api<any>("/coach/chat",{method:"POST",body:JSON.stringify({message:q,conversation_id:cid,model_id:model||null,max_tokens:tokens})});setCid(r.conversation_id);setMsgs(v=>[...v,{role:"assistant",content:r.content,meta:`${r.local?"LOCAL":"CLOUD"} · ${r.model} · ${r.data_used.activities} activities · ${r.usage?.total_tokens??"?"} tokens`}])}catch(e){setMsgs(v=>[...v,{role:"assistant",content:e instanceof Error?e.message:"Error"}])}finally{setBusy(false)}}
  return <AppShell>
    <div className="between"><div><h1>PenguCoach AI Coach</h1><p className="muted">{bi(lang,"Der Coach nutzt lokal gespeicherte Garmin-/FIT-Fakten. Das Modell kann pro Anfrage gewählt werden.","The coach uses locally stored Garmin/FIT facts. The model can be selected per request.")}</p></div><div className="ai-model-badge"><span>{bi(lang,"Standardmodell","Default model")}</span><strong>{task.default_model??"—"}</strong><small>{task.default_provider??""}</small></div></div>
    <section className="card chat">{msgs.length?msgs.map((m,i)=><div key={i} className={`bubble ${m.role}`}><div>{m.content}</div>{m.meta&&<small style={{display:"block",marginTop:8}}>{m.meta}</small>}</div>):<div className="muted">{bi(lang,"Beispiele: „Analysiere meine letzten vier Wochen“, „Warum war mein letzter Lauf schwerer?“, „Wie entwickelt sich meine HRV?“","Examples: “Analyse my last four weeks”, “Why was my last run harder?”, “How is my HRV developing?”")}</div>}{busy&&<div className="bubble assistant">…</div>}</section>
    <form className="card stack" onSubmit={submit}><div className="ai-controls-grid"><label>{bi(lang,"Modell","Model")}<select value={model} onChange={e=>setModel(e.target.value)}>{models.map((x:AnyObj)=><option value={x.id} key={x.id}>{x.display_name} · {x.provider} · {x.local?"LOCAL":"CLOUD"}</option>)}</select></label><label>{bi(lang,"Max. Antwort-Tokens","Max response tokens")}<input type="number" min={128} max={task.max_output_tokens??8192} value={tokens} onChange={e=>setTokens(Number(e.target.value))}/><small>{bi(lang,"Serverlimit","Server limit")}: {task.max_output_tokens??"—"}</small></label></div><div className="row"><textarea style={{flex:1}} value={text} onChange={e=>setText(e.target.value)} placeholder={bi(lang,"Frage an PenguCoach…","Ask PenguCoach…")}/><button disabled={busy||!model}>{bi(lang,"Senden","Send")}</button></div></form>
  </AppShell>
}
