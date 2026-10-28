"use client";
import {useEffect,useState} from "react";
import Link from "next/link";
import {useSession} from "../lib/session";
import {api} from "../lib/api";
import {cacheQueryResult,useCachedQuery} from "../lib/data-cache";
import {bi,useI18n} from "../lib/i18n";

type UpdateStatus={status:string;latest_version?:string;url:string;stale?:boolean;checked_at?:string;retry_after_seconds?:number};
const PATH="/settings/update-status",RELEASES="https://github.com/Borderlane-HA/PenguCoach/releases";
let checking:Promise<void>|null=null;
const listeners=new Set<()=>void>();
function notify(){listeners.forEach(fn=>fn())}
function checkNow(){
 if(checking)return checking;
 checking=api<UpdateStatus>("/settings/update-check",{cache:"no-store"}).then(data=>{cacheQueryResult(PATH,data)}).finally(()=>{checking=null;notify()});
 notify();return checking;
}
function RefreshIcon(){return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M20 7v5h-5M4 17v-5h5"/><path d="M6.1 7a7 7 0 0 1 11.6-1L20 9M4 15l2.3 3A7 7 0 0 0 17.9 17"/></svg>}
export function useUpdates(){
 const query=useCachedQuery<UpdateStatus>(PATH,600000),[busy,setBusy]=useState(!!checking),[error,setError]=useState("");
 useEffect(()=>{const listener=()=>setBusy(!!checking);listeners.add(listener);setBusy(!!checking);return()=>{listeners.delete(listener)}},[]);
 useEffect(()=>{setError("")},[query.updatedAt]);
 const check=async()=>{setError("");try{await checkNow()}catch{setError("unavailable")}};
 return {...query,busy,error:error||query.error,check};
}
function resultLabel(data:UpdateStatus|undefined,lang:"de"|"en",error:string){
 if(error||data?.stale||data?.status==="unavailable")return bi(lang,"Prüfung momentan nicht möglich","Unable to check right now");
 if(data?.status==="available")return bi(lang,`Update verfügbar · ${data.latest_version}`,`Update available · ${data.latest_version}`);
 if(data?.status==="current")return bi(lang,"Du bist auf dem neuesten Stand","You're up to date");
 return bi(lang,"Release-Stand nicht bestimmbar","Release status unknown");
}
export function UpdateCheck(){
 const {lang}=useI18n(),{data,busy,error,check}=useUpdates();
 const checked=data?.checked_at?new Date(data.checked_at):null;
 return <section className="card update-check-card"><div><span className="eyebrow">UPDATES</span><h2>{bi(lang,"Neue Versionen","New versions")}</h2><p className="muted">{bi(lang,"Bei Nutzung der App prüfen wir automatisch alle 6 Stunden auf neue GitHub-Releases.","While you use the app, we check for new GitHub releases every 6 hours.")}</p></div><p className="update-check-result" role="status">{busy?bi(lang,"Version wird geprüft …","Checking for updates …"):!data&&!error?bi(lang,"Release-Stand wird geladen …","Loading release status …"):resultLabel(data,lang,error)}</p>{checked&&!Number.isNaN(checked.getTime())&&<small className="muted">{bi(lang,"Zuletzt erfolgreich geprüft","Last successful check")}: {checked.toLocaleString(lang==="de"?"de-DE":"en-GB")}</small>}<div className="form-actions"><button type="button" className="ghost update-check-button" disabled={busy} onClick={()=>void check()}><RefreshIcon/>{busy?bi(lang,"Prüfe …","Checking …"):bi(lang,"Jetzt prüfen","Check now")}</button><a className="text-link" href={data?.url||RELEASES} target="_blank" rel="noopener noreferrer">{bi(lang,"GitHub-Releases öffnen","Open GitHub releases")} ↗</a></div><small className="muted">{bi(lang,"Manuelles Prüfen umgeht den 6-Stunden-Cache. Wiederholte Klicks innerhalb einer Minute verwenden dasselbe Ergebnis.","Manual checks bypass the 6-hour cache. Repeat clicks within one minute reuse the same result.")}</small></section>;
}
export default function UpdateNotice({version,mobile=false}:{version:string;mobile?:boolean}){
 const {lang}=useI18n(),{me}=useSession(),{data,busy,error,check}=useUpdates();
 // Checking stays in the sidebar; only the result leads to the update area.
 const [asked,setAsked]=useState(false);
 const available=data?.status==="available",target=me?.role==="admin"?"/admin/system#updates":"/settings/updates";
 const checkLabel=bi(lang,"Nach Updates suchen","Check for updates");
 const showResult=asked||available;
 const result=busy?bi(lang,"Prüfe …","Checking …"):error||data?.stale||data?.status==="unavailable"?bi(lang,"Prüfung nicht möglich","Check not possible"):available?bi(lang,"Update verfügbar","Update available"):data?.status==="current"?bi(lang,"Aktuell","Up to date"):bi(lang,"Status unbekannt","Status unknown");
 return <div className={`version-notice ${mobile?"mobile-version-notice":""} ${available?"has-update":""}`}>
  <div className="version-notice-row"><Link prefetch={false} className="side-version" href={target} title={bi(lang,"Updates & Release Notes","Updates & release notes")}>v{version}</Link><button type="button" className={`version-check ${busy?"spinning":""}`} aria-label={checkLabel} title={checkLabel} disabled={busy} onClick={()=>{setAsked(true);void check()}}><RefreshIcon/></button></div>
  {showResult&&(busy?<span className="update-result checking" role="status"><span>{result}</span></span>
   :<Link prefetch={false} className={`update-result ${available?"update-notice-link":"is-current"}`} href={target} role="status" aria-label={available?bi(lang,`Update verfügbar · ${data?.latest_version} · öffnen`,`Update available · ${data?.latest_version} · open`):bi(lang,`${result} · Updates öffnen`,`${result} · open updates`)}>
     {available?<><span className="update-notice-icon" aria-hidden="true">↑</span><span><strong>{result}</strong><small>{data?.latest_version}</small></span></>:<><span className="update-result-dot" aria-hidden="true"/><span><strong>{result}</strong><small>{bi(lang,"Details ansehen","View details")}</small></span></>}
   </Link>)}
 </div>;
}

/** Slim banner above every page: an update exists. Dismissed per version, so the next release shows again. */
export function UpdateBanner(){
 const {lang}=useI18n(),{me}=useSession(),{data}=useUpdates();
 const [dismissed,setDismissed]=useState<string|null>(null);
 useEffect(()=>{try{setDismissed(localStorage.getItem("pengucoach_update_banner_dismissed"))}catch{}},[]);
 const version=data?.latest_version;
 if(data?.status!=="available"||!version||dismissed===version)return null;
 const target=me?.role==="admin"?"/admin/system#updates":"/settings/updates";
 return <div className="update-banner" role="status">
  <span className="update-banner-dot" aria-hidden="true"/>
  <Link prefetch={false} href={target}><strong>{bi(lang,"Update verfügbar","Update available")}</strong> <span>{version}</span> <span className="update-banner-cta">{me?.role==="admin"?bi(lang,"Ansehen & installieren →","View & install →"):bi(lang,"Was ist neu? →","What's new? →")}</span></Link>
  <button type="button" className="update-banner-close" aria-label={bi(lang,"Hinweis ausblenden","Dismiss")} onClick={()=>{try{localStorage.setItem("pengucoach_update_banner_dismissed",version)}catch{};setDismissed(version)}}>✕</button>
 </div>;
}
