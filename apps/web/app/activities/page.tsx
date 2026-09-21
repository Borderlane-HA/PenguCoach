"use client";

import {useEffect,useMemo,useRef,useState} from "react";
import AppShell from "../../components/AppShell";
import {API,api} from "../../lib/api";
import {bi,useI18n} from "../../lib/i18n";

type A={id:string;name?:string;sport_type?:string;started_at?:string;distance_m?:number;duration_seconds?:number;avg_hr?:number;training_load?:number;fit_status:string;source?:string;original_filename?:string};
type ImportResult={activity_id:string};
const duration=(s?:number)=>s?`${Math.floor(s/3600)}:${String(Math.floor((s%3600)/60)).padStart(2,"0")}:${String(Math.floor(s%60)).padStart(2,"0")}`:"—";
const sportInfo=(s?:string)=>{const v=(s||"").toLowerCase();if(v.includes("run"))return{icon:"RUN",label:"Running",tone:"run"};if(v.includes("bike")||v.includes("cycling"))return{icon:"BIKE",label:"Cycling",tone:"bike"};if(v.includes("swim"))return{icon:"SWIM",label:"Swimming",tone:"swim"};if(v.includes("strength")||v.includes("weight"))return{icon:"GYM",label:"Strength",tone:"strength"};return{icon:"MOVE",label:s||"Activity",tone:"other"}};

