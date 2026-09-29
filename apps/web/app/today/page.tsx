"use client";

import {useEffect,useMemo,useState} from "react";
import {sourceLabel,measuredLabel} from "../../lib/sources";
import DailyCompanion from "../../components/DailyCompanion";
import SourceOverview from "../../components/SourceOverview";
import AppShell from "../../components/AppShell";
import SparkLine from "../../components/SparkLine";
import {api} from "../../lib/api";
import {bi,useI18n} from "../../lib/i18n";

type Body={weight_kg?:number;height_cm?:number;bmi?:number;body_fat_percent?:number;body_water_percent?:number;muscle_mass_kg?:number;bone_mass_kg?:number;sources?:Record<string,string>;measured_at_by_metric?:Record<string,string>};
type H={available:boolean;steps?:number;resting_hr?:number;stress_avg?:number;body_battery_high?:number;hydration_ml?:number;hydration_goal_ml?:number;training_readiness?:number;vo2max_running?:number;vo2max_cycling?:number;sources?:Record<string,string>;body?:Body;sleep?:{duration_seconds?:number;score?:number;source?:string};hrv?:{overnight_average?:number;status?:string;source?:string}};
type A={id:string;name?:string;sport_type?:string;distance_m?:number;duration_seconds?:number;avg_hr?:number;started_at?:string};
const dur=(s?:number)=>s?`${Math.floor(s/3600)}h ${Math.round((s%3600)/60)}m`:"—";
const sportGlyph=(s?:string)=>{const v=(s||"").toLowerCase();if(v.includes("run"))return "RUN";if(v.includes("bike")||v.includes("cycling"))return "BIKE";if(v.includes("swim"))return "SWIM";if(v.includes("strength")||v.includes("weight"))return "GYM";return "MOVE"};

