"use client";

import {useEffect,useMemo,useState} from "react";
import AppShell from "../../components/AppShell";
import DualTrendChart from "../../components/DualTrendChart";
import SparkLine from "../../components/SparkLine";
import {api} from "../../lib/api";
import {bi,useI18n} from "../../lib/i18n";

type Vo2Point={date:string;value:number;activity_id?:string};
type Vo2Data={running:Vo2Point[];cycling:Vo2Point[];latest?:{running?:number|null;cycling?:number|null}};
type BodyLatest={weight_kg?:number;height_cm?:number;bmi?:number;body_fat_percent?:number;body_water_percent?:number;muscle_mass_kg?:number;bone_mass_kg?:number;sources?:Record<string,string>;measured_at?:string};

function latestWith<T=any>(rows:any[],key:string):T|undefined{for(let i=(rows?.length??0)-1;i>=0;i--){const v=rows[i]?.[key];if(v!==null&&v!==undefined&&v!=="")return rows[i] as T}return undefined}
function sourceLabel(source?:string){if(source==="sparkyfitness")return "SparkyFitness";if(source==="garmin+sparkyfitness")return "Garmin + SparkyFitness";return source||"Garmin"}
function rowMetricSource(row:any,key:string){return sourceLabel(row?.sources?.[key]??row?.source)}
function bodyMetricSource(body:BodyLatest|undefined,key:string){return sourceLabel(body?.sources?.[key])}

