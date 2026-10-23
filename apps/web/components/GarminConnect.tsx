"use client";

import {FormEvent,useEffect,useState} from "react";
import {api} from "../lib/api";
import {bi} from "../lib/i18n";
import {AuthMode,CAPABILITIES,KEY_SETTINGS_URL,PersonalApiInfo,addMonths,cleanKey,garminError} from "../lib/garminAuth";

type Lang="de"|"en";
type Props={lang:Lang;status:{status?:string;auth_mode?:AuthMode|null;personal_api?:PersonalApiInfo}|null;renewing?:boolean;onConnected:()=>void;onCancel?:()=>void;notify:(text:string,timeout?:number)=>void};

const EXPIRY_PRESETS=[1,3,6,12];

/** Connection form with a choice between Garmin login and the official Personal API key. */
export default function GarminConnect({lang,status,renewing=false,onConnected,onCancel,notify}:Props){
  const de=lang==="de";
  const previous=status?.auth_mode??null;
  const [mode,setMode]=useState<AuthMode>(renewing?"personal_api":previous??"password");
  const [email,setEmail]=useState(""),[password,setPassword]=useState(""),[challenge,setChallenge]=useState(""),[code,setCode]=useState("");
  const [apiKey,setApiKey]=useState(""),[expires,setExpires]=useState(()=>addMonths(new Date(),12)),[busy,setBusy]=useState(false),[guideOpen,setGuideOpen]=useState(true);
  useEffect(()=>{if(previous&&!renewing)setMode(previous)},[previous,renewing]);
  const settingsUrl=status?.personal_api?.key_settings_url||KEY_SETTINGS_URL;
  const fail=(e:unknown)=>notify(garminError(e instanceof Error?e.message:String(e),lang),8000);

  async function login(e:FormEvent){
    e.preventDefault();setBusy(true);
    try{
      const r=await api<any>("/garmin/auth/start",{method:"POST",body:JSON.stringify({email,password})});
      setPassword("");
      if(r.status==="mfa_required")setChallenge(r.challenge_id);
      else{notify(bi(lang,"Garmin verbunden","Garmin connected"));onConnected()}
    }catch(err){fail(err)}finally{setBusy(false)}
  }
  async function mfa(e:FormEvent){
    e.preventDefault();setBusy(true);
    try{await api("/garmin/auth/mfa",{method:"POST",body:JSON.stringify({challenge_id:challenge,code})});setChallenge("");setCode("");notify(bi(lang,"Garmin verbunden","Garmin connected"));onConnected()}
    catch(err){fail(err)}finally{setBusy(false)}
  }
  async function connectKey(e:FormEvent){
    e.preventDefault();setBusy(true);
    try{
      await api("/garmin/auth/personal-api",{method:"POST",body:JSON.stringify({api_key:cleanKey(apiKey),expires_on:expires||null})});
      setApiKey("");notify(bi(lang,renewing?"API-Key erneuert":"Garmin über Personal API verbunden",renewing?"API key renewed":"Garmin connected via Personal API"));onConnected();
    }catch(err){fail(err)}finally{setBusy(false)}
  }

  if(challenge)return <form className="card stack" onSubmit={mfa}><h2>MFA / Zwei-Faktor-Bestätigung</h2><p>{bi(lang,"Gib den von Garmin angeforderten Code ein.","Enter the verification code requested by Garmin.")}</p><label>Code<input required autoComplete="one-time-code" value={code} onChange={e=>setCode(e.target.value)}/></label><button disabled={busy}>{bi(lang,"Bestätigen","Verify")}</button></form>;

  const reauth=status?.status==="reauth_required";
  return <section className="card stack garmin-connect-card">
    <div><span className="eyebrow">CONNECTION</span><h2>{renewing?bi(lang,"API-Key erneuern","Renew API key"):bi(lang,"Garmin verbinden","Connect Garmin")}</h2>
      {reauth&&!renewing&&<p className="status-warn">{previous==="personal_api"?bi(lang,"Garmin hat den gespeicherten API-Key nicht mehr akzeptiert (abgelaufen oder widerrufen). Trage einen neuen Key ein – deine Daten bleiben erhalten.","Garmin no longer accepts the stored API key (expired or revoked). Enter a new key – your data is kept."):bi(lang,"Garmin verlangt eine neue Anmeldung. Deine Daten bleiben erhalten.","Garmin requires a new sign-in. Your data is kept.")}</p>}
    </div>
    {!renewing&&<div className="garmin-method-switch" role="radiogroup" aria-label={bi(lang,"Verbindungsart","Connection method")}>
      {([["password",bi(lang,"Garmin-Login","Garmin login"),bi(lang,"E-Mail & Passwort · alle Funktionen","E-mail & password · all features")],["personal_api",bi(lang,"Personal API Key","Personal API key"),bi(lang,"Offizieller Garmin-Zugang · nur lesen","Official Garmin access · read-only")]] as const).map(([key,label,hint])=><button type="button" role="radio" aria-checked={mode===key} key={key} className={mode===key?"active":""} onClick={()=>setMode(key)}><strong>{label}</strong><small>{hint}</small></button>)}
    </div>}

    {!renewing&&<div className="garmin-capabilities" aria-label={bi(lang,"Funktionsvergleich","Feature comparison")}>{CAPABILITIES.map(c=>{const ok=mode==="password"?c.password:c.personal;return <span key={c.key} className={ok?"ok":"off"}><i aria-hidden>{ok?"✓":"–"}</i>{de?c.de:c.en}</span>})}</div>}

    {mode==="password"&&!renewing&&<form className="stack" onSubmit={login}>
      <p className="muted">{bi(lang,"Das Passwort wird nur für die Garmin-Anmeldung verwendet und nicht dauerhaft gespeichert. Gespeichert werden nur die Anmelde-Tokens von Garmin (verschlüsselt).","The password is used only for Garmin sign-in and is not stored. Only Garmin's sign-in tokens are kept (encrypted).")}</p>
      <label>E-Mail<input type="email" required autoComplete="username" value={email} onChange={e=>setEmail(e.target.value)}/></label>
      <label>{bi(lang,"Passwort","Password")}<input type="password" required autoComplete="current-password" value={password} onChange={e=>setPassword(e.target.value)}/></label>
      <button disabled={busy}>{busy?bi(lang,"Verbinde…","Connecting…"):bi(lang,"Verbinden","Connect")}</button>
    </form>}

    {mode==="personal_api"&&<form className="stack" onSubmit={connectKey}>
      <div className="garmin-guide">
        <button type="button" className="garmin-guide-toggle" aria-expanded={guideOpen} onClick={()=>setGuideOpen(v=>!v)}><strong>{bi(lang,"Anleitung: API-Key in Garmin Connect erstellen","Guide: create an API key in Garmin Connect")}</strong></button>
        {guideOpen&&<ol>
          <li>{bi(lang,"Öffne die Garmin-Connect-Seite für persönliche API-Keys und melde dich mit deinem Garmin-Konto an:","Open the Garmin Connect page for personal API keys and sign in with your Garmin account:")} <a href={settingsUrl} target="_blank" rel="noopener noreferrer">{bi(lang,"Garmin Connect → Einstellungen → Personal API","Garmin Connect → Settings → Personal API")} ↗</a></li>
          <li>{bi(lang,"Lege dort einen neuen persönlichen API-Key an. Ist die Seite für dein Konto nicht verfügbar, nutze vorerst die Verbindungsart „Garmin-Login“.","Create a new personal API key there. If the page is not available for your account, use the “Garmin login” method for now.")}</li>
          <li>{bi(lang,"Wähle eine Laufzeit (30 Tage bis 1 Jahr). Empfehlung: 1 Jahr – merke dir das Ablaufdatum.","Pick a lifetime (30 days to 1 year). Recommendation: 1 year – note the expiry date.")}</li>
          <li>{bi(lang,"Kopiere den Key sofort und vollständig – Garmin zeigt ihn unter Umständen nur einmal an. Geht er verloren, einfach einen neuen erstellen.","Copy the complete key right away – Garmin may show it only once. If it gets lost, simply create a new one.")}</li>
          <li>{bi(lang,"Füge den Key unten ein, trage dasselbe Ablaufdatum ein und klicke „Mit API-Key verbinden“. PenguCoach prüft den Key sofort bei Garmin.","Paste the key below, enter the same expiry date and click “Connect with API key”. PenguCoach checks the key with Garmin right away.")}</li>
        </ol>}
        <p className="garmin-write-note">{bi(lang,"Der Key ist so viel wert wie dein Passwort für deine Gesundheitsdaten: nicht weitergeben. PenguCoach speichert ihn verschlüsselt und nutzt ihn nur zum Lesen. Vor Ablauf erinnert dich diese Seite; einen widerrufenen oder abgelaufenen Key ersetzt du einfach durch einen neuen – Daten gehen nicht verloren. Workouts zu Garmin übertragen geht mit dem API-Key nicht; dafür bitte „Garmin-Login“ wählen.","Treat the key like your password for your health data: do not share it. PenguCoach stores it encrypted and only reads with it. This page reminds you before it expires; replace a revoked or expired key with a new one – no data is lost. Sending workouts to Garmin is not possible with the API key; choose “Garmin login” for that.")}</p>
      </div>
      <label>{bi(lang,"Personal API Key","Personal API key")}<input type="password" required minLength={8} autoComplete="off" spellCheck={false} value={apiKey} onChange={e=>setApiKey(e.target.value)} placeholder={bi(lang,"Key aus Garmin Connect einfügen","Paste the key from Garmin Connect")}/></label>
      <label>{bi(lang,"Ablaufdatum des Keys","Key expiry date")}<input type="date" value={expires} min={addMonths(new Date(),0)} onChange={e=>setExpires(e.target.value)}/></label>
      <div className="garmin-expiry-presets">{EXPIRY_PRESETS.map(m=><button type="button" className="ghost" key={m} onClick={()=>setExpires(addMonths(new Date(),m))}>{m===12?bi(lang,"1 Jahr","1 year"):`${m} ${bi(lang,m===1?"Monat":"Monate",m===1?"month":"months")}`}</button>)}<button type="button" className="ghost" onClick={()=>setExpires("")}>{bi(lang,"Unbekannt","Unknown")}</button></div>
      {previous==="password"&&!renewing&&status?.status==="connected"&&<p className="muted">{bi(lang,"Hinweis: Mit dem API-Key ersetzt du die bisherige Garmin-Anmeldung. Der Workout-Export wird dabei ausgeschaltet.","Note: the API key replaces the current Garmin sign-in. Workout export is switched off.")}</p>}
      <div className="form-actions"><button disabled={busy||!cleanKey(apiKey)}>{busy?bi(lang,"Prüfe Key…","Checking key…"):renewing?bi(lang,"Key ersetzen","Replace key"):bi(lang,"Mit API-Key verbinden","Connect with API key")}</button>{onCancel&&<button type="button" className="ghost" onClick={onCancel}>{bi(lang,"Abbrechen","Cancel")}</button>}</div>
    </form>}
  </section>;
}
