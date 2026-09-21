"use client";

import {useEffect,useMemo,useState} from "react";
import AppShell from "../../components/AppShell";
import {api} from "../../lib/api";
import {bi,useI18n} from "../../lib/i18n";

type A={id:string;name?:string;sport_type?:string;started_at?:string;distance_m?:number;duration_seconds?:number;avg_hr?:number;training_load?:number;fit_status:string};
const duration=(s?:number)=>s?`${Math.floor(s/3600)}:${String(Math.floor((s%3600)/60)).padStart(2,"0")}:${String(Math.floor(s%60)).padStart(2,"0")}`:"—";
const sportInfo=(s?:string)=>{const v=(s||"").toLowerCase();if(v.includes("run"))return{icon:"RUN",label:"Running",tone:"run"};if(v.includes("bike")||v.includes("cycling"))return{icon:"BIKE",label:"Cycling",tone:"bike"};if(v.includes("swim"))return{icon:"SWIM",label:"Swimming",tone:"swim"};if(v.includes("strength")||v.includes("weight"))return{icon:"GYM",label:"Strength",tone:"strength"};return{icon:"MOVE",label:s||"Activity",tone:"other"}};

export default function Activities(){
  const{lang}=useI18n();const[rows,setRows]=useState<A[]>([]);const[query,setQuery]=useState("");
  useEffect(()=>{api<A[]>("/activities?limit=200").then(setRows)},[]);
  const filtered=useMemo(()=>{const q=query.trim().toLowerCase();if(!q)return rows;return rows.filter(a=>`${a.name||""} ${a.sport_type||""}`.toLowerCase().includes(q))},[rows,query]);
  return <AppShell>
    <section className="page-head-modern activities-head"><div><span className="eyebrow">{bi(lang,"Trainingstagebuch","Training log")}</span><h1>{bi(lang,"Aktivitäten","Activities")}</h1><p>{bi(lang,"Garmin-Gesamtwerte, FIT-Zeitreihen und PenguCoach-Analysen in einer verständlichen Historie.","Garmin summaries, FIT time series and PenguCoach analytics in one clear history.")}</p></div><div className="activity-search"><span>⌕</span><input value={query} onChange={e=>setQuery(e.target.value)} placeholder={bi(lang,"Aktivitäten durchsuchen…","Search activities…")}/></div></section>

    <section className="activity-summary-strip"><div><span>{bi(lang,"Aktivitäten","Activities")}</span><strong>{rows.length}</strong></div><div><span>{bi(lang,"Gefiltert","Filtered")}</span><strong>{filtered.length}</strong></div><div><span>{bi(lang,"FIT analysiert","FIT analysed")}</span><strong>{rows.filter(x=>x.fit_status==="parsed").length}</strong></div></section>

    <section className="card activity-list-card">{filtered.length?<div className="modern-activity-list">{filtered.map(a=>{const s=sportInfo(a.sport_type);return <a className="modern-activity-row" href={`/activities/${a.id}`} key={a.id}><span className={`activity-sport-icon tone-${s.tone}`}>{s.icon}</span><span className="activity-row-main"><strong>{a.name??a.sport_type??"Activity"}</strong><small>{a.started_at?new Date(a.started_at).toLocaleString(lang==="de"?"de-DE":"en-US",{day:"2-digit",month:"short",year:"numeric",hour:"2-digit",minute:"2-digit"}):""} · {s.label}</small></span><span className="activity-row-stat"><small>{bi(lang,"Distanz","Distance")}</small><strong>{a.distance_m?`${(a.distance_m/1000).toFixed(2)} km`:"—"}</strong></span><span className="activity-row-stat"><small>{bi(lang,"Dauer","Duration")}</small><strong>{duration(a.duration_seconds)}</strong></span><span className="activity-row-stat"><small>Ø HR</small><strong>{a.avg_hr?`${Math.round(a.avg_hr)} bpm`:"—"}</strong></span><span className={`fit-status ${a.fit_status}`}>FIT {a.fit_status}</span><span className="activity-row-arrow">→</span></a>})}</div>:<div className="empty-state"><strong>{bi(lang,"Keine passenden Aktivitäten","No matching activities")}</strong><span>{query?bi(lang,"Passe die Suche an oder lösche den Suchbegriff.","Adjust or clear your search."):bi(lang,"Synchronisiere Garmin, um deine Trainingshistorie zu füllen.","Sync Garmin to build your training history.")}</span></div>}</section>
  </AppShell>
}