export default function Health(){
  const{lang}=useI18n();
  const[data,setData]=useState<any>({health:[],sleep:[],hrv:[],body:[],body_latest:null});
  const[period,setPeriod]=useState("30");
  const[vo2,setVo2]=useState<Vo2Data>({running:[],cycling:[]});

  useEffect(()=>{
    const suffix=period==="all"?"?all=true":`?days=${Number(period)}`;
    void Promise.all([
      api<any>(`/health/range${suffix}`),
      api<Vo2Data>(`/health/vo2-history${suffix}`),
    ]).then(([range,vo2Range])=>{setData(range);setVo2(vo2Range)});
  },[period]);

  const latestRhr=latestWith(data.health??[],"resting_hr"),latestSteps=latestWith(data.health??[],"steps"),latestBattery=latestWith(data.health??[],"body_battery_high"),latestStress=latestWith(data.health??[],"stress_avg"),latestHydration=latestWith(data.health??[],"hydration_ml"),sleep=latestWith(data.sleep??[],"duration_seconds"),hrv=latestWith(data.hrv??[],"overnight_average");
  const body:BodyLatest|undefined=data.body_latest??undefined;
  const periodLabel=useMemo(()=>{
    if(period==="all")return bi(lang,"Alle Daten","All data");
    const days=Number(period);
    if(days===365)return bi(lang,"1 Jahr","1 year");
    if(days===1825)return bi(lang,"5 Jahre","5 years");
    return `${days} ${bi(lang,"Tage","days")}`;
  },[period,lang]);
  const cards=[
    {label:"HRV",value:hrv?.overnight_average?`${hrv.overnight_average} ms`:"—",note:hrv?`${sourceLabel(hrv.source)}${hrv.status?` · ${hrv.status}`:""}`:bi(lang,"Keine Daten im Zeitraum","No data in period"),tone:"hrv"},
    {label:bi(lang,"Schlaf","Sleep"),value:sleep?.duration_seconds?`${(sleep.duration_seconds/3600).toFixed(1)} h`:"—",note:sleep?`${sourceLabel(sleep.source)}${sleep.score?` · Score ${sleep.score}`:""}`:bi(lang,"Keine Daten im Zeitraum","No data in period"),tone:"sleep"},
    {label:bi(lang,"Ruhepuls","Resting HR"),value:latestRhr?.resting_hr?`${latestRhr.resting_hr} bpm`:"—",note:latestRhr?rowMetricSource(latestRhr,"resting_hr"):bi(lang,"Keine Daten im Zeitraum","No data in period"),tone:"heart"},
    {label:bi(lang,"Schritte","Steps"),value:latestSteps?.steps?Number(latestSteps.steps).toLocaleString(lang==="de"?"de-DE":"en-US"):"—",note:latestSteps?rowMetricSource(latestSteps,"steps"):bi(lang,"Keine Daten im Zeitraum","No data in period"),tone:"steps"},
    {label:"Body Battery",value:latestBattery?.body_battery_high??"—",note:latestBattery?rowMetricSource(latestBattery,"body_battery_high"):bi(lang,"Keine Daten im Zeitraum","No data in period"),tone:"battery"},
    {label:"Stress",value:latestStress?.stress_avg??"—",note:latestStress?`${rowMetricSource(latestStress,"stress_avg")} · ${bi(lang,"Tagesdurchschnitt","Daily average")}`:bi(lang,"Keine Daten im Zeitraum","No data in period"),tone:"stress"},
    {label:bi(lang,"Hydration","Hydration"),value:latestHydration?.hydration_ml?`${(latestHydration.hydration_ml/1000).toFixed(1)} L`:"—",note:latestHydration?`${rowMetricSource(latestHydration,"hydration_ml")}${latestHydration.hydration_goal_ml?` · ${bi(lang,"Ziel","Goal")} ${(latestHydration.hydration_goal_ml/1000).toFixed(1)} L`:""}`:bi(lang,"Keine Daten im Zeitraum","No data in period"),tone:"water"}
  ];
  const bodyCards=[
    {label:bi(lang,"Gewicht","Weight"),key:"weight_kg",value:body?.weight_kg!=null?`${body.weight_kg.toFixed(1)} kg`:"—"},
    {label:bi(lang,"Körperfett","Body fat"),key:"body_fat_percent",value:body?.body_fat_percent!=null?`${body.body_fat_percent.toFixed(1)} %`:"—"},
    {label:bi(lang,"Muskelmasse","Muscle mass"),key:"muscle_mass_kg",value:body?.muscle_mass_kg!=null?`${body.muscle_mass_kg.toFixed(1)} kg`:"—"},
    {label:bi(lang,"Körperwasser","Body water"),key:"body_water_percent",value:body?.body_water_percent!=null?`${body.body_water_percent.toFixed(1)} %`:"—"},
    {label:bi(lang,"Knochenmasse","Bone mass"),key:"bone_mass_kg",value:body?.bone_mass_kg!=null?`${body.bone_mass_kg.toFixed(1)} kg`:"—"},
    {label:"BMI",key:"bmi",value:body?.bmi!=null?body.bmi.toFixed(1):"—"},
    {label:bi(lang,"Größe","Height"),key:"height_cm",value:body?.height_cm!=null?`${body.height_cm.toFixed(0)} cm`:"—"}
  ];

  return <AppShell>
    <section className="page-head-modern"><div><span className="eyebrow">{bi(lang,"Physiologie & Erholung","Physiology & recovery")}</span><h1>{bi(lang,"Gesundheit","Health")}</h1><p>{bi(lang,"Garmin- und SparkyFitness-Gesundheitswerte als ruhiger Langzeitverlauf – mit Quellenkennzeichnung pro Messwert.","Garmin and SparkyFitness health signals as calm long-term trends, with provenance per metric.")}</p></div><div className="period-control"><span>{bi(lang,"Zeitraum","Period")}</span><select value={period} onChange={e=>setPeriod(e.target.value)}><option value="7">7 {bi(lang,"Tage","days")}</option><option value="30">30 {bi(lang,"Tage","days")}</option><option value="90">90 {bi(lang,"Tage","days")}</option><option value="365">{bi(lang,"1 Jahr","1 year")}</option><option value="1825">{bi(lang,"5 Jahre","5 years")}</option><option value="all">{bi(lang,"Alle Daten","All data")}</option></select></div></section>

    <section className="health-metric-grid health-page-metrics">{cards.map(c=><div className={`health-metric-card tone-${c.tone}`} key={c.label}><div className="health-metric-top"><span className="health-metric-dot"/><span className="metric-label">{c.label}</span></div><div className="metric-value">{String(c.value)}</div><div className="kpi-note">{c.note}</div></div>)}</section>

    <section className="card body-composition-card"><div className="section-heading"><div><span className="eyebrow">{bi(lang,"Körperzusammensetzung","Body composition")}</span><h2>{bi(lang,"Aktuelle Körperwerte","Current body metrics")}</h2><p>{bi(lang,"Gewicht und Waagenwerte aus Garmin oder SparkyFitness. Fehlende Werte bleiben leer und werden nicht geschätzt.","Weight and smart-scale metrics from Garmin or SparkyFitness. Missing values remain empty and are never estimated.")}</p></div><span className="period-badge">{periodLabel}</span></div><div className="body-metric-grid">{bodyCards.map(item=><div className="body-metric" key={item.key}><small>{item.label}</small><strong>{item.value}</strong><span>{body?.[item.key as keyof BodyLatest]!=null?bodyMetricSource(body,item.key):bi(lang,"Keine Daten","No data")}</span></div>)}</div></section>

    <section className="card vo2-history-card">
      <div className="section-heading vo2-heading"><div><span className="eyebrow">VO₂MAX · GARMIN</span><h2>{bi(lang,"Laufen & Radfahren","Running & cycling")} · {periodLabel}</h2><p>{bi(lang,"Sportartspezifische Garmin-VO₂max-Werte aus deinen Aktivitätszusammenfassungen im ausgewählten Zeitraum.","Sport-specific Garmin VO₂ max values from activity summaries in the selected period.")}</p></div><div className="vo2-current"><div><small>{bi(lang,"Laufen","Running")}</small><strong>{vo2.latest?.running??"—"}</strong></div><div><small>{bi(lang,"Radfahren","Cycling")}</small><strong>{vo2.latest?.cycling??"—"}</strong></div><span>ml/kg/min</span></div></div>
      <DualTrendChart running={vo2.running??[]} cycling={vo2.cycling??[]} lang={lang}/>
    </section>

    <section className="health-chart-grid">
      <div className="card health-chart-card"><div className="section-heading"><div><span className="eyebrow">HRV</span><h2>{bi(lang,"Nächtlicher Durchschnitt","Overnight average")}</h2></div><span className="period-badge">{periodLabel}</span></div><SparkLine values={(data.hrv??[]).map((x:any)=>x.overnight_average)}/></div>
      <div className="card health-chart-card"><div className="section-heading"><div><span className="eyebrow">HEART</span><h2>{bi(lang,"Ruhepuls","Resting HR")}</h2></div><span className="period-badge">{periodLabel}</span></div><SparkLine values={(data.health??[]).map((x:any)=>x.resting_hr)}/></div>
      <div className="card health-chart-card"><div className="section-heading"><div><span className="eyebrow">SLEEP</span><h2>{bi(lang,"Schlafdauer","Sleep duration")}</h2></div><span className="period-badge">{periodLabel}</span></div><SparkLine values={(data.sleep??[]).map((x:any)=>x.duration_seconds?x.duration_seconds/3600:null)}/></div>
      <div className="card health-chart-card"><div className="section-heading"><div><span className="eyebrow">STEPS</span><h2>{bi(lang,"Tagesschritte","Daily steps")}</h2></div><span className="period-badge">{periodLabel}</span></div><SparkLine values={(data.health??[]).map((x:any)=>x.steps)}/></div>
      <div className="card health-chart-card"><div className="section-heading"><div><span className="eyebrow">WEIGHT</span><h2>{bi(lang,"Gewicht","Weight")}</h2></div><span className="period-badge">{periodLabel}</span></div><SparkLine values={(data.body??[]).map((x:any)=>x.weight_kg)}/></div>
      <div className="card health-chart-card"><div className="section-heading"><div><span className="eyebrow">BODY FAT</span><h2>{bi(lang,"Körperfett","Body fat")}</h2></div><span className="period-badge">{periodLabel}</span></div><SparkLine values={(data.body??[]).map((x:any)=>x.body_fat_percent)}/></div>
    </section>

    <section className="card data-quality-card"><div><span className="eyebrow">{bi(lang,"Datenqualität","Data coverage")}</span><h2>{bi(lang,"Abdeckung im gewählten Zeitraum","Coverage in selected period")}</h2><p>{bi(lang,"PenguCoach verwendet fehlende Werte nicht als Null und erfindet keine Gesundheitsdaten.","PenguCoach keeps missing values missing and never invents health data.")}</p></div><div className="coverage-pills"><span><strong>{data.health?.length??0}</strong>{bi(lang,"Gesundheitstage","health days")}</span><span><strong>{data.sleep?.length??0}</strong>{bi(lang,"Schlafnächte","sleep nights")}</span><span><strong>{data.hrv?.length??0}</strong>{bi(lang,"HRV-Tage","HRV days")}</span><span><strong>{data.body?.length??0}</strong>{bi(lang,"Körpermessungen","body readings")}</span><span><strong>{(vo2.running?.length??0)+(vo2.cycling?.length??0)}</strong>{bi(lang,"VO₂max-Messungen","VO₂ max readings")}</span></div></section>
  </AppShell>
}
