"use client";

import {useEffect,useMemo,useState} from "react";
import AppShell from "../../components/AppShell";
import SparkLine from "../../components/SparkLine";
import {api} from "../../lib/api";
import {bi,useI18n} from "../../lib/i18n";

type H={available:boolean;steps?:number;resting_hr?:number;stress_avg?:number;body_battery_high?:number;hydration_ml?:number;hydration_goal_ml?:number;training_readiness?:number;vo2max_running?:number;sleep?:{duration_seconds?:number;score?:number};hrv?:{overnight_average?:number;status?:string}};
type A={id:string;name?:string;sport_type?:string;distance_m?:number;duration_seconds?:number;avg_hr?:number;started_at?:string};
const dur=(s?:number)=>s?`${Math.floor(s/3600)}h ${Math.round((s%3600)/60)}m`:"—";
const sportGlyph=(s?:string)=>{const v=(s||"").toLowerCase();if(v.includes("run"))return "RUN";if(v.includes("bike")||v.includes("cycling"))return "BIKE";if(v.includes("swim"))return "SWIM";if(v.includes("strength")||v.includes("weight"))return "GYM";return "MOVE"};

export default function Today(){
  const{lang}=useI18n();
  const[h,setH]=useState<H|null>(null),[acts,setActs]=useState<A[]>([]),[trend,setTrend]=useState<any[]>([]);
  useEffect(()=>{api<H>("/health/today").then(setH);api<A[]>("/activities?limit=4").then(setActs);api<any>("/health/range?days=14").then(v=>setTrend(v.health??[]))},[]);
  const date=useMemo(()=>new Intl.DateTimeFormat(lang==="de"?"de-DE":"en-US",{weekday:"long",day:"2-digit",month:"long"}).format(new Date()),[lang]);
  const sleepHours=h?.sleep?.duration_seconds?h.sleep.duration_seconds/3600:null;
  const cards=[
    {label:bi(lang,"Schlaf","Sleep"),value:h?.sleep?.score?`${h.sleep.score}`:sleepHours?`${sleepHours.toFixed(1)} h`:"—",note:h?.sleep?.score?`${sleepHours?sleepHours.toFixed(1):"—"} h · Score`:bi(lang,"Letzte Nacht","Last night"),tone:"sleep"},
    {label:"HRV",value:h?.hrv?.overnight_average?`${h.hrv.overnight_average} ms`:"—",note:h?.hrv?.status??"Garmin",tone:"hrv"},
    {label:bi(lang,"Ruhepuls","Resting HR"),value:h?.resting_hr?`${h.resting_hr} bpm`:"—",note:bi(lang,"Tageswert","Daily value"),tone:"heart"},
    {label:"Body Battery",value:h?.body_battery_high??"—",note:bi(lang,"Höchstwert heute","High today"),tone:"battery"},
    {label:"Stress",value:h?.stress_avg??"—",note:bi(lang,"Durchschnitt","Average"),tone:"stress"},
    {label:bi(lang,"Hydration","Hydration"),value:h?.hydration_ml?`${(h.hydration_ml/1000).toFixed(1)} L`:"—",note:h?.hydration_goal_ml?`${bi(lang,"Ziel","Goal")} ${(h.hydration_goal_ml/1000).toFixed(1)} L`:"Garmin",tone:"water"},
    {label:bi(lang,"Bereitschaft","Readiness"),value:h?.training_readiness??"—",note:bi(lang,"Training Readiness","Training readiness"),tone:"ready"},
    {label:"VO₂max",value:h?.vo2max_running??"—",note:bi(lang,"Laufen","Running"),tone:"vo2"}
  ];
  return <AppShell>
    <section className="dashboard-hero">
      <div className="dashboard-hero-copy">
        <span className="eyebrow">{date}</span>
        <h1>{bi(lang,"Dein Gesundheits- und Trainingsüberblick","Your health & training overview")}</h1>
        <p>{bi(lang,"Garmin, FIT-Analysen und dein AI Coach – ruhig, verständlich und an einem Ort.","Garmin, FIT analytics and your AI Coach — calm, clear and in one place.")}</p>
        <div className="hero-actions"><a className="primary-link" href="/coach">✦ {bi(lang,"Coach fragen","Ask Coach")}</a><a className="soft-link" href="/activities">{bi(lang,"Aktivitäten öffnen","Open activities")} →</a></div>
      </div>
      <div className="dashboard-hero-art">
        <img src="/dashboard-wellness.svg" alt=""/>
        <div className="wellness-panel floating">
          <div className="wellness-ring"><span>{h?.training_readiness??h?.body_battery_high??"—"}</span><small>{h?.training_readiness?bi(lang,"Bereitschaft","Readiness"):"Body Battery"}</small></div>
          <div className="wellness-copy"><span className="metric-label">{bi(lang,"Heute im Fokus","Today at a glance")}</span><strong>{h?.available!==false?bi(lang,"Daten sind synchronisiert","Health data synced"):bi(lang,"Warte auf Garmin-Daten","Waiting for Garmin data")}</strong><small>{bi(lang,"Tippe auf Gesundheit für den langfristigen Verlauf.","Open Health for longer-term trends.")}</small></div>
        </div>
      </div>
    </section>

    <section className="health-metric-grid">{cards.map(c=><div className={`health-metric-card tone-${c.tone}`} key={c.label}><div className="health-metric-top"><span className="health-metric-dot"/><span className="metric-label">{c.label}</span></div><div className="metric-value">{String(c.value)}</div><div className="kpi-note">{c.note}</div></div>)}</section>

    <section className="dashboard-main-grid">
      <div className="card trend-card"><div className="section-heading"><div><span className="eyebrow">{bi(lang,"Trend","Trend")}</span><h2>{bi(lang,"Ruhepuls · 14 Tage","Resting HR · 14 days")}</h2></div><a className="text-link" href="/health">{bi(lang,"Gesundheit","Health")} →</a></div><div className="trend-visual"><SparkLine values={trend.map(x=>x.resting_hr)}/></div><div className="trend-footer"><span><i className="legend-dot"/>{bi(lang,"Garmin Ruhepuls","Garmin resting HR")}</span><small>{bi(lang,"Mehr Metriken und Zeiträume in Gesundheit","More metrics and periods in Health")}</small></div></div>

      <div className="card recent-card"><div className="section-heading"><div><span className="eyebrow">{bi(lang,"Training","Training")}</span><h2>{bi(lang,"Letzte Aktivitäten","Recent activities")}</h2></div><a className="text-link" href="/activities">{bi(lang,"Alle","All")} →</a></div>{acts.length?<div className="recent-list">{acts.map(a=><a className="recent-activity" key={a.id} href={`/activities/${a.id}`}><span className="sport-badge">{sportGlyph(a.sport_type)}</span><span className="recent-main"><strong>{a.name??a.sport_type??"Activity"}</strong><small>{a.started_at?new Date(a.started_at).toLocaleDateString(lang==="de"?"de-DE":"en-US",{day:"2-digit",month:"short"}):""}</small></span><span className="recent-stat">{a.distance_m?`${(a.distance_m/1000).toFixed(1)} km`:dur(a.duration_seconds)}</span><span className="recent-arrow">→</span></a>)}</div>:<div className="empty-state"><strong>{bi(lang,"Noch keine Aktivitäten","No activities yet")}</strong><span>{bi(lang,"Synchronisiere Garmin, um hier deine letzten Einheiten zu sehen.","Sync Garmin to see your latest sessions here.")}</span></div>}</div>
    </section>
  </AppShell>
}
