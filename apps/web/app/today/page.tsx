"use client";
import {activityTimeLabel} from "../../lib/sources";

import {useEffect,useMemo,useRef,useState} from "react";
import {sourceLabel,measuredLabel} from "../../lib/sources";
import PersonalProgress from "../../components/PersonalProgress";
import TodayCustomization,{DEFAULT_TODAY} from "../../components/TodayCustomization";
import {DayPhases,TrainingPreparation,TodayWeather} from "../../components/TodayJourney";
import DailyCompanion from "../../components/DailyCompanion";
import SourceOverview from "../../components/SourceOverview";
import AppShell from "../../components/AppShell";
import SparkLine from "../../components/SparkLine";
import {useCachedQuery,invalidateDataCache} from "../../lib/data-cache";
import MetricCard from "../../components/MetricCard";
import StepGoalCard from "../../components/StepGoalCard";
import Deferred from "../../components/Deferred";
import Link from "next/link";
import {bi,useI18n} from "../../lib/i18n";

type Body={weight_kg?:number;height_cm?:number;bmi?:number;body_fat_percent?:number;body_water_percent?:number;muscle_mass_kg?:number;bone_mass_kg?:number;sources?:Record<string,string>;measured_at_by_metric?:Record<string,string>};
type H={available:boolean;step_goal?:any;steps?:number;resting_hr?:number;stress_avg?:number;body_battery_high?:number;hydration_ml?:number;hydration_goal_ml?:number;training_readiness?:number;vo2max_running?:number;vo2max_cycling?:number;sources?:Record<string,string>;body?:Body;sleep?:{duration_seconds?:number;score?:number;source?:string};hrv?:{overnight_average?:number;status?:string;source?:string}};
type A={id:string;name?:string;sport_type?:string;distance_m?:number;duration_seconds?:number;avg_hr?:number;started_at?:string};
const dur=(s?:number)=>s?`${Math.floor(s/3600)}h ${Math.round((s%3600)/60)}m`:"—";
const sportGlyph=(s?:string)=>{const v=(s||"").toLowerCase();if(v.includes("run"))return "RUN";if(v.includes("bike")||v.includes("cycling"))return "BIKE";if(v.includes("swim"))return "SWIM";if(v.includes("strength")||v.includes("weight"))return "GYM";return "MOVE"};

