"use client";
import {useEffect,useState} from "react";
import AppShell from "../../../components/AppShell";
import {api} from "../../../lib/api";
import {bi,useI18n} from "../../../lib/i18n";

type Privacy={local_ai_only:boolean;cloud_health_ai_allowed:boolean};
export default function PrivacyPage(){
  const {lang}=useI18n(); const [p,setP]=useState<Privacy|null>(null); const [saved,setSaved]=useState("");
  useEffect(()=>{api<Privacy>("/settings/privacy").then(setP)},[]);
  async function save(){if(!p)return;await api("/settings/privacy",{method:"PUT",body:JSON.stringify(p)});setSaved(bi(lang,"Gespeichert","Saved"));}
  if(!p)return <AppShell><div className="card">Loading…</div></AppShell>;
  return <AppShell><div><h1>{bi(lang,"Datenschutz & KI","Privacy & AI")}</h1><p className="muted">{bi(lang,"Cloud-KI erhält Gesundheits- und Trainingsdaten nur nach deiner ausdrücklichen Freigabe.","Cloud AI receives health and training data only after your explicit permission.")}</p></div>
  <section className="card stack"><label className="row"><input style={{width:20}} type="checkbox" checked={p.local_ai_only} onChange={e=>setP({...p,local_ai_only:e.target.checked})}/><span><strong>{bi(lang,"Nur lokale KI","Local AI only")}</strong><small style={{display:"block"}}>{bi(lang,"Es werden ausschließlich lokale Provider wie Ollama verwendet.","Only local providers such as Ollama are used.")}</small></span></label>
  <label className="row"><input style={{width:20}} type="checkbox" disabled={p.local_ai_only} checked={p.cloud_health_ai_allowed} onChange={e=>setP({...p,cloud_health_ai_allowed:e.target.checked})}/><span><strong>{bi(lang,"Gesundheits- und Trainingsdaten für Cloud-KI freigeben","Allow health and training data for cloud AI")}</strong><small style={{display:"block"}}>{bi(lang,"Erforderlich, bevor OpenAI, Anthropic oder andere Cloud-Provider diese Daten verarbeiten dürfen.","Required before OpenAI, Anthropic or another cloud provider may process these data.")}</small></span></label>
  <div><button onClick={save}>{bi(lang,"Speichern","Save")}</button> {saved&&<span className="status-ok">{saved}</span>}</div></section></AppShell>;
}
