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
type Job={ready:boolean;successful:boolean;result?:Record<string,any>;progress?:Record<string,any>;error?:string;state?:string};

const sleep=(ms:number)=>new Promise(r=>setTimeout(r,ms));
const SYNC_JOB_KEY="pengucoach_garmin_sync_job";
const HISTORY_JOB_KEY="pengucoach_garmin_history_job";

export default function GarminSettingsPage(){
  const{lang}=useI18n();
  const[status,setStatus]=useState<Status|null>(null),[email,setEmail]=useState(""),[password,setPassword]=useState(""),[challenge,setChallenge]=useState(""),[code,setCode]=useState("");
  const[msg,setMsg]=useState(""),[syncing,setSyncing]=useState(false),[historyOpen,setHistoryOpen]=useState(false),[syncState,setSyncState]=useState("");
  const[historyRunning,setHistoryRunning]=useState(false),[historyProgress,setHistoryProgress]=useState<Record<string,any>|null>(null);
  const noticeTimer=useRef<ReturnType<typeof setTimeout>|null>(null);

  const refresh=()=>api<Status>("/garmin/status").then(setStatus);
  const showNotice=(text:string,timeout=3500)=>{setMsg(text);if(noticeTimer.current)clearTimeout(noticeTimer.current);if(timeout>0)noticeTimer.current=setTimeout(()=>setMsg(""),timeout)};

  useEffect(()=>{
    void refresh();
    const existing=localStorage.getItem(SYNC_JOB_KEY);
    if(existing){setSyncing(true);void pollSync(existing)}
    const history=localStorage.getItem(HISTORY_JOB_KEY);
    if(history){setHistoryOpen(true);setHistoryRunning(true);void pollHistory(history)}
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
            if(resultStatus==="already_running")showNotice(bi(lang,"Eine Garmin-Aufgabe läuft bereits.","A Garmin task is already running."),5000);
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
    if(syncing||historyRunning)return;
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

  function historyText(p:Record<string,any>|null){
    if(!p)return bi(lang,"Historienimport wartet auf den Worker…","History import is waiting for the worker…");
    if(p.state==="rate_limited")return bi(lang,`Garmin bremst gerade – automatischer neuer Versuch in ${p.retry_in_seconds??"?"} s.`,`Garmin is throttling requests — automatic retry in ${p.retry_in_seconds??"?"} s.`);
    if(p.phase==="activities")return bi(lang,`Aktivitäten: ${p.matched??p.scanned??0} gefunden · ${p.pages??0} Seiten`,`Activities: ${p.matched??p.scanned??0} found · ${p.pages??0} pages`);
    if(p.phase==="wellness")return bi(lang,`Tagesdaten: ${p.completed_days??0}/${p.total_days??"?"} · ${p.current_date??""}`,`Daily data: ${p.completed_days??0}/${p.total_days??"?"} · ${p.current_date??""}`);
    if(p.phase==="fit_queue")return bi(lang,`FIT-Analyse wird eingereiht: ${p.queued??0}/${p.total??"?"}`,`Queuing FIT analysis: ${p.queued??0}/${p.total??"?"}`);
    if(p.phase==="done")return bi(lang,"Historienimport abgeschlossen.","History import completed.");
    return String(p.message??bi(lang,"Historienimport läuft…","History import in progress…"));
  }

  async function pollHistory(taskId:string){
    setHistoryRunning(true);
    for(let i=0;i<100000;i++){
      try{
        const j=await api<Job>(`/jobs/${taskId}`);
        if(j.progress)setHistoryProgress(j.progress);
        if(j.ready){
          localStorage.removeItem(HISTORY_JOB_KEY);
          setHistoryRunning(false);
          const result=j.result??{};
          setHistoryProgress(j.successful?{phase:"done",state:String(result.status??"success"),...result}:null);
          await refresh();
          if(j.successful){
            const rs=String(result.status??"success");
            if(rs==="already_running")showNotice(bi(lang,"Eine Garmin-Aufgabe läuft bereits.","A Garmin task is already running."),6000);
            else if(rs==="rate_limited")showNotice(bi(lang,"Garmin hat den Import nach mehreren Versuchen begrenzt. Er kann gefahrlos erneut gestartet werden und setzt fehlende Daten fort.","Garmin rate-limited the import after several retries. It can be safely restarted and will continue missing data."),9000);
            else{
              const count=(result.activities as any)?.matched;
              showNotice(count!==undefined?bi(lang,`Historienimport abgeschlossen · ${count} Aktivitäten erfasst.`,`History import completed · ${count} activities captured.`):bi(lang,"Historienimport abgeschlossen.","History import completed."),7000);
            }
          }else showNotice(`${bi(lang,"Historienimport fehlgeschlagen","History import failed")}: ${j.error??"Unknown error"}`,9000);
          return;
        }
      }catch{}
      await sleep(2500);
    }
    setHistoryRunning(false);
    showNotice(bi(lang,"Der Historienjob läuft sehr lange. Beim Neuladen wird der Status automatisch wieder aufgenommen.","The history job is taking a long time. Its status will automatically resume after a reload."),9000);
  }

  async function startImport(){
    if(historyRunning||syncing)return;
    const days=status?.settings?.historical_days??365;
    setHistoryRunning(true);setHistoryProgress({phase:"activities",state:"queued",matched:0,pages:0});
    try{
      const r=await api<any>("/garmin/import",{method:"POST",body:JSON.stringify({days})});
      localStorage.setItem(HISTORY_JOB_KEY,r.task_id);
      await pollHistory(r.task_id);
    }catch(e){
      setHistoryRunning(false);setHistoryProgress(null);
      showNotice(e instanceof Error?e.message:String(e),8000);
    }
  }

  async function disconnect(){
    if(!confirm(bi(lang,"Garmin trennen? Lokale Daten bleiben erhalten.","Disconnect Garmin? Local data is preserved.")))return;
    await api("/garmin/disconnect",{method:"POST"});
    localStorage.removeItem(SYNC_JOB_KEY);localStorage.removeItem(HISTORY_JOB_KEY);setSyncing(false);setHistoryRunning(false);setSyncState("");setHistoryProgress(null);await refresh();
  }

  const fmt=(value?:string)=>value?new Date(value).toLocaleString(lang==="de"?"de-DE":"en-GB"):"—";
  const patchSettings=(patch:Partial<GarminSettings>)=>status?.settings&&setStatus({...status,settings:{...status.settings,...patch}});
  const historyPercent=typeof historyProgress?.percent==="number"?Math.max(0,Math.min(100,historyProgress.percent)):null;

  return <AppShell title="Garmin">
    <div className="garmin-head"><div><span className="eyebrow">GARMIN CONNECT</span><h1>{bi(lang,"Garmin synchronisieren","Sync Garmin")}</h1><p className="muted">{bi(lang,"Ein Klick holt aktuelle Tageswerte, Aktivitäten und – falls aktiviert – FIT-Daten.","One click fetches current daily metrics, activities and FIT data when enabled.")}</p></div><span className={`connection-pill ${status?.connected?"online":"offline"}`}><i/>{status?.connected?bi(lang,"Verbunden","Connected"):bi(lang,"Nicht verbunden","Not connected")}</span></div>

    {syncing&&<div className="garmin-sync-progress" role="status"><span className="sync-spinner"/><div><strong>{bi(lang,"Synchronisierung läuft","Synchronization in progress")}</strong><small>{syncState}</small></div></div>}
    {!syncing&&msg&&<div className="ai-toast">{msg}</div>}

    {status?.connected&&<section className="card garmin-sync-card"><div className="garmin-account"><div className="garmin-device-mark">G</div><div><span className="metric-label">Account</span><strong>{status.display_name??"Garmin Connect"}</strong><small>{bi(lang,"Nur-Lese-Verbindung","Read-only connection")}</small></div></div><div className="garmin-sync-meta"><div><small>{bi(lang,"Letzter Sync","Last sync")}</small><strong>{fmt(status.last_successful_sync_at)}</strong></div><div><small>{bi(lang,"Nächster Sync","Next sync")}</small><strong>{fmt(status.next_sync_at)}</strong></div></div><button className="garmin-sync-primary" disabled={syncing||historyRunning} onClick={sync}>{syncing?bi(lang,"Synchronisiert…","Synchronizing…"):historyRunning?bi(lang,"Historienimport läuft…","History import running…"):bi(lang,"Synchronisieren","Synchronize")}</button></section>}

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

    {status?.connected&&status.settings&&<section className="card garmin-history-card"><button type="button" className="garmin-history-toggle" onClick={()=>setHistoryOpen(v=>!v)}><div><span className="eyebrow">HISTORY</span><strong>{bi(lang,"Historie & Ersteinrichtung","History & initial setup")}</strong><small>{bi(lang,"Aktivitäten werden zuerst vollständig seitenweise geladen; Tages- und Erholungsdaten folgen separat und können bei einem Neustart übersprungen werden, wenn sie bereits vollständig importiert wurden.","Activities are imported first using full pagination; daily and recovery data follows separately and completed historical days can be skipped on a restart.")}</small></div><span>{historyOpen?"−":"+"}</span></button>{historyOpen&&<div className="garmin-history-body"><label>{bi(lang,"Zeitraum","Period")}<select disabled={historyRunning} value={status.settings.historical_days} onChange={e=>patchSettings({historical_days:Number(e.target.value)})}><option value={30}>30 {bi(lang,"Tage","days")}</option><option value={90}>90 {bi(lang,"Tage","days")}</option><option value={365}>1 {bi(lang,"Jahr","year")}</option><option value={730}>2 {bi(lang,"Jahre","years")}</option><option value={1825}>5 {bi(lang,"Jahre","years")}</option><option value={3650}>10 {bi(lang,"Jahre","years")}</option><option value={0}>{bi(lang,"Alle verfügbaren Daten","All available data")}</option></select></label><p className="muted">{status.settings.historical_days===0?bi(lang,"„Alle Daten“ paginiert die Garmin-Aktivitätsliste bis zum tatsächlichen Ende und verwendet die älteste gefundene Aktivität als Start für Tages-, Schlaf-, HRV-, Stress- und weitere Gesundheitsdaten. Große Konten mit vielen hundert oder tausend Aktivitäten sind ausdrücklich unterstützt.","“All data” paginates the Garmin activity catalogue until its actual end and uses the oldest discovered activity as the starting point for daily, sleep, HRV, stress and other health data. Large accounts with hundreds or thousands of activities are explicitly supported."):bi(lang,"Der Historienimport lädt Aktivitäten für den gewählten Zeitraum seitenweise und ergänzt danach die Tagesdaten. Bereits abgeschlossene ältere Tage werden bei einem erneuten Lauf übersprungen.","The history import loads activities for the selected range by pages and then fills daily data. Completed older days are skipped on subsequent runs.")}</p>{historyRunning&&<div className="history-import-progress" role="status"><div className="history-import-progress-head"><span className="sync-spinner"/><div><strong>{bi(lang,"Historienimport läuft","History import running")}</strong><small>{historyText(historyProgress)}</small></div></div>{historyPercent!==null&&<div className="history-progress-track"><i style={{width:`${historyPercent}%`}}/></div>}<div className="history-progress-meta">{historyProgress?.phase==="activities"&&<><span>{bi(lang,"Seiten","Pages")}: {historyProgress.pages??0}</span><span>{bi(lang,"Aktivitäten","Activities")}: {historyProgress.matched??historyProgress.scanned??0}</span>{historyProgress.oldest_date&&<span>{bi(lang,"Älteste bisher","Oldest so far")}: {historyProgress.oldest_date}</span>}</>}{historyProgress?.phase==="wellness"&&<><span>{bi(lang,"Tage","Days")}: {historyProgress.completed_days??0}/{historyProgress.total_days??"?"}</span><span>{bi(lang,"Übersprungen (bereits vorhanden)","Skipped (already complete)")}: {historyProgress.skipped_days??0}</span></>}</div></div>}<button className="ghost" disabled={historyRunning||syncing} onClick={startImport}>{historyRunning?bi(lang,"Import läuft…","Import running…"):status.settings.historical_days===0?bi(lang,"Alle Daten nachladen","Backfill all data"):bi(lang,"Historie jetzt nachladen","Backfill history now")}</button></div>}</section>}

    {status?.last_error_code&&<section className="card subtle"><strong className="status-warn">{status.last_error_code}</strong></section>}
  </AppShell>;
}
