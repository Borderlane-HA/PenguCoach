"use client";
import {Fragment,useEffect,useRef,useState} from "react";
import {api} from "../lib/api";
import {bi,useI18n} from "../lib/i18n";
import {CHANGELOG_SOURCE,changelogLink,changelogSections} from "../lib/changelog";

type Result={status:string;content:string|null;checked_at?:string;stale?:boolean};
function inline(text:string){
 return text.split(/(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\([^\s)]+\))/g).map((part,i)=>{
  if(part.startsWith("**")&&part.endsWith("**"))return <strong key={i}>{part.slice(2,-2)}</strong>;
  if(part.startsWith("`")&&part.endsWith("`"))return <code key={i}>{part.slice(1,-1)}</code>;
  const link=part.match(/^\[([^\]]+)\]\(([^)]+)\)$/),href=link&&changelogLink(link[2]);
  return href?<a key={i} href={href} target="_blank" rel="noopener noreferrer">{link![1]} ↗</a>:<Fragment key={i}>{part}</Fragment>;
 });
}
function Notes({content}:{content:string}){
 return <div className="changelog-notes">{content.trim().split(/\r?\n/).map((raw,i)=>{
  const line=raw.trim();if(!line)return null;
  const heading=line.match(/^#{3,6}\s+(.+)$/),bullet=line.match(/^[-*]\s+(.+)$/);
  if(heading)return <h3 key={i}>{inline(heading[1])}</h3>;
  return bullet?<div className="changelog-bullet" key={i}><span aria-hidden="true">•</span><p>{inline(bullet[1])}</p></div>:<p key={i}>{inline(line)}</p>;
 })}</div>;
}
export default function Changelog({installedVersion}:{installedVersion?:string}){
 const{lang}=useI18n(),[open,setOpen]=useState(false),[data,setData]=useState<Result|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState(false),[visible,setVisible]=useState(6),[expanded,setExpanded]=useState<string|null>("release-0");
 const alive=useRef(true),request=useRef<AbortController|null>(null);
 useEffect(()=>{alive.current=true;return()=>{alive.current=false;request.current?.abort()}},[]);
 async function load(refresh=false){
  if(request.current)return;const controller=new AbortController();request.current=controller;setBusy(true);setError(false);
  const timer=setTimeout(()=>controller.abort(),10000);
  try{const result=await api<Result>(`/settings/changelog${refresh?"?refresh=true":""}`,{signal:controller.signal,cache:"no-store"});if(alive.current)setData(previous=>!result.content&&previous?.content?{...result,content:previous.content,checked_at:previous.checked_at,stale:true}:result)}
  catch{if(alive.current)setError(true)}
  finally{clearTimeout(timer);if(request.current===controller)request.current=null;if(alive.current)setBusy(false)}
 }
 useEffect(()=>{if(open)void load()},[open]);
 const sections=changelogSections(data?.content??""),checked=data?.checked_at?new Date(data.checked_at):null;
 const unavailable=error||data?.stale||data?.status==="unavailable";
 return <details className="card about-changelog" open={open} onToggle={event=>setOpen(event.currentTarget.open)}>
  <summary><span><strong>Changelog</strong><small>{bi(lang,"Was ist neu in PenguCoach?","What's new in PenguCoach?")}</small></span></summary>
  {open&&<div className="changelog-body"><div className="changelog-toolbar"><p className="muted">{bi(lang,"Änderungen direkt aus GitHub. Der Stand kann neuer sein als deine installierte Version.","Changes directly from GitHub. These may be newer than your installed version.")}</p><div className="form-actions"><button className="ghost compact" type="button" disabled={busy} onClick={()=>void load(true)}>{busy?bi(lang,"Wird geladen…","Loading…"):bi(lang,"Changelog neu laden","Reload changelog")}</button><a className="text-link" href={CHANGELOG_SOURCE} target="_blank" rel="noopener noreferrer">{bi(lang,"Auf GitHub öffnen","Open on GitHub")} ↗</a></div></div>
   {unavailable&&<p className="changelog-status" role="status">{sections.length?bi(lang,"Der aktuelle Stand ist momentan nicht abrufbar. Der zuletzt geladene Changelog bleibt sichtbar.","The current changelog is unavailable. Showing the last loaded version."):bi(lang,"Der Changelog konnte nicht geladen werden. Versuche es erneut oder öffne ihn auf GitHub.","The changelog could not be loaded. Try again or open it on GitHub.")}</p>}
   {busy&&!sections.length&&<p className="changelog-status" role="status">{bi(lang,"Änderungen werden von GitHub geladen…","Loading changes from GitHub…")}</p>}
   {sections.slice(0,visible).map(section=><section className="changelog-release" key={section.id}><button className="ghost changelog-release-toggle" type="button" aria-expanded={expanded===section.id} aria-controls={`changelog-${section.id}`} onClick={()=>setExpanded(value=>value===section.id?null:section.id)}><strong>{inline(section.title)}</strong><span>{section.version===installedVersion?.replace(/^v/,"")&&<small className="changelog-installed">{bi(lang,"Installiert","Installed")}</small>}</span></button>{expanded===section.id&&<div id={`changelog-${section.id}`}><Notes content={section.content}/></div>}</section>)}
   {!busy&&!unavailable&&data&&!sections.length&&<p role="status">{bi(lang,"Noch keine Einträge vorhanden.","No entries yet.")}</p>}
   {visible<sections.length&&<button type="button" className="ghost compact changelog-older" onClick={()=>setVisible(value=>value+6)}>{bi(lang,"Ältere Versionen anzeigen","Show older versions")} ({sections.length-visible})</button>}
   {checked&&!Number.isNaN(checked.getTime())&&<small className="changelog-checked">{bi(lang,"Zuletzt erfolgreich geladen","Last successfully loaded")}: {checked.toLocaleString(lang==="de"?"de-DE":"en-GB")}</small>}
  </div>}
 </details>;
}
