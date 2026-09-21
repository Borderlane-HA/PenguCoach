"use client";

import {FormEvent,useEffect,useMemo,useState} from "react";
import AppShell from "../../../components/AppShell";
import {api} from "../../../lib/api";
import {bi,useI18n} from "../../../lib/i18n";

type Provider={id:string;name:string;provider_type:string;base_url?:string;enabled:boolean;is_local:boolean;has_secret?:boolean};
type Model={id:string;provider_id:string;provider_name?:string;provider_type?:string;local?:boolean;model_identifier:string;display_name:string;enabled:boolean;context_window?:number;temperature:number};
type Route={task_type:string;primary_model_id:string|null;fallback_model_id:string|null;enabled:boolean;max_output_tokens:number;context_window_tokens:number;max_context_chars:number;default_prompt:string;default_prompt_de:string;default_prompt_en:string;factory_prompt_de:string;factory_prompt_en:string};

const TASKS=["coach_chat","activity_analysis","training_plan"];
const taskName=(task:string,de:boolean)=>({coach_chat:de?"Coach Chat":"Coach chat",activity_analysis:de?"Aktivitätsanalyse":"Activity analysis",training_plan:de?"Trainingsplanung":"Training planning"}[task]??task);
const taskSub=(task:string,de:boolean)=>({coach_chat:de?"Freier Chat mit intelligentem Trainingskontext":"Free chat with smart training context",activity_analysis:de?"Tiefe Einheitenanalyse mit 3-/7-Tage-Rückblick":"Deep session analysis with 3/7-day lookback",training_plan:de?"Periodisierte Pläne aus Ziel und 7-/28-Tage-Daten":"Periodized plans from goals and 7/28-day data"}[task]??"");
const taskIcon=(task:string)=>task==="coach_chat"?"✦":task==="activity_analysis"?"⌁":"◫";

