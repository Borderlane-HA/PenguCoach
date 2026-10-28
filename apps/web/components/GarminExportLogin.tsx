"use client";

import {FormEvent,useState} from "react";
import {api} from "../lib/api";
import {bi} from "../lib/i18n";
import {garminError} from "../lib/garminAuth";

type Lang="de"|"en";
type Info={status?:string;connected?:boolean;display_name?:string|null;last_error_code?:string|null}|null|undefined;

/** Garmin login used only for workout export while data comes from the Personal API key. */
export default function GarminExportLogin({lang,info,onChanged,notify}:{lang:Lang;info:Info;onChanged:()=>void;notify:(text:string,timeout?:number)=>void}){
  const [open,setOpen]=useState(false),[email,setEmail]=useState(""),[password,setPassword]=useState(""),[challenge,setChallenge]=useState(""),[code,setCode]=useState(""),[busy,setBusy]=useState(false);
  const fail=(e:unknown)=>notify(garminError(e instanceof Error?e.message:String(e),lang),8000);
  const done=()=>{setOpen(false);setChallenge("");setCode("");setPassword("");notify(bi(lang,"Garmin-Login für den Export gespeichert","Garmin login for export saved"));onChanged()};

  async function start(e:FormEvent){
    e.preventDefault();setBusy(true);
    try{const r=await api<any>("/garmin/auth/export/start",{method:"POST",body:JSON.stringify({email,password})});setPassword("");if(r.status==="mfa_required")setChallenge(r.challenge_id);else done()}
    catch(err){fail(err)}finally{setBusy(false)}
  }
  async function mfa(e:FormEvent){
    e.preventDefault();setBusy(true);
    try{await api("/garmin/auth/mfa",{method:"POST",body:JSON.stringify({challenge_id:challenge,code})});done()}
    catch(err){fail(err)}finally{setBusy(false)}
  }
  async function remove(){
    if(!confirm(bi(lang,"Garmin-Login für den Export entfernen? Der Datensync über den API-Key bleibt unverändert.","Remove the Garmin login for export? The data sync via the API key stays unchanged.")))return;
    setBusy(true);try{await api("/garmin/auth/export/disconnect",{method:"POST"});onChanged()}catch(err){fail(err)}finally{setBusy(false)}
  }

  const connected=Boolean(info?.connected),expired=info?.status==="reauth_required";
  return <div className="garmin-export-login">
    <div className="garmin-export-login-head"><div>
      <strong>{connected?bi(lang,"Zusatz-Login für den Export aktiv","Extra login for export active"):expired?bi(lang,"Export-Login abgelaufen","Export login expired"):bi(lang,"Zusatz-Login für den Export","Extra login for export")}</strong>
      <small>{connected?`${info?.display_name??"Garmin"} · ${bi(lang,"wird nur zum Übertragen von Workouts benutzt","used only to send workouts")}`:expired?garminError(info?.last_error_code||"GARMIN_EXPORT_LOGIN_EXPIRED",lang):bi(lang,"Daten kommen weiter über den API-Key. Der Garmin-Login wird nur gespeichert (verschlüsselt, ohne Passwort), um Trainingspläne zu Garmin zu schicken.","Data keeps coming through the API key. The Garmin login is stored (encrypted, without the password) only to send training plans to Garmin.")}</small>
    </div>{connected?<button type="button" className="ghost" disabled={busy} onClick={()=>void remove()}>{bi(lang,"Entfernen","Remove")}</button>:!open&&!challenge&&<button type="button" onClick={()=>setOpen(true)}>{expired?bi(lang,"Neu anmelden","Sign in again"):bi(lang,"Garmin-Login hinzufügen","Add Garmin login")}</button>}</div>
    {challenge?<form className="stack" onSubmit={mfa}><label>{bi(lang,"Bestätigungscode von Garmin","Verification code from Garmin")}<input required autoComplete="one-time-code" value={code} onChange={e=>setCode(e.target.value)}/></label><div className="form-actions"><button disabled={busy}>{bi(lang,"Bestätigen","Verify")}</button></div></form>
    :open&&<form className="stack" onSubmit={start}><div className="grid2"><label>E-Mail<input type="email" required autoComplete="username" value={email} onChange={e=>setEmail(e.target.value)}/></label><label>{bi(lang,"Passwort","Password")}<input type="password" required autoComplete="current-password" value={password} onChange={e=>setPassword(e.target.value)}/></label></div><div className="form-actions"><button disabled={busy}>{busy?bi(lang,"Verbinde…","Connecting…"):bi(lang,"Für Export anmelden","Sign in for export")}</button><button type="button" className="ghost" onClick={()=>setOpen(false)}>{bi(lang,"Abbrechen","Cancel")}</button></div></form>}
  </div>;
}
