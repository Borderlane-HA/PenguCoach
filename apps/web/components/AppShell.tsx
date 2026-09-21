"use client";

import {useEffect,useMemo,useState} from "react";
import {usePathname} from "next/navigation";
import {api} from "../lib/api";
import {bi,useI18n} from "../lib/i18n";

type Me={username:string;role:string;locale:string;safety_required:boolean};
type Appearance={theme:string;has_avatar:boolean;has_app_icon:boolean;avatar_version?:number;app_icon_version?:number};
type IconName="today"|"health"|"activities"|"training"|"coach"|"garmin"|"privacy"|"appearance"|"ai"|"users"|"logout";

function Icon({name}:{name:IconName}){
  const common={width:20,height:20,viewBox:"0 0 24 24",fill:"none",stroke:"currentColor",strokeWidth:1.8,strokeLinecap:"round" as const,strokeLinejoin:"round" as const,"aria-hidden":true};
  if(name==="today")return <svg {...common}><rect x="4" y="4" width="16" height="16" rx="4"/><path d="M8 9h8M8 13h3M14 13h2M8 17h5"/></svg>;
  if(name==="health")return <svg {...common}><path d="M20.8 5.8a5 5 0 0 0-7.1 0L12 7.5l-1.7-1.7a5 5 0 1 0-7.1 7.1L12 21l8.8-8.1a5 5 0 0 0 0-7.1Z"/><path d="M7 12h2l1-2 2 5 1.5-3H17"/></svg>;
  if(name==="activities")return <svg {...common}><path d="M4 13h3l2-5 3 10 2-6h6"/><path d="M4 5v14"/></svg>;
  if(name==="training")return <svg {...common}><path d="M6 7v10M18 7v10M3 10v4M21 10v4M6 12h12"/></svg>;
  if(name==="coach")return <svg {...common}><path d="m12 3 1.2 3.4L16.5 8l-3.3 1.6L12 13l-1.2-3.4L7.5 8l3.3-1.6L12 3Z"/><path d="m18.5 13 .8 2.2 2.2.8-2.2.8-.8 2.2-.8-2.2-2.2-.8 2.2-.8.8-2.2ZM5.5 14l.7 1.8 1.8.7-1.8.7-.7 1.8-.7-1.8-1.8-.7 1.8-.7.7-1.8Z"/></svg>;
  if(name==="garmin")return <svg {...common}><rect x="7" y="4" width="10" height="16" rx="3"/><path d="M9 1h6M9 23h6M10 9l2-2 2 2M10 14h4"/></svg>;
  if(name==="privacy")return <svg {...common}><path d="M12 3 5 6v5c0 4.7 2.7 8.1 7 10 4.3-1.9 7-5.3 7-10V6l-7-3Z"/><path d="m9.5 12 1.6 1.6 3.4-3.6"/></svg>;
  if(name==="appearance")return <svg {...common}><circle cx="12" cy="12" r="9"/><path d="M12 3v18M3 12h18M6.2 6.2l11.6 11.6M17.8 6.2 6.2 17.8"/></svg>;
  if(name==="ai")return <svg {...common}><rect x="6" y="6" width="12" height="12" rx="3"/><path d="M9 10h6M9 14h4M9 2v4M15 2v4M9 18v4M15 18v4M2 9h4M18 9h4M2 15h4M18 15h4"/></svg>;
  if(name==="logout")return <svg {...common}><path d="M10 5H6a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h4"/><path d="m15 16 4-4-4-4M19 12H9"/></svg>;
  return <svg {...common}><path d="M16 20v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 20v-2a4 4 0 0 0-3-3.9M16 3.1a4 4 0 0 1 0 7.8"/></svg>;
}