export default function Today(){
  const{lang}=useI18n();
  const[h,setH]=useState<H|null>(null),[acts,setActs]=useState<A[]>([]),[trend,setTrend]=useState<any[]>([]),[load,setLoad]=useState<any|null>(null);
  useEffect(()=>{api<H>("/health/today").then(setH);api<A[]>("/activities?limit=4").then(setActs);api<any>("/health/range?days=14").then(v=>setTrend(v.health??[]));api<any>("/coach/training-load").then(setLoad).catch(()=>setLoad(null))},[]);
  const date=useMemo(()=>new Intl.DateTimeFormat(lang==="de"?"de-DE":"en-US",{weekday:"long",day:"2-digit",month:"long"}).format(new Date()),[lang]);
  const sleepHours=h?.sleep?.duration_seconds?h.sleep.duration_seconds/3600:null;
  const metricSource=(field:string)=>sourceLabel(h?.sources?.[field],lang);
  const bodySource=(field:string)=>[sourceLabel(h?.body?.sources?.[field],lang),measuredLabel(h?.body?.measured_at_by_metric?.[field],lang)].filter(Boolean).join(" · ");
  const askPrompt=lang==="de"?"Was passt heute zu mir? Nutze meine ausgewählten Daten, meine Readiness und meinen aktuellen Check-in. Antworte kurz mit einer konkreten Empfehlung für heute.":"What suits me today? Use my selected data, readiness and current check-in. Give a short concrete recommendation for today.";
  const focusItems=[
    {label:bi(lang,"Schritte","Steps"),value:h?.steps!=null?h.steps.toLocaleString(lang==="de"?"de-DE":"en-US"):"—",note:bi(lang,"heute","today")},
    {label:bi(lang,"Schlaf","Sleep"),value:sleepHours!=null?`${sleepHours.toFixed(1)} h`:"—",note:h?.sleep?.score!=null?`${bi(lang,"Score","Score")} ${h.sleep.score}`:bi(lang,"letzte Nacht","last night")},
    {label:bi(lang,"Ruhepuls","Resting HR"),value:h?.resting_hr!=null?`${h.resting_hr}`:"—",note:h?.resting_hr!=null?"bpm":bi(lang,"keine Daten","no data")}
  ];
  const cards=[
    {label:bi(lang,"Schlaf","Sleep"),value:h?.sleep?.score?`${h.sleep.score}`:sleepHours?`${sleepHours.toFixed(1)} h`:"—",note:h?.sleep?`${sourceLabel(h.sleep.source,lang)}${h.sleep.score&&sleepHours?` · ${sleepHours.toFixed(1)} h` : ""}`:bi(lang,"Keine Daten","No data"),tone:"sleep"},
    {label:"HRV",value:h?.hrv?.overnight_average?`${h.hrv.overnight_average} ms`:"—",note:h?.hrv?`${sourceLabel(h.hrv.source,lang)}${h.hrv.status?` · ${h.hrv.status}`:""}`:bi(lang,"Keine Daten","No data"),tone:"hrv"},
    {label:bi(lang,"Ruhepuls","Resting HR"),value:h?.resting_hr?`${h.resting_hr} bpm`:"—",note:h?.resting_hr?metricSource("resting_hr"):bi(lang,"Keine Daten","No data"),tone:"heart"},
    {label:bi(lang,"Schritte","Steps"),value:h?.steps!=null?h.steps.toLocaleString(lang==="de"?"de-DE":"en-US"):"—",note:h?.steps!=null?metricSource("steps"):bi(lang,"Heute","Today"),tone:"steps"},
    {label:bi(lang,"Body Battery · Tageshoch","Body Battery · daily high"),value:h?.body_battery_high??"—",note:h?.body_battery_high!=null?metricSource("body_battery_high"):bi(lang,"Keine Daten","No data"),tone:"battery"},
    {label:"Stress",value:h?.stress_avg??"—",note:h?.stress_avg!=null?metricSource("stress_avg"):bi(lang,"Keine Daten","No data"),tone:"stress"},
    {label:bi(lang,"Hydration","Hydration"),value:h?.hydration_ml!=null?`${(h.hydration_ml/1000).toFixed(1)} L`:"—",note:h?.hydration_ml!=null?`${metricSource("hydration_ml")}${h?.hydration_goal_ml?` · ${bi(lang,"Ziel","Goal")} ${(h.hydration_goal_ml/1000).toFixed(1)} L`:""}`:bi(lang,"Keine Daten","No data"),tone:"water"},
    {label:bi(lang,"Bereitschaft","Readiness"),value:h?.training_readiness??"—",note:h?.training_readiness!=null?metricSource("training_readiness"):bi(lang,"Keine Daten","No data"),tone:"ready"},
    {label:bi(lang,"Gewicht","Weight"),value:h?.body?.weight_kg!=null?`${h.body.weight_kg.toFixed(1)} kg`:"—",note:h?.body?.weight_kg!=null?bodySource("weight_kg"):bi(lang,"Letzte Messung","Latest measurement"),tone:"body"},
    {label:bi(lang,"Körperfett","Body fat"),value:h?.body?.body_fat_percent!=null?`${h.body.body_fat_percent.toFixed(1)} %`:"—",note:h?.body?.body_fat_percent!=null?bodySource("body_fat_percent"):bi(lang,"Letzte Messung","Latest measurement"),tone:"body"}
  ];
  const rhrSources=Array.from(new Set(trend.map(x=>x?.sources?.resting_hr).filter(Boolean))).map(x=>sourceLabel(x,lang)).join(" + ")||bi(lang,"Quelle unbekannt","Source unknown");

  return <AppShell>
    <SourceOverview/>
    <section className="dashboard-hero today-hero">
      <div className="dashboard-hero-copy">
        <span className="eyebrow">{date}</span>
        <h1>{bi(lang,"Dein Tag. Deine Balance.","Your day. Your balance.")}</h1>
        <p>{bi(lang,"Heute zählt vor allem, wie es dir geht und was realistisch zu deinem Tag passt. PenguCoach bündelt Readiness, Bewegung und deinen kurzen Check-in an einem Ort.","What matters today is how you feel and what realistically fits your day. PenguCoach brings together readiness, movement and your short check-in in one place.")}</p>
        <div className="hero-actions hero-actions-priority">
          <a className="primary-link" href={`/coach?prompt=${encodeURIComponent(askPrompt)}`}>✦ {bi(lang,"Was passt heute zu mir?","What suits me today?")}</a>
          <a className="soft-link" href="/coach">{bi(lang,"Coach frei fragen","Ask Coach freely")} →</a>
          <a className="text-link" href="/activities">{bi(lang,"Aktivitäten öffnen","Open activities")} →</a>
        </div>
      </div>
      <div className="today-focus-card today-focus-card-hero">
          <div className="today-focus-head">
            <div>
              <span className="metric-label">{bi(lang,"Heute im Fokus","Today in focus")}</span>
              <strong>{h?.available===true?bi(lang,"Tagesdaten bereit","Daily data ready"):bi(lang,"Synchronisierung läuft","Sync in progress")}</strong>
            </div>
            <span className={`sync-pill ${h?.available===true?"ok":"pending"}`}>{h?.available===true?bi(lang,"Synchronisiert","Synced"):bi(lang,"Wird geladen","Loading")}</span>
          </div>
          <div className="today-focus-list">{focusItems.map(item=><div className="today-focus-item" key={item.label}><span>{item.label}</span><strong>{item.value}</strong><small>{item.note}</small></div>)}</div>
          <a className="text-link" href="/health">{bi(lang,"Gesundheit öffnen","Open health")} →</a>
      </div>
    </section>

    <DailyCompanion/>
    {load&&<section className={`card today-load-card load-${load.status||"unknown"}`}><div><span className="eyebrow">TRAINING LOAD</span><h2>{load.trend==="strongly_rising"?bi(lang,"Belastung steigt stark","Load rising strongly"):load.trend==="rising"?bi(lang,"Belastung steigt leicht","Load rising slightly"):load.trend==="falling"?bi(lang,"Belastung sinkt","Load falling"):bi(lang,"Belastung stabil","Load stable")}</h2><p className="muted">{load.basis==="garmin_training_load"?bi(lang,"Garmin Training Load · 7 Tage gegenüber deinem 28-Tage-Wochenmittel","Garmin Training Load · 7 days versus your 28-day weekly average"):bi(lang,"Trainingsminuten · 7 Tage gegenüber deinem 28-Tage-Wochenmittel","Training minutes · 7 days versus your 28-day weekly average")}</p></div><div className="today-load-metrics"><span><small>{bi(lang,"7 Tage","7 days")}</small><strong>{load.acute_7d}</strong></span><span><small>{bi(lang,"28-Tage-Mittel","28d average")}</small><strong>{load.chronic_28d_weekly}</strong></span><span><small>{bi(lang,"Volumen","Volume")}</small><strong>{load.minutes_7d} min</strong></span></div>{Array.isArray(load.sport_mix)&&load.sport_mix.length>0&&<div className="today-sport-mix">{load.sport_mix.slice(0,4).map((x:any)=><span key={x.sport}>{x.sport} <b>{x.percent}%</b></span>)}</div>}</section>}
    <section className="health-metric-grid">{cards.filter(c=>!["battery","ready"].includes(c.tone)||c.value!=="—").map(c=><div className={`health-metric-card tone-${c.tone}`} key={c.label}><div className="health-metric-top"><span className="health-metric-dot"/><span className="metric-label">{c.label}</span></div><div className="metric-value">{String(c.value)}</div><div className="kpi-note">{c.note}</div></div>)}<div className="health-metric-card tone-vo2 vo2-dual-card"><div className="health-metric-top"><span className="health-metric-dot"/><span className="metric-label">VO₂max</span></div><div className="vo2-dual-values"><div><small>{bi(lang,"Laufen","Running")}</small><strong>{h?.vo2max_running??"—"}</strong></div><div><small>{bi(lang,"Rad","Cycling")}</small><strong>{h?.vo2max_cycling??"—"}</strong></div></div><div className="kpi-note">ml/kg/min · {Array.from(new Set([h?.sources?.vo2max_running,h?.sources?.vo2max_cycling].filter(Boolean))).map(s=>sourceLabel(s,lang)).join(" + ")||"—"}</div></div></section>

    <section className="dashboard-main-grid">
      <div className="card trend-card"><div className="section-heading"><div><span className="eyebrow">{bi(lang,"Trend","Trend")}</span><h2>{bi(lang,"Ruhepuls · 14 Tage","Resting HR · 14 days")}</h2></div><a className="text-link" href="/health">{bi(lang,"Gesundheit","Health")} →</a></div><div className="trend-visual"><SparkLine values={trend.map(x=>x.resting_hr)}/></div><div className="trend-footer"><span><i className="legend-dot"/>{rhrSources}</span><small>{bi(lang,"Mehr Metriken und Zeiträume in Gesundheit","More metrics and periods in Health")}</small></div></div>

      <div className="card recent-card"><div className="section-heading"><div><span className="eyebrow">{bi(lang,"Training","Training")}</span><h2>{bi(lang,"Letzte Aktivitäten","Recent activities")}</h2></div><a className="text-link" href="/activities">{bi(lang,"Alle","All")} →</a></div>{acts.length?<div className="recent-list">{acts.map(a=><a className="recent-activity" key={a.id} href={`/activities/${a.id}`}><span className="sport-badge">{sportGlyph(a.sport_type)}</span><span className="recent-main"><strong>{a.name??a.sport_type??"Activity"}</strong><small>{a.started_at?new Date(a.started_at).toLocaleDateString(lang==="de"?"de-DE":"en-US",{day:"2-digit",month:"short"}):""}</small></span><span className="recent-stat">{a.distance_m?`${(a.distance_m/1000).toFixed(1)} km`:dur(a.duration_seconds)}</span><span className="recent-arrow">→</span></a>)}</div>:<div className="empty-state"><strong>{bi(lang,"Noch keine Aktivitäten","No activities yet")}</strong><span>{bi(lang,"Synchronisiere Garmin oder SparkyFitness, um hier deine letzten Einheiten zu sehen.","Sync Garmin or SparkyFitness to see your latest sessions here.")}</span></div>}</div>
    </section>
  </AppShell>
}
