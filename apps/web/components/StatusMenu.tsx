"use client";
// Compact status pill for the top bar: system, data connections and refresh in one hover/click menu.
import {useEffect,useRef,useState} from "react";
import Link from "next/link";
import {useCachedQuery,invalidateDataCache} from "../lib/data-cache";
import {bi,useI18n} from "../lib/i18n";
import {overallStatus} from "../lib/todayLayout";

type Conn={source:string;name:string;connected:boolean;status?:string|null;last_error_code?:string|null;last_synced_at?:string|null};

function ago(value:string|null|undefined,lang:"de"|"en"){
  if(!value)return bi(lang,"noch nie","never");
  const minutes=Math.round((Date.now()-new Date(value).getTime())/60000);
  if(!Number.isFinite(minutes))return "—";
  if(minutes<1)return bi(lang,"gerade eben","just now");
  if(minutes<60)return bi(lang,`vor ${minutes} Min`,`${minutes} min ago`);
  const hours=Math.round(minutes/60);
  if(hours<36)return bi(lang,`vor ${hours} Std`,`${hours} h ago`);
  return new Date(value).toLocaleDateString(lang==="de"?"de-DE":"en-GB",{day:"2-digit",month:"2-digit"});
}

export default function StatusMenu(){
  const {lang}=useI18n();
  const sources=useCachedQuery<{connections:Conn[]}>("/health/sources",60000);
  const [online,setOnline]=useState(true),[open,setOpen]=useState(false),[pinned,setPinned]=useState(false);
  const root=useRef<HTMLDivElement>(null),closeTimer=useRef<ReturnType<typeof setTimeout>|null>(null);
  useEffect(()=>{
    const update=()=>setOnline(navigator.onLine);update();
    window.addEventListener("online",update);window.addEventListener("offline",update);
    const outside=(e:PointerEvent)=>{if(root.current&&e.target instanceof Node&&!root.current.contains(e.target)){setOpen(false);setPinned(false)}};
    const esc=(e:KeyboardEvent)=>{if(e.key==="Escape"){setOpen(false);setPinned(false)}};
    document.addEventListener("pointerdown",outside);document.addEventListener("keydown",esc);
    return()=>{window.removeEventListener("online",update);window.removeEventListener("offline",update);document.removeEventListener("pointerdown",outside);document.removeEventListener("keydown",esc)};
  },[]);
  const conns=sources.data?.connections??[];
  const state=overallStatus(conns,online&&!sources.error);
  const label=state==="ok"?bi(lang,"Alles verbunden","All connected"):state==="attention"?bi(lang,"Hinweis","Attention"):state==="offline"?bi(lang,"Offline","Offline"):bi(lang,"Keine Quelle","No source");
  const show=()=>{if(closeTimer.current)clearTimeout(closeTimer.current);setOpen(true)};
  const hide=()=>{if(pinned)return;closeTimer.current=setTimeout(()=>setOpen(false),180)};
  const updated=sources.updatedAt?new Date(sources.updatedAt).toLocaleTimeString(lang==="de"?"de-DE":"en-GB",{hour:"2-digit",minute:"2-digit"}):null;
  return <div className={`status-menu status-${state}`} ref={root} onMouseEnter={show} onMouseLeave={hide}>
    <button type="button" className="status-pill" aria-expanded={open} aria-controls="status-menu-panel" onClick={()=>{setPinned(!(open&&pinned));setOpen(!(open&&pinned))}} onFocus={show}>
      <i aria-hidden="true"/><span>{label}</span>
    </button>
    {open&&<div className="status-panel" id="status-menu-panel" role="dialog" aria-label={bi(lang,"Status & Verbindungen","Status & connections")}>
      <div className="status-row"><span className={`status-dot ${online&&!sources.error?"ok":"bad"}`} aria-hidden="true"/><div><strong>PenguCoach</strong><small>{online&&!sources.error?bi(lang,"System erreichbar","System reachable"):bi(lang,"Keine Verbindung zum Server","No connection to the server")}</small></div></div>
      {conns.map(c=>{
        const s=c.status==="reauth_required"?"bad":c.connected?(c.last_error_code?"warn":"ok"):"off";
        return <Link prefetch={false} key={c.source} href={`/settings/${c.source}`} className="status-row status-link" onClick={()=>setOpen(false)}>
          <span className={`status-dot ${s}`} aria-hidden="true"/>
          <div><strong>{c.name}</strong><small>{c.status==="reauth_required"?bi(lang,"Neu anmelden","Sign in again"):c.connected?`${bi(lang,"Sync","Sync")} ${ago(c.last_synced_at,lang)}`:bi(lang,"Nicht verbunden · einrichten","Not connected · set up")}</small></div>
          <span aria-hidden="true">›</span>
        </Link>;
      })}
      <div className="status-foot">
        <small>{updated?bi(lang,`Ansicht von ${updated}`,`View from ${updated}`):""}</small>
        <button type="button" className="ghost compact" onClick={()=>invalidateDataCache()} disabled={sources.loading}>{sources.loading?bi(lang,"Lädt …","Loading …"):bi(lang,"Aktualisieren","Refresh")} ↻</button>
      </div>
    </div>}
  </div>;
}
