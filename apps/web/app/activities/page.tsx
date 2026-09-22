"use client";

import {useEffect,useRef,useState} from "react";
import AppShell from "../../components/AppShell";
import {API,api} from "../../lib/api";
import {bi,useI18n} from "../../lib/i18n";

type A={id:string;name?:string;sport_type?:string;started_at?:string;distance_m?:number;duration_seconds?:number;avg_hr?:number;training_load?:number;fit_status:string;source?:string;original_filename?:string};
type ImportResult={activity_id:string};
type Paged={items:A[];page:number;per_page:number;pages:number;total:number;filtered_total:number;analyzed_total:number;manual_total:number;query:string};
const duration=(s?:number)=>s?`${Math.floor(s/3600)}:${String(Math.floor((s%3600)/60)).padStart(2,"0")}:${String(Math.floor(s%60)).padStart(2,"0")}`:"—";
const sportInfo=(s?:string)=>{const v=(s||"").toLowerCase();if(v.includes("run"))return{icon:"RUN",label:"Running",tone:"run"};if(v.includes("bike")||v.includes("cycling"))return{icon:"BIKE",label:"Cycling",tone:"bike"};if(v.includes("swim"))return{icon:"SWIM",label:"Swimming",tone:"swim"};if(v.includes("strength")||v.includes("weight"))return{icon:"GYM",label:"Strength",tone:"strength"};return{icon:"MOVE",label:s||"Activity",tone:"other"}};