export default function Activities(){
  const{lang}=useI18n();const[rows,setRows]=useState<A[]>([]);const[query,setQuery]=useState("");
  const[uploadOpen,setUploadOpen]=useState(false),[file,setFile]=useState<File|null>(null),[name,setName]=useState(""),[sport,setSport]=useState("auto"),[uploading,setUploading]=useState(false),[uploadError,setUploadError]=useState("");
  const fileInput=useRef<HTMLInputElement|null>(null);
  const load=()=>api<A[]>("/activities?limit=200").then(setRows);
  useEffect(()=>{void load()},[]);
  const filtered=useMemo(()=>{const q=query.trim().toLowerCase();if(!q)return rows;return rows.filter(a=>`${a.name||""} ${a.sport_type||""} ${a.original_filename||""}`.toLowerCase().includes(q))},[rows,query]);

  async function upload(){
    if(!file||uploading)return;
    setUploading(true);setUploadError("");
    const body=new FormData();body.append("file",file);if(name.trim())body.append("name",name.trim());body.append("sport_type",sport);
    try{
      const response=await fetch(`${API}/activities/import`,{method:"POST",body,credentials:"include"});
      const data=await response.json().catch(()=>({}));
      if(!response.ok){
        const detail=data?.detail;
        if(detail?.activity_id){location.href=`/activities/${detail.activity_id}`;return}
        throw new Error(typeof detail==="string"?detail:detail?.code||`HTTP ${response.status}`);
      }
      const result=data as ImportResult;
      location.href=`/activities/${result.activity_id}`;
    }catch(error:any){
      const code=String(error?.message||error);
      const messages:Record<string,string>={
        UNSUPPORTED_ACTIVITY_FILE:bi(lang,"Dateityp nicht unterstützt. Verwende FIT, GPX, TCX oder ZIP mit FIT.","Unsupported file type. Use FIT, GPX, TCX or a ZIP containing FIT."),
        INVALID_ACTIVITY_FILE:bi(lang,"Die Trainingsdatei konnte nicht gelesen werden.","The activity file could not be read."),
        ACTIVITY_UPLOAD_TOO_LARGE:bi(lang,"Die Datei ist größer als 50 MB.","The file is larger than 50 MB."),
        UPLOAD_TOO_LARGE:bi(lang,"Die Datei ist größer als 50 MB.","The file is larger than 50 MB."),
      };
      setUploadError(messages[code]||code);
    }finally{setUploading(false)}
  }

  function closeUpload(){if(uploading)return;setUploadOpen(false);setFile(null);setName("");setSport("auto");setUploadError("")}

  return <AppShell>
    <section className="page-head-modern activities-head"><div><span className="eyebrow">{bi(lang,"Trainingstagebuch","Training log")}</span><h1>{bi(lang,"Aktivitäten","Activities")}</h1><p>{bi(lang,"Garmin-Daten und manuell importierte Trainingsdateien gemeinsam analysieren.","Analyse Garmin data and manually imported activity files together.")}</p></div><div className="activities-head-actions"><div className="activity-search"><span>⌕</span><input value={query} onChange={e=>setQuery(e.target.value)} placeholder={bi(lang,"Aktivitäten durchsuchen…","Search activities…")}/></div><button className="activity-upload-button" onClick={()=>setUploadOpen(true)}><span aria-hidden="true">↑</span>{bi(lang,"Training importieren","Import activity")}</button></div></section>

    <section className="activity-summary-strip"><div><span>{bi(lang,"Aktivitäten","Activities")}</span><strong>{rows.length}</strong></div><div><span>{bi(lang,"Gefiltert","Filtered")}</span><strong>{filtered.length}</strong></div><div><span>{bi(lang,"Analysiert","Analysed")}</span><strong>{rows.filter(x=>x.fit_status==="parsed").length}</strong></div><div><span>{bi(lang,"Manuell","Manual")}</span><strong>{rows.filter(x=>x.source==="manual_upload").length}</strong></div></section>

    <section className="card activity-list-card">{filtered.length?<div className="modern-activity-list">{filtered.map(a=>{const s=sportInfo(a.sport_type);const manual=a.source==="manual_upload";return <a className="modern-activity-row" href={`/activities/${a.id}`} key={a.id}><span className={`activity-sport-icon tone-${s.tone}`}>{s.icon}</span><span className="activity-row-main"><strong>{a.name??a.sport_type??"Activity"}</strong><small>{a.started_at?new Date(a.started_at).toLocaleString(lang==="de"?"de-DE":"en-US",{day:"2-digit",month:"short",year:"numeric",hour:"2-digit",minute:"2-digit"}):""} · {s.label}{manual?` · ${bi(lang,"Upload","Upload")}`:""}</small></span><span className="activity-row-stat"><small>{bi(lang,"Distanz","Distance")}</small><strong>{a.distance_m?`${(a.distance_m/1000).toFixed(2)} km`:"—"}</strong></span><span className="activity-row-stat"><small>{bi(lang,"Dauer","Duration")}</small><strong>{duration(a.duration_seconds)}</strong></span><span className="activity-row-stat"><small>Ø HR</small><strong>{a.avg_hr?`${Math.round(a.avg_hr)} bpm`:"—"}</strong></span><span className={`fit-status ${a.fit_status}`}>{manual?bi(lang,"IMPORT","IMPORT"):"FIT"} {a.fit_status}</span><span className="activity-row-arrow">→</span></a>})}</div>:<div className="empty-state"><strong>{bi(lang,"Keine passenden Aktivitäten","No matching activities")}</strong><span>{query?bi(lang,"Passe die Suche an oder lösche den Suchbegriff.","Adjust or clear your search."):bi(lang,"Synchronisiere Garmin oder importiere FIT-, GPX- bzw. TCX-Dateien manuell.","Sync Garmin or manually import FIT, GPX or TCX files.")}</span></div>}</section>

    {uploadOpen&&<div className="activity-upload-backdrop" role="presentation" onMouseDown={e=>{if(e.currentTarget===e.target)closeUpload()}}><section className="activity-upload-modal" role="dialog" aria-modal="true" aria-labelledby="activity-upload-title"><div className="activity-upload-title"><div><span className="eyebrow">{bi(lang,"OHNE GARMIN","WITHOUT GARMIN")}</span><h2 id="activity-upload-title">{bi(lang,"Training importieren","Import activity")}</h2><p>{bi(lang,"Lade eine vorhandene Trainingsdatei hoch. PenguCoach speichert sie lokal, erzeugt Zeitreihen und führt dieselbe Analyse wie bei Garmin-Aktivitäten aus.","Upload an existing activity file. PenguCoach stores it locally, creates time series and runs the same analytics used for Garmin activities.")}</p></div><button className="upload-close" onClick={closeUpload} aria-label={bi(lang,"Schließen","Close")}>×</button></div>
      <button type="button" className={`activity-dropzone ${file?"selected":""}`} onClick={()=>fileInput.current?.click()}><span className="dropzone-icon">↑</span>{file?<><strong>{file.name}</strong><small>{(file.size/1024/1024).toFixed(2)} MB · {bi(lang,"Datei ändern","Change file")}</small></>:<><strong>{bi(lang,"FIT, GPX oder TCX auswählen","Choose FIT, GPX or TCX")}</strong><small>{bi(lang,"Auch ZIP-Dateien mit einer FIT-Datei · maximal 50 MB","ZIP files containing a FIT file are supported too · max 50 MB")}</small></>}</button>
      <input ref={fileInput} className="activity-file-input" type="file" accept=".fit,.gpx,.tcx,.zip,application/zip" onChange={e=>{setFile(e.target.files?.[0]??null);setUploadError("")}}/>
      <div className="activity-upload-fields"><label><span>{bi(lang,"Name (optional)","Name (optional)")}</span><input value={name} onChange={e=>setName(e.target.value)} placeholder={file?.name.replace(/\.[^.]+$/,"")||bi(lang,"z. B. Feierabendrunde","e.g. Evening ride")}/></label><label><span>{bi(lang,"Sportart","Sport")}</span><select value={sport} onChange={e=>setSport(e.target.value)}><option value="auto">{bi(lang,"Automatisch erkennen","Detect automatically")}</option><option value="running">{bi(lang,"Laufen","Running")}</option><option value="cycling">{bi(lang,"Radfahren","Cycling")}</option><option value="swimming">{bi(lang,"Schwimmen","Swimming")}</option><option value="strength_training">{bi(lang,"Krafttraining","Strength")}</option><option value="walking">{bi(lang,"Gehen","Walking")}</option><option value="hiking">{bi(lang,"Wandern","Hiking")}</option><option value="other">{bi(lang,"Sonstiges","Other")}</option></select></label></div>
      {uploadError&&<div className="activity-upload-error">{uploadError}</div>}
      <div className="activity-upload-actions"><button className="ghost" onClick={closeUpload} disabled={uploading}>{bi(lang,"Abbrechen","Cancel")}</button><button onClick={()=>void upload()} disabled={!file||uploading}>{uploading?bi(lang,"Wird importiert…","Importing…"):bi(lang,"Importieren & analysieren","Import & analyse")}</button></div>
      <div className="activity-upload-note">{bi(lang,"Unterstützt: FIT, GPX, TCX und ZIP mit FIT. CSV wird bewusst nicht automatisch interpretiert, da das Format keine einheitliche Trainingsstruktur vorgibt.","Supported: FIT, GPX, TCX and ZIP containing FIT. CSV is intentionally not auto-interpreted because it has no standard activity schema.")}</div>
    </section></div>}
  </AppShell>
}
