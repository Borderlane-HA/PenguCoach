"use client";

import {FormEvent,useEffect,useState} from "react";
import {api} from "../lib/api";
import {bi,useI18n} from "../lib/i18n";

export default function Home(){
  const{lang,setLang}=useI18n();const[username,setUsername]=useState("");const[password,setPassword]=useState("");const[error,setError]=useState("");
  useEffect(()=>{api<{setup_required:boolean}>("/setup/status").then(s=>{if(s.setup_required){location.replace("/setup");return}api<{safety_required:boolean}>("/auth/me").then(me=>location.replace(me.safety_required?"/safety":"/today")).catch(()=>undefined)}).catch(()=>undefined)},[]);
  async function submit(e:FormEvent){e.preventDefault();setError("");try{await api("/auth/login",{method:"POST",body:JSON.stringify({username,password})});location.replace("/safety")}catch(e){setError(e instanceof Error?e.message:"Login failed")}}
  return <main className="login-page">
    <section className="login-brand-panel">
      <div className="login-brand"><span className="brand-mark large custom"><img src="/pengucoach-icon.svg" alt=""/></span><span><strong>PenguCoach</strong><small>Training & Health</small></span></div>
      <div className="login-message"><span className="eyebrow">SELF-HOSTED · PRIVATE · YOUR DATA</span><h1>{bi(lang,"Training verstehen. Gesundheit im Blick behalten.","Understand training. Keep health in view.")}</h1><p>{bi(lang,"Garmin-Daten, FIT-Tiefenanalyse und dein persönlicher AI Coach – lokal kontrolliert und übersichtlich aufbereitet.","Garmin data, deep FIT analytics and your personal AI Coach — locally controlled and clearly presented.")}</p></div>
      <div className="login-feature-row"><span>✓ Garmin & FIT</span><span>✓ AI Coach</span><span>✓ {bi(lang,"Lokale Daten","Local data")}</span></div>
    </section>
    <section className="login-form-panel">
      <div className="login-form-wrap">
        <div className="login-top"><span className="mobile-login-brand">PenguCoach</span><button className="language-switch" onClick={()=>setLang(lang==="de"?"en":"de")}>{lang==="de"?"DE":"EN"}<span>⌄</span></button></div>
        <div className="login-copy"><span className="eyebrow">{bi(lang,"Willkommen zurück","Welcome back")}</span><h2>{bi(lang,"Bei PenguCoach anmelden","Sign in to PenguCoach")}</h2><p>{bi(lang,"Deine Trainings- und Gesundheitsdaten warten auf dich.","Your training and health data is ready for you.")}</p></div>
        <form onSubmit={submit} className="login-form">
          <label>{bi(lang,"Benutzername","Username")}<input required value={username} onChange={e=>setUsername(e.target.value)} autoComplete="username" placeholder={bi(lang,"Benutzername eingeben","Enter username")}/></label>
          <label>{bi(lang,"Passwort","Password")}<input required type="password" value={password} onChange={e=>setPassword(e.target.value)} autoComplete="current-password" placeholder="••••••••"/></label>
          {error&&<div className="login-error">{error}</div>}
          <button className="login-submit">{bi(lang,"Anmelden","Sign in")} <span>→</span></button>
        </form>
        <small className="login-note">{bi(lang,"Fitness-, Trainings- und Wellnessanalyse. Kein Medizinprodukt.","Fitness, training and wellness analysis. Not a medical device.")}</small>
      </div>
    </section>
  </main>
}
