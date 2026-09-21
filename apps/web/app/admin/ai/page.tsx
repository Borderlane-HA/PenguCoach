"use client";

import {FormEvent,useEffect,useState} from "react";
import AppShell from "../../../components/AppShell";
import {api} from "../../../lib/api";
import {bi,useI18n} from "../../../lib/i18n";

type Provider={id:string;name:string;provider_type:string;base_url?:string;enabled:boolean;is_local:boolean};
type Model={id:string;provider_id:string;provider_name?:string;provider_type?:string;local?:boolean;model_identifier:string;display_name:string;enabled:boolean;context_window?:number;temperature:number};
type Route={task_type:string;primary_model_id:string|null;fallback_model_id:string|null;enabled:boolean;max_output_tokens:number;max_context_chars:number;default_prompt:string};

const taskName=(task:string,de:boolean)=>({coach_chat:de?"Coach Chat":"Coach chat",activity_analysis:de?"Aktivitäts-Tiefenanalyse":"Activity deep analysis",training_plan:de?"Trainingsplanung":"Training planning"}[task]??task);

export default function AIAdmin(){
  const{lang}=useI18n();const de=lang!=="en";
  const[p,setP]=useState<Provider[]>([]),[m,setM]=useState<Model[]>([]),[routes,setRoutes]=useState<Route[]>([]),[msg,setMsg]=useState("");
  const[type,setType]=useState("ollama"),[name,setName]=useState("Local Ollama"),[url,setUrl]=useState("http://127.0.0.1:11434"),[key,setKey]=useState("");
  const[found,setFound]=useState<string[]>([]);
  const refresh=()=>{void Promise.all([api<Provider[]>("/admin/ai/providers"),api<Model[]>("/admin/ai/models"),api<Route[]>("/admin/ai/routes")]).then(([pp,mm,rr])=>{setP(pp);setM(mm);setRoutes(rr)})};
  useEffect(refresh,[]);
  async function create(e:FormEvent){e.preventDefault();await api("/admin/ai/providers",{method:"POST",body:JSON.stringify({name,provider_type:type,base_url:url||null,api_key:key||null,is_local:type==="ollama"})});setKey("");refresh()}
  async function test(){try{const r=await api<any>("/admin/ai/providers/test",{method:"POST",body:JSON.stringify({name,provider_type:type,base_url:url||null,api_key:key||null,is_local:type==="ollama"})});setFound(r.models??[]);setMsg(`${r.ok?"OK":"FAIL"} · ${(r.models??[]).length} ${de?"Modelle gefunden":"models found"}`)}catch(e){setMsg(e instanceof Error?e.message:String(e))}}
  async function addModel(providerId:string,identifier?:string){const id=identifier??prompt("Model identifier / Modell-ID")??"";if(!id)return;await api("/admin/ai/models",{method:"POST",body:JSON.stringify({provider_id:providerId,model_identifier:id,display_name:id,temperature:.2,enabled:true})});refresh()}
  function patchRoute(task:string,patch:Partial<Route>){setRoutes(v=>v.map(r=>r.task_type===task?{...r,...patch}:r))}
  async function saveRoute(r:Route){await api(`/admin/ai/routes/${r.task_type}`,{method:"PUT",body:JSON.stringify(r)});setMsg(`${taskName(r.task_type,de)} · ${de?"gespeichert":"saved"}`);refresh()}
  const testedProvider=p.find(x=>x.provider_type===type&&x.base_url===url)||p.find(x=>x.provider_type===type);
  return <AppShell>
    <div><h1>LLM Management</h1><p className="muted">{bi(lang,"Provider, Modelle, Standard-Routing, Prompts und Token-Budgets zentral konfigurieren.","Configure providers, models, default routing, prompts and token budgets centrally.")}</p></div>
    <section className="grid2">
      <form className="card stack" onSubmit={create}><h2>{bi(lang,"Provider hinzufügen","Add provider")}</h2>
        <label>Type<select value={type} onChange={e=>{setType(e.target.value);if(e.target.value==="ollama")setUrl("http://127.0.0.1:11434");else if(e.target.value==="openai")setUrl("https://api.openai.com/v1");else if(e.target.value==="anthropic")setUrl("https://api.anthropic.com/v1")}}><option value="ollama">Ollama</option><option value="openai">OpenAI</option><option value="anthropic">Anthropic</option><option value="openai_compatible">OpenAI compatible</option></select></label>
        <label>Name<input value={name} onChange={e=>setName(e.target.value)}/></label><label>Base URL<input value={url} onChange={e=>setUrl(e.target.value)}/></label><label>API Key<input type="password" value={key} onChange={e=>setKey(e.target.value)} placeholder={type==="ollama"?"optional":"required"}/></label>
        <div className="form-actions"><button type="button" className="ghost" onClick={test}>{bi(lang,"Verbindung testen","Test connection")}</button><button>{bi(lang,"Speichern","Save")}</button></div>{msg&&<small>{msg}</small>}
        {found.length>0&&<div className="model-discovery"><strong>{bi(lang,"Erkannte Modelle","Detected models")}</strong><div className="chip-list">{found.slice(0,20).map(x=><button type="button" className="ghost compact" key={x} disabled={!testedProvider} title={!testedProvider?(de?"Provider zuerst speichern":"Save provider first"):""} onClick={()=>testedProvider&&addModel(testedProvider.id,x)}>+ {x}</button>)}</div></div>}
      </form>
      <div className="card"><h2>Providers</h2>{p.map(x=><div className="between provider-row" key={x.id}><div><strong>{x.name}</strong><small style={{display:"block"}}>{x.provider_type} · {x.is_local?"LOCAL":"CLOUD"}</small></div><button className="ghost compact" onClick={()=>addModel(x.id)}>+ Model</button></div>)}</div>
    </section>

    <section className="card"><div className="between"><div><h2>Models</h2><p className="muted">{bi(lang,"Alle aktivierten Modelle können pro Analyse ausgewählt werden. Das Task-Routing legt den Standard fest.","All enabled models can be selected per analysis. Task routing defines the default.")}</p></div><span className="badge">{m.filter(x=>x.enabled).length} active</span></div>
      <div className="table-scroll"><table><thead><tr><th>Provider</th><th>Model</th><th>Context</th><th>Status</th></tr></thead><tbody>{m.map(x=><tr key={x.id}><td>{x.provider_name??x.provider_id}<small style={{display:"block"}}>{x.local?"LOCAL":"CLOUD"}</small></td><td><strong>{x.display_name}</strong><small style={{display:"block"}}>{x.model_identifier}</small></td><td>{x.context_window?.toLocaleString()??"—"}</td><td>{x.enabled?"●":"○"}</td></tr>)}</tbody></table></div>
    </section>

    <section className="stack"><div><h2>{bi(lang,"AI Routing & Kostenlimits","AI routing & cost limits")}</h2><p className="muted">{bi(lang,"Für Chat, Aktivitätsanalyse und Trainingspläne kann jeweils ein Standardmodell, ein Prompt und ein maximales Antwortbudget festgelegt werden.","Set a default model, prompt and maximum response budget separately for chat, activity analysis and training plans.")}</p></div>
      {routes.map(r=><div className="card ai-route-card stack" key={r.task_type}><div className="between"><div><span className="badge">{r.task_type}</span><h2 style={{marginTop:10}}>{taskName(r.task_type,de)}</h2></div><button onClick={()=>saveRoute(r)}>{bi(lang,"Routing speichern","Save routing")}</button></div>
        <div className="grid2"><label>{bi(lang,"Standardmodell","Default model")}<select value={r.primary_model_id??""} onChange={e=>patchRoute(r.task_type,{primary_model_id:e.target.value||null})}><option value="">{bi(lang,"Automatisch erstes aktives Modell","Automatically first active model")}</option>{m.filter(x=>x.enabled).map(x=><option key={x.id} value={x.id}>{x.display_name} · {x.provider_name} · {x.local?"LOCAL":"CLOUD"}</option>)}</select></label><label>Fallback<select value={r.fallback_model_id??""} onChange={e=>patchRoute(r.task_type,{fallback_model_id:e.target.value||null})}><option value="">—</option>{m.filter(x=>x.enabled).map(x=><option key={x.id} value={x.id}>{x.display_name} · {x.provider_name}</option>)}</select></label></div>
        <div className="grid2"><label>{bi(lang,"Max. Antwort-Tokens","Max response tokens")}<input type="number" min={128} max={8192} value={r.max_output_tokens} onChange={e=>patchRoute(r.task_type,{max_output_tokens:Number(e.target.value)})}/><small>{bi(lang,"Harte Obergrenze pro Anfrage – wichtig für Cloud-Kosten. Benutzer können nur kleiner wählen.","Hard limit per request – important for cloud cost. Users may only choose a lower value.")}</small></label><label>{bi(lang,"Max. Kontextzeichen","Max context characters")}<input type="number" min={4000} max={200000} step={1000} value={r.max_context_chars} onChange={e=>patchRoute(r.task_type,{max_context_chars:Number(e.target.value)})}/><small>≈ {Math.round(r.max_context_chars/4).toLocaleString()} {bi(lang,"Input-Tokens als grobe Schätzung","input tokens as a rough estimate")}</small></label></div>
        <label>{bi(lang,"Vordefinierter Prompt","Default prompt")}<textarea className="prompt-editor" value={r.default_prompt} onChange={e=>patchRoute(r.task_type,{default_prompt:e.target.value})}/></label>
      </div>)}
    </section>
  </AppShell>
}
