"use client";

import {FormEvent,useEffect,useRef,useState} from "react";
import AppShell from "../../../components/AppShell";
import {api} from "../../../lib/api";
import {bi,useI18n} from "../../../lib/i18n";

type GarminSettings={
  enabled:boolean;
  interval_minutes:number;
  fit_download_enabled:boolean;
  fit_analysis_enabled:boolean;
  historical_days:number;
  sync_health?:boolean;
  sync_activities?:boolean;
  sync_body?:boolean;
  sync_training?:boolean;
};
type Status={connected:boolean;status:string;display_name?:string;last_successful_sync_at?:string;next_sync_at?:string;cooldown_until?:string;last_error_code?:string;settings?:GarminSettings};
type Job={ready:boolean;successful:boolean;result?:Record<string,unknown>;error?:string;state?:string};

const sleep=(ms:number)=>new Promise(r=>setTimeout(r,ms));
const SYNC_JOB_KEY="pengucoach_garmin_sync_job";

export default function GarminSettingsPage(){
  const{lang}=useI18n();
  const[status,setStatus]=useState<Status|null>(null),[email,setEmail]=useState(""),[password,setPassword]=useState(""),[challenge,setChallenge]=useState(""),[code,setCode]=useState("");
  const[msg,setMsg]=useState(""),[syncing,setSyncing]=useState(false),[historyOpen,setHistoryOpen]=useState(false),[syncState,setSyncState]=useState("");
  const noticeTimer=useRef<ReturnType<typeof setTimeout>|null>(null);

  const refresh=()=>api<Status>("/garmin/status").then(setStatus);
  const showNotice=(text:string,timeout=3500)=>{setMsg(text);if(noticeTimer.current)clearTimeout(noticeTimer.current);if(timeout>0)noticeTimer.current=setTimeout(()=>setMsg(""),timeout)};

  useEffect(()=>{
    void refresh();
    const existing=localStorage.getItem(SYNC_JOB_KEY);
    if(existing){setSyncing(true);void pollSync(existing)}
    return()=>{if(noticeTimer.current)clearTimeout(noticeTimer.current)};
    // eslint-disable-next-line react-hooks/exhaustive-deps
  },[]);

  async function connect(e:FormEvent){
    e.preventDefault();setMsg("");
    try{
      const r=await api<any>("/garmin/auth/start",{method:"POST",body:JSON.stringify({email,password})});
      setPassword("");
      if(r.status==="mfa_required")setChallenge(r.challenge_id);
      else{showNotice(bi(lang,"Garmin verbunden","Garmin connected"));void refresh()}
    }catch(e){showNotice(e instanceof Error?e.message:"Error",6000)}
  }

  async function mfa(e:FormEvent){
    e.preventDefault();
    try{
      await api("/garmin/auth/mfa",{method:"POST",body:JSON.stringify({challenge_id:challenge,code})});
      setChallenge("");setCode("");showNotice(bi(lang,"Garmin verbunden","Garmin connected"));void refresh();
    }catch(e){showNotice(e instanceof Error?e.message:"Error",6000)}
  }

  async function pollSync(taskId:string){
    setSyncing(true);setSyncState(bi(lang,"Synchronisierung läuft…","Synchronization in progress…"));
    for(let i=0;i<1200;i++){
      try{
        const j=await api<Job>(`/jobs/${taskId}`);
        if(j.ready){
          localStorage.removeItem(SYNC_JOB_KEY);
          setSyncing(false);setSyncState("");
          await refresh();
          if(j.successful){
            const resultStatus=String(j.result?.status??"success");
            if(resultStatus==="already_running")showNotice(bi(lang,"Eine Synchronisierung läuft bereits.","A synchronization is already running."),5000);
            else showNotice(bi(lang,"Synchronisierung abgeschlossen.","Synchronization completed."));
          }else showNotice(`${bi(lang,"Synchronisierung fehlgeschlagen","Synchronization failed")}: ${j.error??"Unknown error"}`,7000);
          return;
        }
        setSyncState(j.state==="STARTED"?bi(lang,"Garmin-Daten werden verarbeitet…","Garmin data is being processed…"):bi(lang,"Synchronisierung wartet auf den Worker…","Synchronization is waiting for the worker…"));
      }catch{
        setSyncState(bi(lang,"Synchronisierungsstatus wird geprüft…","Checking synchronization status…"));
      }
      await sleep(1250);
    }
    setSyncing(false);setSyncState("");
    showNotice(bi(lang,"Die Synchronisierung läuft ungewöhnlich lange. Prüfe den Worker-Status.","Synchronization is taking unusually long. Check the worker status."),8000);
  }

  async function sync(){
    if(syncing)return;
    setMsg("");setSyncing(true);setSyncState(bi(lang,"Synchronisierung wird gestartet…","Starting synchronization…"));
    try{
      const r=await api<any>("/garmin/sync/now",{method:"POST"});
      localStorage.setItem(SYNC_JOB_KEY,r.task_id);
      await pollSync(r.task_id);
    }catch(e){
      setSyncing(false);setSyncState("");
      showNotice(e instanceof Error?e.message:String(e),7000);
    }
  }

  async function saveSettings(){
    if(!status?.settings)return;
    await api("/garmin/sync/settings",{method:"PUT",body:JSON.stringify(status.settings)});
    showNotice(bi(lang,"Einstellungen gespeichert","Settings saved"));
    await refresh();
  }

  async function startImport(){
    const days=status?.settings?.historical_days??365;
    const r=await api<any>("/garmin/import",{method:"POST",body:JSON.stringify({days})});
    showNotice(`${bi(lang,"Historienimport gestartet","History import started")} · ${r.task_id}`,6000);
  }

  async function disconnect(){
    if(!confirm(bi(lang,"Garmin trennen? Lokale Daten bleiben erhalten.","Disconnect Garmin? Local data is preserved.")))return;
    await api("/garmin/disconnect",{method:"POST"});
    localStorage.removeItem(SYNC_JOB_KEY);setSyncing(false);setSyncState("");await refresh();
  }

  const fmt=(value?:string)=>value?new Date(value).toLocaleString(lang==="de"?"de-DE":"en-GB"):"—";
  const patchSettings=(patch:Partial<GarminSettings>)=>status?.settings&&setStatus({...status,settings:{...status.settings,...patch}});

  return <AppShell title="Garmin">
    <div className="garmin-head"><div><span className="eyebrow">GARMIN CONNECT</span><h1>{bi(lang,"Garmin synchronisieren","Sync Garmin")}</h1><p className="muted">{bi(lang,"Ein Klick holt aktuelle Tageswerte, Aktivitäten und – falls aktiviert – FIT-Daten.","One click fetches current daily metrics, activities and FIT data when enabled.")}</p></div><span className={`connection-pill ${status?.connected?"online":"offline"}`}><i/>{status?.connected?bi(lang,"Verbunden","Connected"):bi(lang,"Nicht verbunden","Not connected")}</span></div>

    {syncing&&<div className="garmin-sync-progress" role="status"><span className="sync-spinner"/><div><strong>{bi(lang,"Synchronisierung läuft","Synchronization in progress")}</strong><small>{syncState}</small></div></div>}
    {!syncing&&msg&&<div className="ai-toast">{msg}</div>}

    {status?.connected&&<section className="card garmin-sync-card"><div className="garmin-account"><div className="garmin-device-mark">G</div><div><span className="metric-label">Account</span><strong>{status.display_name??"Garmin Connect"}</strong><small>{bi(lang,"Nur-Lese-Verbindung","Read-only connection")}</small></div></div><div className="garmin-sync-meta"><div><small>{bi(lang,"Letzter Sync","Last sync")}</small><strong>{fmt(status.last_successful_sync_at)}</strong></div><div><small>{bi(lang,"Nächster Sync","Next sync")}</small><strong>{fmt(status.next_sync_at)}</strong></div></div><button className="garmin-sync-primary" disabled={syncing} onClick={sync}>{syncing?bi(lang,"Synchronisiert…","Synchronizing…"):bi(lang,"Synchronisieren","Synchronize")}</button></section>}

    {!status?.connected&&!challenge&&<form className="card stack" onSubmit={connect}><div><span className="eyebrow">CONNECTION</span><h2>{bi(lang,"Garmin verbinden","Connect Garmin")}</h2><p className="muted">{bi(lang,"Das Passwort wird nur für die Garmin-Anmeldung verwendet und nicht dauerhaft gespeichert.","The password is used only for Garmin sign-in and is not stored persistently.")}</p></div><label>E-Mail<input type="email" required value={email} onChange={e=>setEmail(e.target.value)}/></label><label>{bi(lang,"Passwort","Password")}<input type="password" required value={password} onChange={e=>setPassword(e.target.value)}/></label><button>{bi(lang,"Verbinden","Connect")}</button></form>}
    {challenge&&<form className="card stack" onSubmit={mfa}><h2>MFA / Zwei-Faktor-Bestätigung</h2><p>{bi(lang,"Gib den von Garmin angeforderten Code ein.","Enter the verification code requested by Garmin.")}</p><label>Code<input required value={code} onChange={e=>setCode(e.target.value)}/></label><button>{bi(lang,"Bestätigen","Verify")}</button></form>}

    {status?.connected&&status.settings&&<section className="card garmin-settings-card">
      <div className="section-heading"><div><span className="eyebrow">AUTOMATION</span><h2>{bi(lang,"Automatische Synchronisierung","Automatic synchronization")}</h2><p className="muted">{bi(lang,"Zeitplan und FIT-Verarbeitung getrennt und übersichtlich konfigurieren.","Configure schedule and FIT processing separately and clearly.")}</p></div><span className="badge">{status.settings.enabled?"AUTO ON":"AUTO OFF"}</span></div>
      <div className="garmin-settings-layout">
        <div className="garmin-setting-panel">
          <div className="garmin-setting-panel-head"><strong>{bi(lang,"Zeitplan","Schedule")}</strong><small>{bi(lang,"Regelmäßige Garmin-Aktualisierung","Regular Garmin refresh")}</small></div>
          <label className="switch-row"><input type="checkbox" checked={status.settings.enabled} onChange={e=>patchSettings({enabled:e.target.checked})}/><span/><div><strong>{bi(lang,"Automatischer Sync","Automatic sync")}</strong><small>{bi(lang,"Im Hintergrund neue Garmin-Daten holen","Fetch new Garmin data in the background")}</small></div></label>
          <label className="garmin-interval-control"><span>{bi(lang,"Intervall","Interval")}</span><select disabled={!status.settings.enabled} value={status.settings.interval_minutes} onChange={e=>patchSettings({interval_minutes:Number(e.target.value)})}><option value={15}>15 min</option><option value={30}>30 min</option><option value={60}>1 h</option><option value={120}>2 h</option><option value={360}>6 h</option><option value={720}>12 h</option><option value={1440}>24 h</option></select></label>
        </div>
        <div className="garmin-setting-panel">
          <div className="garmin-setting-panel-head"><strong>{bi(lang,"Aktivitätsdaten","Activity data")}</strong><small>{bi(lang,"Originaldaten und lokale Analyse","Original files and local analysis")}</small></div>
          <label className="switch-row"><input type="checkbox" checked={status.settings.fit_download_enabled} onChange={e=>patchSettings({fit_download_enabled:e.target.checked})}/><span/><div><strong>Original FIT</strong><small>{bi(lang,"FIT-Dateien neuer Aktivitäten laden","Download FIT files for new activities")}</small></div></label>
          <label className="switch-row"><input type="checkbox" checked={status.settings.fit_analysis_enabled} onChange={e=>patchSettings({fit_analysis_enabled:e.target.checked})}/><span/><div><strong>{bi(lang,"FIT analysieren","Analyze FIT")}</strong><small>{bi(lang,"Zeitreihen und Trainingsmetriken erzeugen","Generate time series and training metrics")}</small></div></label>
        </div>
      </div>
      <div className="form-actions garmin-settings-actions"><button onClick={saveSettings}>{bi(lang,"Einstellungen speichern","Save settings")}</button><button className="ghost" onClick={disconnect}>{bi(lang,"Garmin trennen","Disconnect Garmin")}</button></div>
    </section>}

    {status?.connected&&status.settings&&<section className="card garmin-history-card"><button type="button" className="garmin-history-toggle" onClick={()=>setHistoryOpen(v=>!v)}><div><span className="eyebrow">HISTORY</span><strong>{bi(lang,"Historie & Ersteinrichtung","History & initial setup")}</strong><small>{bi(lang,"Nur nötig, wenn du ältere Daten nachladen oder den Historienzeitraum ändern möchtest.","Only needed when you want to backfill older data or change the history range.")}</small></div><span>{historyOpen?"−":"+"}</span></button>{historyOpen&&<div className="garmin-history-body"><label>{bi(lang,"Zeitraum","Period")}<select value={status.settings.historical_days} onChange={e=>patchSettings({historical_days:Number(e.target.value)})}><option value={30}>30 {bi(lang,"Tage","days")}</option><option value={90}>90 {bi(lang,"Tage","days")}</option><option value={365}>1 {bi(lang,"Jahr","year")}</option><option value={730}>2 {bi(lang,"Jahre","years")}</option><option value={1825}>5 {bi(lang,"Jahre","years")}</option><option value={3650}>10 {bi(lang,"Jahre","years")}</option><option value={0}>{bi(lang,"Alle verfügbaren Daten","All available data")}</option></select></label><p className="muted">{status.settings.historical_days===0?bi(lang,"PenguCoach ermittelt den Startpunkt aus deiner ältesten Garmin-Aktivität und lädt ab dort Tages-, Trainings- und Aktivitätsdaten nach. Das kann bei vielen Jahren deutlich länger dauern.","PenguCoach finds the start from your oldest Garmin activity and backfills daily, training and activity data from there. Many years can take considerably longer."):bi(lang,"Der Historienimport fragt viele Garmin-Tage ab und kann länger dauern. Für normale tägliche Updates nicht verwenden.","History import requests many Garmin days and can take a while. It is not needed for normal daily updates.")}</p><button className="ghost" onClick={startImport}>{status.settings.historical_days===0?bi(lang,"Alle Daten nachladen","Backfill all data"):bi(lang,"Historie jetzt nachladen","Backfill history now")}</button></div>}</section>}

    {status?.last_error_code&&<section className="card subtle"><strong className="status-warn">{status.last_error_code}</strong></section>}
  </AppShell>;
}