export default function Today(){
  const{lang}=useI18n();
  const[briefing,setBriefing]=useState<Record<string,any>|null>(null),[personalPreferences,setPreferences]=useState<Record<string,any>|null>(null),[phaseOverride,setPhaseOverride]=useState<string|null>(null);const lastDate=useRef<string|null>(null);
  const prefsQuery=useCachedQuery<Record<string,any>>("/settings/today",60000);
  const preferences=personalPreferences??{...DEFAULT_TODAY,...prefsQuery.data};
  const prefsLoaded=!!prefsQuery.data,prefsError=prefsQuery.error;
  const hQuery=useCachedQuery<H>("/health/today?include_vo2=false");
  const actsQuery=useCachedQuery<A[]>(prefsLoaded&&!preferences.hidden.includes("activities")?"/activities?limit=4&include_stats=false":null);
  const trendQuery=useCachedQuery<any>(prefsLoaded&&!preferences.hidden.includes("trend")?"/health/resting-hr?days=14":null);
  const loadQuery=useCachedQuery<any>(prefsLoaded&&!preferences.hidden.includes("load")?"/coach/training-load":null);
  const vo2Query=useCachedQuery<any>(prefsLoaded&&!preferences.hidden.includes("metrics")&&preferences.pinned_metrics.includes("vo2max")?"/health/vo2-history?days=180":null,120000);
  const h=hQuery.data?{...hQuery.data,vo2max_running:hQuery.data.vo2max_running??vo2Query.data?.latest?.running,vo2max_cycling:hQuery.data.vo2max_cycling??vo2Query.data?.latest?.cycling}:null;
  const acts=actsQuery.data??[],trend:any[]=trendQuery.data?.health??[],load=loadQuery.data;
  const refresh=()=>invalidateDataCache();
  useEffect(()=>{setPreferences(null)},[prefsQuery.data]);
  useEffect(()=>{if(briefing?.date){if(lastDate.current&&lastDate.current!==briefing.date)setPhaseOverride(null);lastDate.current=briefing.date}},[briefing?.date]);
  const phase=phaseOverride||briefing?.day_phase||"morning";
  const date=useMemo(()=>new Intl.DateTimeFormat(lang==="de"?"de-DE":"en-US",{weekday:"long",day:"2-digit",month:"long",...(briefing?.date?{timeZone:"UTC"}:{})}).format(briefing?.date?new Date(`${briefing.date}T12:00:00Z`):new Date()),[lang,briefing?.date]);
  const sleepHours=h?.sleep?.duration_seconds!=null?h.sleep.duration_seconds/3600:null;
  const metricSource=(field:string)=>sourceLabel(h?.sources?.[field],lang);
  const bodySource=(field:string)=>[sourceLabel(h?.body?.sources?.[field],lang),measuredLabel(h?.body?.measured_at_by_metric?.[field],lang)].filter(Boolean).join(" · ");

  const cards=[
    {label:bi(lang,"Schlaf","Sleep"),value:h?.sleep?.score!=null?`${h.sleep.score}`:sleepHours!=null?`${sleepHours.toFixed(1)} h`:"—",note:h?.sleep?`${sourceLabel(h.sleep.source,lang)}${h.sleep.score!=null&&sleepHours!=null?` · ${sleepHours.toFixed(1)} h` : ""}`:bi(lang,"Keine Daten","No data"),tone:"sleep",key:"sleep"},
    {label:"HRV",value:h?.hrv?.overnight_average!=null?`${h.hrv.overnight_average} ms`:"—",note:h?.hrv?`${sourceLabel(h.hrv.source,lang)}${h.hrv.status?` · ${h.hrv.status}`:""}`:bi(lang,"Keine Daten","No data"),tone:"hrv",key:"hrv"},
    {label:bi(lang,"Ruhepuls","Resting HR"),value:h?.resting_hr!=null?`${h.resting_hr} bpm`:"—",note:h?.resting_hr!=null?metricSource("resting_hr"):bi(lang,"Keine Daten","No data"),tone:"heart",key:"resting_hr"},
    {label:bi(lang,"Schritte","Steps"),value:h?.steps!=null?h.steps.toLocaleString(lang==="de"?"de-DE":"en-US"):"—",note:h?.steps!=null?metricSource("steps"):bi(lang,"Heute","Today"),tone:"steps",key:"steps"},
    {label:bi(lang,"Body Battery · Tageshoch","Body Battery · daily high"),value:h?.body_battery_high??"—",note:h?.body_battery_high!=null?metricSource("body_battery_high"):bi(lang,"Keine Daten","No data"),tone:"battery",key:"body_battery_high"},
    {label:"Stress",value:h?.stress_avg??"—",note:h?.stress_avg!=null?metricSource("stress_avg"):bi(lang,"Keine Daten","No data"),tone:"stress",key:"stress"},
    {label:bi(lang,"Hydration","Hydration"),value:h?.hydration_ml!=null?`${(h.hydration_ml/1000).toFixed(1)} L`:"—",note:h?.hydration_ml!=null?`${metricSource("hydration_ml")}${h?.hydration_goal_ml?` · ${bi(lang,"Ziel","Goal")} ${(h.hydration_goal_ml/1000).toFixed(1)} L`:""}`:bi(lang,"Keine Daten","No data"),tone:"water",key:"hydration"},
    {label:bi(lang,"Bereitschaft","Readiness"),value:h?.training_readiness??"—",note:h?.training_readiness!=null?metricSource("training_readiness"):bi(lang,"Keine Daten","No data"),tone:"ready",key:"training_readiness"},
    {label:bi(lang,"Gewicht","Weight"),value:h?.body?.weight_kg!=null?`${h.body.weight_kg.toFixed(1)} kg`:"—",note:h?.body?.weight_kg!=null?bodySource("weight_kg"):bi(lang,"Letzte Messung","Latest measurement"),tone:"body",key:"weight"},
    {label:bi(lang,"Körperfett","Body fat"),value:h?.body?.body_fat_percent!=null?`${h.body.body_fat_percent.toFixed(1)} %`:"—",note:h?.body?.body_fat_percent!=null?bodySource("body_fat_percent"):bi(lang,"Letzte Messung","Latest measurement"),tone:"body",key:"body_fat"}
  ];
  const rhrSources=Array.from(new Set(trend.map(x=>x?.sources?.resting_hr).filter(Boolean))).map(x=>sourceLabel(x,lang)).join(" + ")||bi(lang,"Quelle unbekannt","Source unknown");

  const cardsById:Record<string,React.ReactNode>={
    preparation:<TrainingPreparation data={briefing} phase={phase} lang={lang}/>,
    weather:briefing?.date?<Deferred label={bi(lang,"Wetter wird geladen","Loading weather")}><TodayWeather minutes={briefing?.checkin?.minutes??briefing?.upcoming?.find((s:any)=>s.date===briefing.date)?.duration_min??45} preferences={preferences} lang={lang}/></Deferred>:null,
    progress:<Deferred label={bi(lang,"Entwicklung wird geladen","Loading progress")}><PersonalProgress lang={lang}/></Deferred>,
    load:(load&&<section className={`card today-load-card load-${load.status||"unknown"}`}><div><span className="eyebrow">TRAINING LOAD</span><h2>{load.trend==="strongly_rising"?bi(lang,"Belastung steigt stark","Load rising strongly"):load.trend==="rising"?bi(lang,"Belastung steigt leicht","Load rising slightly"):load.trend==="falling"?bi(lang,"Belastung sinkt","Load falling"):bi(lang,"Belastung stabil","Load stable")}</h2><p className="muted">{load.basis==="garmin_training_load"?bi(lang,"Garmin Training Load · 7 Tage gegenüber deinem 28-Tage-Wochenmittel","Garmin Training Load · 7 days versus your 28-day weekly average"):bi(lang,"Trainingsminuten · 7 Tage gegenüber deinem 28-Tage-Wochenmittel","Training minutes · 7 days versus your 28-day weekly average")}</p></div><div className="today-load-metrics"><span><small>{bi(lang,"7 Tage","7 days")}</small><strong>{load.acute_7d}</strong></span><span><small>{bi(lang,"28-Tage-Mittel","28d average")}</small><strong>{load.chronic_28d_weekly}</strong></span><span><small>{bi(lang,"Volumen","Volume")}</small><strong>{load.minutes_7d} min</strong></span></div>{Array.isArray(load.sport_mix)&&load.sport_mix.length>0&&<div className="today-sport-mix">{load.sport_mix.slice(0,4).map((x:any)=><span key={x.sport}>{x.sport} <b>{x.percent}%</b></span>)}</div>}</section>),
    trend:(<div className="card trend-card"><div className="section-heading"><div><span className="eyebrow">{bi(lang,"Trend","Trend")}</span><h2>{bi(lang,"Ruhepuls · 14 Tage","Resting HR · 14 days")}</h2></div><Link prefetch={false} className="text-link" href="/health">{bi(lang,"Gesundheit","Health")} →</Link></div><div className="trend-visual"><SparkLine values={trend.map(x=>x.resting_hr)}/></div><div className="trend-footer"><span><i className="legend-dot"/>{rhrSources}</span><small>{bi(lang,"Mehr Metriken und Zeiträume in Gesundheit","More metrics and periods in Health")}</small></div></div>),
    activities:(<div className="card recent-card"><div className="section-heading"><div><span className="eyebrow">{bi(lang,"Training","Training")}</span><h2>{bi(lang,"Letzte Aktivitäten","Recent activities")}</h2></div><Link prefetch={false} className="text-link" href="/activities">{bi(lang,"Alle","All")} →</Link></div>{acts.length?<div className="recent-list">{acts.map(a=><Link prefetch={false} className="recent-activity" key={a.id} href={`/activities/${a.id}`}><span className="sport-badge">{sportGlyph(a.sport_type)}</span><span className="recent-main"><strong>{a.name??a.sport_type??"Activity"}</strong><small>{a.started_at?activityTimeLabel(a,lang):""}</small></span><span className="recent-stat">{a.distance_m?`${(a.distance_m/1000).toFixed(1)} km`:dur(a.duration_seconds)}</span><span className="recent-arrow">→</span></Link>)}</div>:<div className="empty-state"><strong>{bi(lang,"Noch keine Aktivitäten","No activities yet")}</strong><span>{bi(lang,"Synchronisiere Garmin oder SparkyFitness, um hier deine letzten Einheiten zu sehen.","Sync Garmin or SparkyFitness to see your latest sessions here.")}</span></div>}</div>)
  };

  return <AppShell>
    <SourceOverview/>
    <div className="today-data-state" aria-live="polite">{hQuery.error?<span>{bi(lang,"Aktualisierung fehlgeschlagen","Refresh failed")}</span>:hQuery.data&&hQuery.loading?<span>{bi(lang,"Werte werden aktualisiert …","Refreshing readings …")}</span>:hQuery.updatedAt?<span>{bi(lang,"Ansicht aktualisiert","View updated")} {new Date(hQuery.updatedAt).toLocaleTimeString(lang==="de"?"de-DE":"en-GB",{hour:"2-digit",minute:"2-digit"})}</span>:null}<button type="button" className="ghost compact" onClick={refresh} disabled={hQuery.loading}>{bi(lang,"Aktualisieren","Refresh")} ↻</button></div>
    <section className="dashboard-hero today-hero today-hero-clean">
      <div className="dashboard-hero-copy">
        <span className="eyebrow">{date}</span>
        <h1>{bi(lang,"Dein Tag. Deine Balance.","Your day. Your balance.")}</h1>
        <Link prefetch={false} className="text-link" href="/activities">{bi(lang,"Aktivitäten öffnen","Open activities")} →</Link>
      </div>
      <div className="today-focus-card today-focus-card-hero">
          <div className="today-focus-head">
            <div>
              <span className="metric-label">{bi(lang,"Deine Heute-Ansicht","Your Today view")}</span>
              <strong>{h?.available===true?bi(lang,"Tagesdaten bereit","Daily data ready"):h?bi(lang,"Tagesdaten fehlen","Daily data missing"):bi(lang,"Wird geladen …","Loading …")}</strong>
            </div>
            <div className="today-focus-tools"><TodayCustomization value={preferences} onSaved={setPreferences} lang={lang} loaded={prefsLoaded} error={prefsError} onRetry={()=>void prefsQuery.refresh()}/></div>
          </div>
          <small className="today-reading-count">{preferences.pinned_metrics.length} {bi(lang,"Messwerte ausgewählt","readings selected")}</small>
          <Link prefetch={false} className="text-link" href="/health">{bi(lang,"Gesundheit öffnen","Open health")} →</Link>
      </div>
    </section>

    {!preferences.hidden.includes("metrics")&&<section className="card today-readings" data-today-card="metrics"><div className="section-heading"><div><span className="eyebrow">{bi(lang,"Deine Werte im Blick","Your readings at a glance")}</span><h2>{bi(lang,"Deine Messwerte","Your readings")}</h2></div><button type="button" className="ghost compact" onClick={()=>document.getElementById("today-customization") instanceof HTMLDialogElement&&(document.getElementById("today-customization") as HTMLDialogElement).showModal()}>{bi(lang,"Messwerte auswählen","Choose readings")} <span aria-hidden="true">↗</span></button></div><section className="health-metric-grid">{preferences.pinned_metrics.filter((key:string)=>key!=="vo2max").map((key:string)=>cards.find(c=>c.key===key)).filter(Boolean).map((c:any)=>c.key==="steps"?<StepGoalCard key={c.key} summary={h?.step_goal} value={String(c.value)} note={hQuery.error&&!h?bi(lang,"Messwerte konnten nicht geladen werden","Readings could not be loaded"):c.note} loading={!h&&!hQuery.error} error={!!hQuery.error&&!h}/>:<MetricCard key={c.key} label={c.label} value={String(c.value)} note={hQuery.error&&!h?bi(lang,"Messwerte konnten nicht geladen werden","Readings could not be loaded"):c.note} tone={c.tone} loading={!h&&!hQuery.error} error={!!hQuery.error&&!h}/>)}{preferences.pinned_metrics.includes("vo2max")&&<div className="health-metric-card metric-card-modern tone-vo2 vo2-dual-card" data-metric="vo2max"><div className="health-metric-top"><span className="health-metric-dot"/><span className="metric-label">VO₂max</span></div><div className="vo2-dual-values"><div><small>{bi(lang,"Laufen","Running")}</small><strong>{h?.vo2max_running??"—"}</strong></div><div><small>{bi(lang,"Rad","Cycling")}</small><strong>{h?.vo2max_cycling??"—"}</strong></div></div><div className="kpi-note">ml/kg/min · {Array.from(new Set([h?.sources?.vo2max_running,h?.sources?.vo2max_cycling].filter(Boolean))).map(s=>sourceLabel(s,lang)).join(" + ")||"—"}</div></div>}</section></section>}
    <DayPhases data={briefing} phase={phase} onChange={setPhaseOverride} automatic={phaseOverride==null} lang={lang}/>
    <DailyCompanion onData={setBriefing} phase={phase} reflectionVisible={!preferences.hidden.includes("reflection")}/>
    <div className="today-personal-cards">{prefsLoaded&&preferences.order.map((key:string)=>!preferences.hidden.includes(key)&&!["metrics","reflection"].includes(key)&&cardsById[key]?<div className={`today-order-item today-block-${key}`} data-today-card={key} key={key}>{cardsById[key]}</div>:null)}</div>
    </AppShell>
}
