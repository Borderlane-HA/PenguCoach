"use client";

import {useEffect,useState} from "react";
import AppShell from "../../components/AppShell";
import SparkLine from "../../components/SparkLine";
import {api} from "../../lib/api";
import {bi,useI18n} from "../../lib/i18n";

export default function Health(){
  const{lang}=useI18n();const[data,setData]=useState<any>({health:[],sleep:[],hrv:[]});const[days,setDays]=useState(30);
  useEffect(()=>{api<any>(`/health/range?days=${days}`).then(setData)},[days]);
  const latest=data.health?.at(-1);const sleep=data.sleep?.at(-1);const hrv=data.hrv?.at(-1);
  const periodLabel=days===365?bi(lang,"1 Jahr","1 year"):`${days} ${bi(lang,"Tage","days")}`;
  const cards=[
    {label:"HRV",value:hrv?.overnight_average?`${hrv.overnight_average} ms`:"—",note:hrv?.status??"Garmin",tone:"hrv"},
    {label:bi(lang,"Schlaf","Sleep"),value:sleep?.duration_seconds?`${(sleep.duration_seconds/3600).toFixed(1)} h`:"—",note:sleep?.score?`Score ${sleep.score}`:"Garmin",tone:"sleep"},
    {label:bi(lang,"Ruhepuls","Resting HR"),value:latest?.resting_hr?`${latest.resting_hr} bpm`:"—",note:"Garmin",tone:"heart"},
    {label:"Body Battery",value:latest?.body_battery_high??"—",note:"Garmin",tone:"battery"},
    {label:"Stress",value:latest?.stress_avg??"—",note:bi(lang,"Tagesdurchschnitt","Daily average"),tone:"stress"},
    {label:bi(lang,"Hydration","Hydration"),value:latest?.hydration_ml?`${(latest.hydration_ml/1000).toFixed(1)} L`:"—",note:latest?.hydration_goal_ml?`${bi(lang,"Ziel","Goal")} ${(latest.hydration_goal_ml/1000).toFixed(1)} L`:"Garmin",tone:"water"}
  ];
  return <AppShell>
    <section className="page-head-modern"><div><span className="eyebrow">{bi(lang,"Physiologie & Erholung","Physiology & recovery")}</span><h1>{bi(lang,"Gesundheit","Health")}</h1><p>{bi(lang,"Deine Garmin-Gesundheitswerte als ruhiger Langzeitverlauf – für Training, Erholung und Kontext.","Your Garmin health signals as calm long-term trends for training, recovery and context.")}</p></div><div className="period-control"><span>{bi(lang,"Zeitraum","Period")}</span><select value={days} onChange={e=>setDays(Number(e.target.value))}><option value={7}>7 {bi(lang,"Tage","days")}</option><option value={30}>30 {bi(lang,"Tage","days")}</option><option value={90}>90 {bi(lang,"Tage","days")}</option><option value={365}>{bi(lang,"1 Jahr","1 year")}</option></select></div></section>

    <section className="health-metric-grid health-page-metrics">{cards.map(c=><div className={`health-metric-card tone-${c.tone}`} key={c.label}><div className="health-metric-top"><span className="health-metric-dot"/><span className="metric-label">{c.label}</span></div><div className="metric-value">{String(c.value)}</div><div className="kpi-note">{c.note}</div></div>)}</section>

    <section className="health-chart-grid">
      <div className="card health-chart-card"><div className="section-heading"><div><span className="eyebrow">HRV</span><h2>{bi(lang,"Nächtlicher Durchschnitt","Overnight average")}</h2></div><span className="period-badge">{periodLabel}</span></div><SparkLine values={(data.hrv??[]).map((x:any)=>x.overnight_average)}/></div>
      <div className="card health-chart-card"><div className="section-heading"><div><span className="eyebrow">HEART</span><h2>{bi(lang,"Ruhepuls","Resting HR")}</h2></div><span className="period-badge">{periodLabel}</span></div><SparkLine values={(data.health??[]).map((x:any)=>x.resting_hr)}/></div>
      <div className="card health-chart-card"><div className="section-heading"><div><span className="eyebrow">SLEEP</span><h2>{bi(lang,"Schlafdauer","Sleep duration")}</h2></div><span className="period-badge">{periodLabel}</span></div><SparkLine values={(data.sleep??[]).map((x:any)=>x.duration_seconds?x.duration_seconds/3600:null)}/></div>
      <div className="card health-chart-card"><div className="section-heading"><div><span className="eyebrow">STRESS</span><h2>{bi(lang,"Stress","Stress")}</h2></div><span className="period-badge">{periodLabel}</span></div><SparkLine values={(data.health??[]).map((x:any)=>x.stress_avg)}/></div>
    </section>

    <section className="card data-quality-card"><div><span className="eyebrow">{bi(lang,"Datenqualität","Data coverage")}</span><h2>{bi(lang,"Abdeckung im gewählten Zeitraum","Coverage in selected period")}</h2><p>{bi(lang,"PenguCoach verwendet fehlende Werte nicht als Null und erfindet keine Gesundheitsdaten.","PenguCoach keeps missing values missing and never invents health data.")}</p></div><div className="coverage-pills"><span><strong>{data.health?.length??0}</strong>{bi(lang,"Gesundheitstage","health days")}</span><span><strong>{data.sleep?.length??0}</strong>{bi(lang,"Schlafnächte","sleep nights")}</span><span><strong>{data.hrv?.length??0}</strong>{bi(lang,"HRV-Tage","HRV days")}</span></div></section>
  </AppShell>
}