export default function Activities(){
  const{lang}=useI18n();
  const[data,setData]=useState<Paged|null>(null),[page,setPage]=useState(1),[perPage,setPerPage]=useState(50),[query,setQuery]=useState(""),[search,setSearch]=useState(""),[loading,setLoading]=useState(false);
  const[uploadOpen,setUploadOpen]=useState(false),[file,setFile]=useState<File|null>(null),[name,setName]=useState(""),[sport,setSport]=useState("auto"),[uploading,setUploading]=useState(false),[uploadError,setUploadError]=useState("");
  const fileInput=useRef<HTMLInputElement|null>(null);

  useEffect(()=>{const t=setTimeout(()=>{setPage(1);setSearch(query.trim())},300);return()=>clearTimeout(t)},[query]);
  useEffect(()=>{let active=true;setLoading(true);const params=new URLSearchParams({page:String(page),per_page:String(perPage)});if(search)params.set("q",search);void api<Paged>(`/activities?${params.toString()}`).then(v=>{if(active){setData(v);if(v.page!==page)setPage(v.page)}}).finally(()=>{if(active)setLoading(false)});return()=>{active=false}},[page,perPage,search]);

  const rows=data?.items??[];
  const first=data&&data.filtered_total?((data.page-1)*data.per_page)+1:0;
  const last=data?Math.min(data.page*data.per_page,data.filtered_total):0;
  const pageButtons=(()=>{const pages=data?.pages??1,current=data?.page??1;const out:number[]=[];const start=Math.max(1,Math.min(current-2,pages-4));const end=Math.min(pages,start+4);for(let i=start;i<=end;i++)out.push(i);return out})();

  async function upload(){
    if(!file||uploading)return;
    setUploading(true);setUploadError("");
    const body=new FormData();body.append("file",file);if(name.trim())body.append("name",name.trim());body.append("sport_type",sport);
    try{
      const response=await fetch(`${API}/activities/import`,{method:"POST",body,credentials:"include"});
      const value=await response.json().catch(()=>({}));
      if(!response.ok){const detail=value?.detail;if(detail?.activity_id){location.href=`/activities/${detail.activity_id}`;return}throw new Error(typeof detail==="string"?detail:detail?.code||`HTTP ${response.status}`)}
      const result=value as ImportResult;location.href=`/activities/${result.activity_id}`;
    }catch(error:any){
      const code=String(error?.message||error);const messages:Record<string,string>={UNSUPPORTED_ACTIVITY_FILE:bi(lang,"Dateityp nicht unterstützt. Verwende FIT, GPX, TCX oder ZIP mit FIT.","Unsupported file type. Use FIT, GPX, TCX or a ZIP containing FIT."),INVALID_ACTIVITY_FILE:bi(lang,"Die Trainingsdatei konnte nicht gelesen werden.","The activity file could not be read."),ACTIVITY_UPLOAD_TOO_LARGE:bi(lang,"Die Datei ist größer als 50 MB.","The file is larger than 50 MB."),UPLOAD_TOO_LARGE:bi(lang,"Die Datei ist größer als 50 MB.","The file is larger than 50 MB.")};setUploadError(messages[code]||code);
    }finally{setUploading(false)}
  }
  function closeUpload(){if(uploading)return;setUploadOpen(false);setFile(null);setName("");setSport("auto");setUploadError("")}

  return <AppShell>
    <section className="page-head-modern activities-head"><div><span className="eyebrow">{bi(lang,"Trainingstagebuch","Training log")}</span><h1>{bi(lang,"Aktivitäten","Activities")}</h1><p>{bi(lang,"Garmin-Daten und manuell importierte Trainingsdateien gemeinsam analysieren.","Analyse Garmin data and manually imported activity files together.")}</p></div><div className="activities-head-actions"><div className="activity-search"><span>⌕</span><input value={query} onChange={e=>setQuery(e.target.value)} placeholder={bi(lang,"Alle Aktivitäten durchsuchen…","Search all activities…")}/></div><button className="activity-upload-button" onClick={()=>setUploadOpen(true)}><span aria-hidden="true">↑</span>{bi(lang,"Training importieren","Import activity")}</button></div></section>

    <section className="activity-summary-strip"><div><span>{bi(lang,"Gesamt","Total")}</span><strong>{data?.total??"…"}</strong></div><div><span>{bi(lang,"Treffer","Matches")}</span><strong>{data?.filtered_total??"…"}</strong></div><div><span>{bi(lang,"Analysiert","Analysed")}</span><strong>{data?.analyzed_total??"…"}</strong></div><div><span>{bi(lang,"Manuell","Manual")}</span><strong>{data?.manual_total??"…"}</strong></div></section>

    <section className="activity-pagination-bar"><div><strong>{first}–{last}</strong> {bi(lang,"von","of")} <strong>{data?.filtered_total??0}</strong>{search&&<span> · {bi(lang,"Suche","Search")}: “{search}”</span>}</div><label>{bi(lang,"Pro Seite","Per page")}<select value={perPage} onChange={e=>{setPerPage(Number(e.target.value));setPage(1)}}><option value={25}>25</option><option value={50}>50</option><option value={100}>100</option></select></label><span>{bi(lang,"Seite","Page")} {data?.page??1} {bi(lang,"von","of")} {data?.pages??1}</span></section>

    <section className={`card activity-list-card ${loading?"is-loading":""}`}>{rows.length?<div className="modern-activity-list">{rows.map(a=>{const s=sportInfo(a.sport_type);const manual=a.source==="manual_upload";return <a className="modern-activity-row" href={`/activities/${a.id}`} key={a.id}><span className={`activity-sport-icon tone-${s.tone}`}>{s.icon}</span><span className="activity-row-main"><strong>{a.name??a.sport_type??"Activity"}</strong><small>{a.started_at?new Date(a.started_at).toLocaleString(lang==="de"?"de-DE":"en-US",{day:"2-digit",month:"short",year:"numeric",hour:"2-digit",minute:"2-digit"}):""} · {s.label}{manual?` · ${bi(lang,"Upload","Upload")}`:""}</small></span><span className="activity-row-stat"><small>{bi(lang,"Distanz","Distance")}</small><strong>{a.distance_m?`${(a.distance_m/1000).toFixed(2)} km`:"—"}</strong></span><span className="activity-row-stat"><small>{bi(lang,"Dauer","Duration")}</small><strong>{duration(a.duration_seconds)}</strong></span><span className="activity-row-stat"><small>Ø HR</small><strong>{a.avg_hr?`${Math.round(a.avg_hr)} bpm`:"—"}</strong></span><span className={`fit-status ${a.fit_status}`}>{manual?bi(lang,"IMPORT","IMPORT"):"FIT"} {a.fit_status}</span><span className="activity-row-arrow">→</span></a>})}</div>:<div className="empty-state"><strong>{bi(lang,"Keine passenden Aktivitäten","No matching activities")}</strong><span>{search?bi(lang,"Passe die Suche an oder lösche den Suchbegriff.","Adjust or clear your search."):bi(lang,"Synchronisiere Garmin oder importiere FIT-, GPX- bzw. TCX-Dateien manuell.","Sync Garmin or manually import FIT, GPX or TCX files.")}</span></div>}</section>

    {(data?.pages??1)>1&&<nav className="activity-pager" aria-label={bi(lang,"Aktivitätsseiten","Activity pages")}><button className="ghost" disabled={(data?.page??1)<=1} onClick={()=>setPage(1)}>«</button><button className="ghost" disabled={(data?.page??1)<=1} onClick={()=>setPage(p=>Math.max(1,p-1))}>‹</button>{pageButtons.map(p=><button key={p} className={p===data?.page?"active":"ghost"} onClick={()=>setPage(p)}>{p}</button>)}<button className="ghost" disabled={(data?.page??1)>=(data?.pages??1)} onClick={()=>setPage(p=>Math.min(data?.pages??p,p+1))}>›</button><button className="ghost" disabled={(data?.page??1)>=(data?.pages??1)} onClick={()=>setPage(data?.pages??1)}>»</button></nav>}

    {uploadOpen&&<div className="activity-upload-backdrop" role="presentation" onMouseDown={e=>{if(e.currentTarget===e.target)closeUpload()}}><section className="activity-upload-modal" role="dialog" aria-modal="true" aria-labelledby="activity-upload-title"><div className="activity-upload-title"><div><span className="eyebrow">{bi(lang,"OHNE GARMIN","WITHOUT GARMIN")}</span><h2 id="activity-upload-title">{bi(lang,"Training importieren","Import activity")}</h2><p>{bi(lang,"Lade eine vorhandene Trainingsdatei hoch. PenguCoach speichert sie lokal, erzeugt Zeitreihen und führt dieselbe Analyse wie bei Garmin-Aktivitäten aus.","Upload an existing activity file. PenguCoach stores it locally, creates time series and runs the same analytics used for Garmin activities.")}</p></div><button className="upload-close" onClick={closeUpload} aria-label={bi(lang,"Schließen","Close")}>×</button></div>
      <button type="button" className={`activity-dropzone ${file?"selected":""}`} onClick={()=>fileInput.current?.click()}><span className="dropzone-icon">↑</span>{file?<><strong>{file.name}</strong><small>{(file.size/1024/1024).toFixed(2)} MB · {bi(lang,"Datei ändern","Change file")}</small></>:<><strong>{bi(lang,"FIT, GPX oder TCX auswählen","Choose FIT, GPX or TCX")}</strong><small>{bi(lang,"Auch ZIP-Dateien mit einer FIT-Datei · maximal 50 MB","ZIP files containing a FIT file are supported too · max 50 MB")}</small></>}</button>
      <input ref={fileInput} className="activity-file-input" type="file" accept=".fit,.gpx,.tcx,.zip,application/zip" onChange={e=>{setFile(e.target.files?.[0]??null);setUploadError("")}}/>
      <div className="activity-upload-fields"><label><span>{bi(lang,"Name (optional)","Name (optional)")}</span><input value={name} onChange={e=>setName(e.target.value)} placeholder={file?.name.replace(/\.[^.]+$/i,"")||bi(lang,"z. B. Feierabendrunde","e.g. Evening ride")}/></label><label><span>{bi(lang,"Sportart","Sport")}</span><select value={sport} onChange={e=>setSport(e.target.value)}><option value="auto">{bi(lang,"Automatisch erkennen","Detect automatically")}</option><option value="running">{bi(lang,"Laufen","Running")}</option><option value="cycling">{bi(lang,"Radfahren","Cycling")}</option><option value="swimming">{bi(lang,"Schwimmen","Swimming")}</option><option value="strength_training">{bi(lang,"Krafttraining","Strength")}</option><option value="walking">{bi(lang,"Gehen","Walking")}</option><option value="hiking">{bi(lang,"Wandern","Hiking")}</option><option value="other">{bi(lang,"Sonstiges","Other")}</option></select></label></div>
      {uploadError&&<div className="activity-upload-error">{uploadError}</div>}
      <div className="activity-upload-actions"><button className="ghost" onClick={closeUpload} disabled={uploading}>{bi(lang,"Abbrechen","Cancel")}</button><button onClick={()=>void upload()} disabled={!file||uploading}>{uploading?bi(lang,"Wird importiert…","Importing…"):bi(lang,"Importieren & analysieren","Import & analyse")}</button></div>
      <div className="activity-upload-note">{bi(lang,"Unterstützt: FIT, GPX, TCX und ZIP mit FIT. CSV wird bewusst nicht automatisch interpretiert, da das Format keine einheitliche Trainingsstruktur vorgibt.","Supported: FIT, GPX, TCX and ZIP containing FIT. CSV is intentionally not auto-interpreted because it has no standard activity schema.")}</div>
    </section></div>}
  </AppShell>
}