export default function AIAdmin(){
  const{lang}=useI18n();const de=lang!=="en";
  const[p,setP]=useState<Provider[]>([]),[m,setM]=useState<Model[]>([]),[routes,setRoutes]=useState<Route[]>([]),[msg,setMsg]=useState("");
  const[type,setType]=useState("ollama"),[name,setName]=useState("Local Ollama"),[url,setUrl]=useState("http://127.0.0.1:11434"),[key,setKey]=useState("");
  const[found,setFound]=useState<string[]>([]),[selectedTask,setSelectedTask]=useState("activity_analysis"),[promptLang,setPromptLang]=useState<"de"|"en">(de?"de":"en"),[infraOpen,setInfraOpen]=useState(false);
  const refresh=()=>{void Promise.all([api<Provider[]>("/admin/ai/providers"),api<Model[]>("/admin/ai/models"),api<Route[]>("/admin/ai/routes")]).then(([pp,mm,rr])=>{setP(pp);setM(mm);setRoutes(rr)})};
  useEffect(refresh,[]);useEffect(()=>setPromptLang(de?"de":"en"),[de]);
  async function create(e:FormEvent){e.preventDefault();await api("/admin/ai/providers",{method:"POST",body:JSON.stringify({name,provider_type:type,base_url:url||null,api_key:key||null,is_local:type==="ollama"})});setKey("");setMsg(de?"Provider gespeichert":"Provider saved");refresh()}
  async function test(){try{const r=await api<any>("/admin/ai/providers/test",{method:"POST",body:JSON.stringify({name,provider_type:type,base_url:url||null,api_key:key||null,is_local:type==="ollama"})});setFound(r.models??[]);setMsg(`${r.ok?"✓":"!"} ${(r.models??[]).length} ${de?"Modelle erkannt":"models detected"}`)}catch(e){setMsg(e instanceof Error?e.message:String(e))}}
  async function addModel(providerId:string,identifier?:string){const id=identifier??prompt("Model identifier / Modell-ID")??"";if(!id)return;await api("/admin/ai/models",{method:"POST",body:JSON.stringify({provider_id:providerId,model_identifier:id,display_name:id,temperature:.2,enabled:true})});refresh()}
  function patchRoute(task:string,patch:Partial<Route>){setRoutes(v=>v.map(r=>r.task_type===task?{...r,...patch}:r))}
  function patchBudget(r:Route,patch:Partial<Route>){const next={...r,...patch};const input=Math.max(512,next.context_window_tokens-next.max_output_tokens-768);next.max_context_chars=Math.max(4000,Math.floor(input*.72)*4);patchRoute(r.task_type,next)}
  async function saveRoute(r:Route){await api(`/admin/ai/routes/${r.task_type}`,{method:"PUT",body:JSON.stringify(r)});setMsg(`${taskName(r.task_type,de)} · ${de?"gespeichert":"saved"}`);refresh()}
  const testedProvider=p.find(x=>x.provider_type===type&&x.base_url===url)||p.find(x=>x.provider_type===type);
  const route=routes.find(r=>r.task_type===selectedTask);
  const activeModels=m.filter(x=>x.enabled);
  const selectedModel=activeModels.find(x=>x.id===route?.primary_model_id);
  const budget=useMemo(()=>{if(!route)return{input:0,pctOut:0,pctInput:0};const input=Math.max(0,route.context_window_tokens-route.max_output_tokens-768);return{input,pctOut:Math.min(100,route.max_output_tokens/route.context_window_tokens*100),pctInput:Math.min(100,input/route.context_window_tokens*100)}},[route]);
  return <AppShell>
    <div className="ai-studio-head"><div><span className="eyebrow">PENGUCOACH AI STUDIO</span><h1>{bi(lang,"AI & Modelle","AI & models")}</h1><p className="muted">{bi(lang,"Modelle, Kontextfenster, Antwortbudgets und Prompts an einem Ort – klar getrennt nach Aufgabe.","Models, context windows, response budgets and prompts in one place — separated by task.")}</p></div><div className="ai-studio-kpis"><div><strong>{activeModels.length}</strong><span>{bi(lang,"aktive Modelle","active models")}</span></div><div><strong>{p.filter(x=>x.enabled).length}</strong><span>Provider</span></div><div><strong>{routes.filter(x=>x.primary_model_id).length}/{routes.length}</strong><span>{bi(lang,"Routen gesetzt","routes set")}</span></div></div></div>

    {msg&&<div className="ai-toast">{msg}</div>}

    <section className="ai-task-switcher">{TASKS.map(t=><button type="button" key={t} className={selectedTask===t?"active":""} onClick={()=>setSelectedTask(t)}><span>{taskIcon(t)}</span><div><strong>{taskName(t,de)}</strong><small>{taskSub(t,de)}</small></div></button>)}</section>

    {route&&<section className="card ai-config-shell">
      <div className="ai-config-top"><div><span className="badge">{route.task_type}</span><h2>{taskName(route.task_type,de)}</h2><p className="muted">{taskSub(route.task_type,de)}</p></div><button onClick={()=>saveRoute(route)}>{bi(lang,"Änderungen speichern","Save changes")}</button></div>

      <div className="ai-config-grid">
        <div className="ai-config-section"><div className="ai-section-title"><span>01</span><div><strong>{bi(lang,"Modell-Routing","Model routing")}</strong><small>{bi(lang,"Welches Modell diese Aufgabe standardmäßig übernimmt.","Which model handles this task by default.")}</small></div></div>
          <label>{bi(lang,"Standardmodell","Default model")}<select value={route.primary_model_id??""} onChange={e=>patchRoute(route.task_type,{primary_model_id:e.target.value||null})}><option value="">{bi(lang,"Automatisch erstes aktives Modell","Automatically first active model")}</option>{activeModels.map(x=><option key={x.id} value={x.id}>{x.display_name} · {x.provider_name} · {x.local?"LOCAL":"CLOUD"}</option>)}</select></label>
          <label>Fallback<select value={route.fallback_model_id??""} onChange={e=>patchRoute(route.task_type,{fallback_model_id:e.target.value||null})}><option value="">—</option>{activeModels.map(x=><option key={x.id} value={x.id}>{x.display_name} · {x.provider_name}</option>)}</select></label>
          <div className="ai-selected-model"><span className={`ai-local-dot ${selectedModel?.local?"local":"cloud"}`}/><div><strong>{selectedModel?.display_name??bi(lang,"Automatische Auswahl","Automatic selection")}</strong><small>{selectedModel?.provider_name??""}{selectedModel?.context_window?` · ${selectedModel.context_window.toLocaleString()} ctx`:""}</small></div></div>
        </div>

        <div className="ai-config-section"><div className="ai-section-title"><span>02</span><div><strong>{bi(lang,"Kontext & Antwort","Context & response")}</strong><small>{bi(lang,"Wie viel das Modell sehen und maximal ausgeben darf.","How much the model can see and how much it may output.")}</small></div></div>
          <label>{bi(lang,"Kontextfenster","Context window")}<div className="ai-number-control"><input type="number" min={2048} max={262144} step={1024} value={route.context_window_tokens} onChange={e=>patchBudget(route,{context_window_tokens:Number(e.target.value)})}/><span>tokens</span></div></label>
          <div className="ai-preset-row">{[4096,8192,16384,32768].map(v=><button type="button" className={route.context_window_tokens===v?"active":""} key={v} onClick={()=>patchBudget(route,{context_window_tokens:v})}>{v>=1024?`${v/1024}K`:v}</button>)}</div>
          <label>{bi(lang,"Maximale Antwort","Maximum response")}<div className="ai-number-control"><input type="number" min={128} max={8192} step={100} value={route.max_output_tokens} onChange={e=>patchBudget(route,{max_output_tokens:Number(e.target.value)})}/><span>tokens</span></div></label>
          <div className="ai-budget-viz"><div className="ai-budget-bar"><i className="input" style={{width:`${budget.pctInput}%`}}/><i className="output" style={{width:`${budget.pctOut}%`}}/></div><div className="ai-budget-legend"><span><i className="input"/>≈ {budget.input.toLocaleString()} {bi(lang,"für Input","for input")}</span><span><i className="output"/>{route.max_output_tokens.toLocaleString()} {bi(lang,"für Antwort","for response")}</span><span>{bi(lang,"Reserve","reserve")}: 768</span></div></div>
          <small>{selectedModel?.local?bi(lang,"Bei Ollama wird das Kontextfenster direkt als num_ctx übergeben.","For Ollama the context window is sent directly as num_ctx."):bi(lang,"Bei Cloud-Modellen dient das Fenster als PenguCoach-Budget; die Modellgrenze bleibt providerseitig.","For cloud models this is PenguCoach's budget; the provider's model limit still applies.")}</small>
        </div>
      </div>

      <div className="ai-prompt-section"><div className="ai-section-title"><span>03</span><div><strong>{bi(lang,"System-Prompt der Aufgabe","Task prompt")}</strong><small>{bi(lang,"Deutsch und Englisch werden getrennt gepflegt und automatisch nach UI-Sprache gewählt.","German and English are stored separately and selected automatically from the UI language.")}</small></div></div>
        <div className="ai-prompt-tabs"><button type="button" className={promptLang==="de"?"active":""} onClick={()=>setPromptLang("de")}>DE</button><button type="button" className={promptLang==="en"?"active":""} onClick={()=>setPromptLang("en")}>EN</button><span/><button type="button" className="ghost" onClick={()=>patchRoute(route.task_type,promptLang==="de"?{default_prompt_de:route.factory_prompt_de}:{default_prompt_en:route.factory_prompt_en})}>{bi(lang,"Standard wiederherstellen","Restore default")}</button></div>
        <textarea className="prompt-editor modern" value={promptLang==="de"?route.default_prompt_de:route.default_prompt_en} onChange={e=>patchRoute(route.task_type,promptLang==="de"?{default_prompt_de:e.target.value}:{default_prompt_en:e.target.value})}/>
      </div>
    </section>}

    <section className="card ai-infra-card"><button type="button" className="ai-infra-toggle" onClick={()=>setInfraOpen(v=>!v)}><div><strong>{bi(lang,"Provider & Modell-Infrastruktur","Provider & model infrastructure")}</strong><small>{bi(lang,"Ollama, OpenAI, Anthropic und OpenAI-kompatible Endpunkte verwalten.","Manage Ollama, OpenAI, Anthropic and OpenAI-compatible endpoints.")}</small></div><span>{infraOpen?"−":"+"}</span></button>
      {infraOpen&&<div className="ai-infra-body"><div className="grid2"><form className="stack ai-provider-form" onSubmit={create}><h3>{bi(lang,"Provider hinzufügen","Add provider")}</h3><div className="grid2"><label>Type<select value={type} onChange={e=>{setType(e.target.value);if(e.target.value==="ollama")setUrl("http://127.0.0.1:11434");else if(e.target.value==="openai")setUrl("https://api.openai.com/v1");else if(e.target.value==="anthropic")setUrl("https://api.anthropic.com/v1")}}><option value="ollama">Ollama</option><option value="openai">OpenAI</option><option value="anthropic">Anthropic</option><option value="openai_compatible">OpenAI compatible</option></select></label><label>Name<input value={name} onChange={e=>setName(e.target.value)}/></label></div><label>Base URL<input value={url} onChange={e=>setUrl(e.target.value)}/></label><label>API Key<input type="password" value={key} onChange={e=>setKey(e.target.value)} placeholder={type==="ollama"?"optional":"required"}/></label><div className="form-actions"><button type="button" className="ghost" onClick={test}>{bi(lang,"Verbindung testen","Test connection")}</button><button>{bi(lang,"Speichern","Save")}</button></div>{found.length>0&&<div className="model-discovery"><strong>{bi(lang,"Erkannte Modelle","Detected models")}</strong><div className="chip-list">{found.slice(0,30).map(x=><button type="button" className="ghost compact" key={x} disabled={!testedProvider} onClick={()=>testedProvider&&addModel(testedProvider.id,x)}>+ {x}</button>)}</div></div>}</form>
      <div><h3>Providers</h3><div className="ai-provider-list">{p.map(x=><div className="ai-provider-row" key={x.id}><span className={`ai-local-dot ${x.is_local?"local":"cloud"}`}/><div><strong>{x.name}</strong><small>{x.provider_type} · {x.base_url??"—"}</small></div><button className="ghost compact" onClick={()=>addModel(x.id)}>+ Model</button></div>)}</div></div></div>
      <div className="table-scroll"><table><thead><tr><th>Provider</th><th>Model</th><th>Context</th><th>Status</th></tr></thead><tbody>{m.map(x=><tr key={x.id}><td>{x.provider_name??x.provider_id}<small style={{display:"block"}}>{x.local?"LOCAL":"CLOUD"}</small></td><td><strong>{x.display_name}</strong><small style={{display:"block"}}>{x.model_identifier}</small></td><td>{x.context_window?.toLocaleString()??bi(lang,"Task-Setting","Task setting")}</td><td>{x.enabled?"●":"○"}</td></tr>)}</tbody></table></div></div>}
    </section>
  </AppShell>
}