export default function AppShell({children,title}:{children:React.ReactNode;title?:string}){
  const{lang,setLang}=useI18n();
  const pathname=usePathname();
  const[me,setMe]=useState<Me|null>(null),[appearance,setAppearance]=useState<Appearance|null>(null),[loggingOut,setLoggingOut]=useState(false);

  const loadAppearance=()=>api<Appearance>("/settings/appearance").then(v=>{setAppearance(v);document.documentElement.dataset.theme=v.theme||"light"}).catch(()=>{document.documentElement.dataset.theme="light"});
  useEffect(()=>{api<Me>("/auth/me").then(v=>{if(v.safety_required)location.replace("/safety");else{setMe(v);void loadAppearance()}}).catch(()=>location.replace("/"));const handler=()=>void loadAppearance();window.addEventListener("pengucoach-appearance-changed",handler);return()=>window.removeEventListener("pengucoach-appearance-changed",handler)},[]);

  const nav=useMemo(()=>[
    {href:"/today",icon:"today" as IconName,label:bi(lang,"Heute","Today")},
    {href:"/health",icon:"health" as IconName,label:bi(lang,"Gesundheit","Health")},
    {href:"/activities",icon:"activities" as IconName,label:bi(lang,"Aktivitäten","Activities")},
    {href:"/training",icon:"training" as IconName,label:bi(lang,"Training","Training")},
    {href:"/coach",icon:"coach" as IconName,label:bi(lang,"AI Coach","AI Coach")},
  ],[lang]);
  const settings=useMemo(()=>[
    {href:"/settings/garmin",icon:"garmin" as IconName,label:"Garmin"},
    {href:"/settings/appearance",icon:"appearance" as IconName,label:bi(lang,"Darstellung","Appearance")},
    {href:"/settings/privacy",icon:"privacy" as IconName,label:bi(lang,"Datenschutz","Privacy")},
  ],[lang]);
  const admin=useMemo(()=>[
    {href:"/admin/ai",icon:"ai" as IconName,label:"AI Studio"},
    {href:"/admin/users",icon:"users" as IconName,label:bi(lang,"Benutzer","Users")},
  ],[lang]);
  const active=(href:string)=>pathname===href||pathname.startsWith(`${href}/`);
  const current=[...nav,...settings,...admin].find(x=>active(x.href));
  const initials=(me?.username||"PC").slice(0,2).toUpperCase();
  const avatar=appearance?.has_avatar?`/api/v1/settings/avatar?v=${appearance.avatar_version??0}`:null;
  const appIcon=appearance?.has_app_icon?`/api/v1/settings/app-icon?v=${appearance.app_icon_version??0}`:"/pengucoach-icon.svg";

  async function logout(){
    if(loggingOut)return;
    setLoggingOut(true);
    try{await api("/auth/logout",{method:"POST"})}catch{}
    finally{
      for(let i=localStorage.length-1;i>=0;i--){
        const key=localStorage.key(i);
        if(key?.startsWith("pengucoach_")&&key!=="pengucoach_lang")localStorage.removeItem(key);
      }
      location.replace("/");
    }
  }

  if(!me)return <main className="auth-loading"><div className="loading-mark"><img src="/pengucoach-icon.svg" alt=""/></div><p>{bi(lang,"PenguCoach wird geladen…","Loading PenguCoach…")}</p></main>;

  return <div className="app-frame">
    <aside className="side-nav" aria-label={bi(lang,"Hauptnavigation","Main navigation")}>
      <a className="side-brand" href="/today"><span className="brand-mark custom"><img src={appIcon} alt=""/></span><span><strong>PenguCoach</strong><small>Training & Health</small></span></a>
      <div className="side-section"><div className="side-label">{bi(lang,"Übersicht","Overview")}</div>{nav.map(x=><a className={`side-link ${active(x.href)?"active":""}`} href={x.href} key={x.href}><Icon name={x.icon}/><span>{x.label}</span>{active(x.href)&&<i/>}</a>)}</div>
      <div className="side-section"><div className="side-label">{bi(lang,"Verbindungen & Einstellungen","Connections & settings")}</div>{settings.map(x=><a className={`side-link ${active(x.href)?"active":""}`} href={x.href} key={x.href}><Icon name={x.icon}/><span>{x.label}</span>{active(x.href)&&<i/>}</a>)}</div>
      {me.role==="admin"&&<div className="side-section"><div className="side-label">Admin</div>{admin.map(x=><a className={`side-link ${active(x.href)?"active":""}`} href={x.href} key={x.href}><Icon name={x.icon}/><span>{x.label}</span>{active(x.href)&&<i/>}</a>)}</div>}
      <div className="side-account">
        <a className="side-user" href="/settings/appearance"><span className={`side-avatar ${avatar?"photo":""}`}>{avatar?<img src={avatar} alt=""/>:initials}</span><span><strong>{me.username}</strong><small>{me.role}</small></span></a>
        <button className="side-logout" type="button" onClick={()=>void logout()} disabled={loggingOut} title={bi(lang,"Abmelden","Sign out")}><Icon name="logout"/><span>{loggingOut?bi(lang,"Abmelden…","Signing out…"):bi(lang,"Abmelden","Sign out")}</span></button>
      </div>
    </aside>

    <section className="app-main"><header className="topbar"><div className="top-context"><span className="top-kicker">PenguCoach</span><strong>{title??current?.label??bi(lang,"Übersicht","Overview")}</strong></div><div className="top-actions"><span className="health-live"><i/>{bi(lang,"System aktiv","System online")}</span><button className="language-switch" onClick={()=>setLang(lang==="de"?"en":"de")} aria-label={bi(lang,"Sprache wechseln","Change language")}>{lang==="de"?"DE":"EN"}<span>⌄</span></button><a className={`top-avatar ${avatar?"photo":""}`} href="/settings/appearance" title={me.username}>{avatar?<img src={avatar} alt=""/>:initials}</a><button className="top-logout" type="button" onClick={()=>void logout()} disabled={loggingOut} title={bi(lang,"Abmelden","Sign out")} aria-label={bi(lang,"Abmelden","Sign out")}><Icon name="logout"/></button></div></header><main className="stack page">{title&&<div className="page-title"><h1>{title}</h1></div>}{children}</main></section>

    <nav className="mobile-dock" aria-label={bi(lang,"Mobile Navigation","Mobile navigation")}>{nav.map(x=><a className={active(x.href)?"active":""} href={x.href} key={x.href}><Icon name={x.icon}/><span>{x.label}</span></a>)}</nav>
  </div>;
}
