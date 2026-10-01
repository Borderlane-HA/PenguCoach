"use client";

import {useEffect,useMemo,useState} from "react";
import {sourceLabel,measuredLabel,localDate} from "../../lib/sources";
import SourceOverview from "../../components/SourceOverview";
import AppShell from "../../components/AppShell";
import HealthDevelopment from "../../components/HealthDevelopment";
import ProfessionalLineChart from "../../components/ProfessionalLineChart";
import {api} from "../../lib/api";
import {bi,useI18n} from "../../lib/i18n";

type Vo2Point={date:string;value:number;activity_id?:string;measurement_kind?:"imported"|"estimated";confidence?:string;source?:string};
type Vo2Data={running:Vo2Point[];cycling:Vo2Point[];latest?:{running?:number|null;cycling?:number|null};latest_meta?:Record<string,any>;imported?:Record<string,Vo2Point[]>;estimated?:Record<string,Vo2Point[]>};
type BodyLatest={measured_at_by_metric?:Record<string,string>;weight_kg?:number;height_cm?:number;bmi?:number;body_fat_percent?:number;body_water_percent?:number;muscle_mass_kg?:number;bone_mass_kg?:number;sources?:Record<string,string>;measured_at?:string};

function latestWith<T=any>(rows:any[],key:string):T|undefined{for(let i=(rows?.length??0)-1;i>=0;i--){const v=rows[i]?.[key];if(v!==null&&v!==undefined&&v!=="")return rows[i] as T}return undefined}
function rowMetricSource(row:any,key:string){return sourceLabel(row?.sources?.[key]??row?.source)}
function bodyMetricSource(body:BodyLatest|undefined,key:string){return [sourceLabel(body?.sources?.[key]),measuredLabel(body?.measured_at_by_metric?.[key])].filter(Boolean).join(" · ")}
function metricValues(rows:any[],key:string){const values:number[]=[];for(const row of rows??[]){const raw=row?.[key];if(raw===null||raw===undefined||raw==="")continue;const value=Number(raw);if(Number.isFinite(value))values.push(value)}return values}
function metricAverage(rows:any[],key:string){const values=metricValues(rows,key);return {value:values.length?values.reduce((sum,value)=>sum+value,0)/values.length:null,count:values.length}}
function metricSourceSummary(rows:any[],key:string){
  const labels=[...new Set((rows??[]).filter(row=>row?.[key]!==null&&row?.[key]!==undefined&&row?.[key]!=="").map(row=>rowMetricSource(row,key)))];
  if(labels.includes("Garmin + SparkyFitness")||(labels.includes("Garmin")&&labels.includes("SparkyFitness")))return "Garmin + SparkyFitness";
  return labels.join(" + ")||"—";
}
function periodDays(period:string){
  if(period==="today")return 1;
  if(period==="last7")return 7;
  const now=new Date();
  if(period==="week")return ((now.getDay()+6)%7)+1;
  if(period==="month")return now.getDate();
  if(period==="3m")return 90;
  if(period==="6m")return 180;
  if(period==="year")return Math.floor((Date.UTC(now.getFullYear(),now.getMonth(),now.getDate())-Date.UTC(now.getFullYear(),0,1))/86400000)+1;
  return 7;
}

export default function Health(){
  const{lang}=useI18n();
  const[data,setData]=useState<any>({health:[],sleep:[],hrv:[],body:[],body_latest:null});
  const[period,setPeriod]=useState("last7");
  const[vo2,setVo2]=useState<Vo2Data>({running:[],cycling:[]});
  const[development,setDevelopment]=useState<any>({summary:{},volume:[],load_recovery:[],changes:[],efficiency:{},sport_mix:[]});
  const[manualOpen,setManualOpen]=useState(false),[manualSaving,setManualSaving]=useState(false),[manualError,setManualError]=useState("");
  const[manual,setManual]=useState<Record<string,string>>({measured_on:localDate(),weight_kg:"",height_cm:"",body_fat_percent:"",body_water_percent:"",muscle_mass_kg:"",bone_mass_kg:""});

  function load(){
    const suffix=period==="all"?"?all=true":`?days=${periodDays(period)}`;
    return Promise.all([api<any>(`/health/range${suffix}`),api<any>(`/health/development${suffix}`)]).then(([range,dev])=>{setData(range);setDevelopment(dev);setVo2((dev?.vo2_display??{running:[],cycling:[]}) as Vo2Data)});
  }
  useEffect(()=>{void load()},[period]);

  const avgRhr=metricAverage(data.health??[],"resting_hr"),avgSteps=metricAverage(data.health??[],"steps"),avgBattery=metricAverage(data.health??[],"body_battery_high"),avgStress=metricAverage(data.health??[],"stress_avg"),avgHydration=metricAverage(data.health??[],"hydration_ml"),avgSleep=metricAverage(data.sleep??[],"duration_seconds"),avgHrv=metricAverage(data.hrv??[],"overnight_average");
  const latestHydrationGoal=latestWith(data.health??[],"hydration_goal_ml");
  const body:BodyLatest|undefined=data.body_latest??undefined;
  function openManual(){
    setManual({measured_on:localDate(),weight_kg:"",height_cm:"",body_fat_percent:"",body_water_percent:"",muscle_mass_kg:"",bone_mass_kg:""});
    setManualError("");setManualOpen(true);
  }
  async function saveManual(){
    setManualSaving(true);setManualError("");
    try{
      const payload:any={measured_on:manual.measured_on};
      for(const key of ["weight_kg","height_cm","body_fat_percent","body_water_percent","muscle_mass_kg","bone_mass_kg"]){const raw=manual[key]?.trim();if(raw)payload[key]=Number(raw)}
      await api("/health/body/manual",{method:"PUT",body:JSON.stringify(payload)});
      await load();setManualOpen(false);
    }catch(e){setManualError(e instanceof Error?e.message:String(e))}finally{setManualSaving(false)}
  }
  const periodLabel=useMemo(()=>{
    if(period==="today")return bi(lang,"Heute","Today");
    if(period==="last7")return bi(lang,"Letzte 7 Tage","Last 7 days");
    if(period==="week")return bi(lang,"Diese Woche","This week");
    if(period==="month")return bi(lang,"Dieser Monat","This month");
    if(period==="3m")return bi(lang,"Letzte 3 Monate","Last 3 months");
    if(period==="6m")return bi(lang,"Letzte 6 Monate","Last 6 months");
    if(period==="year")return bi(lang,"Dieses Jahr","This year");
    return bi(lang,"Alle","All");
  },[period,lang]);
  function averageNote(count:number,rows:any[],key:string,kind:"day"|"night"|"reading"="day"){
    if(!count)return bi(lang,"Keine Daten im Zeitraum","No data in period");
    const unit=kind==="night"?(count===1?bi(lang,"Nacht","night"):bi(lang,"Nächten","nights")):kind==="reading"?(count===1?bi(lang,"Messwert","reading"):bi(lang,"Messwerten","readings")):(count===1?bi(lang,"Tag","day"):bi(lang,"Tagen","days"));
    return `${bi(lang,"Ø aus","Avg of")} ${count} ${unit} · ${metricSourceSummary(rows,key)}`;
  }
  const cards=[
    {label:"HRV",value:avgHrv.value!=null?`${Math.round(avgHrv.value)} ms`:"—",note:averageNote(avgHrv.count,data.hrv??[],"overnight_average"),tone:"hrv"},
    {label:bi(lang,"Schlaf","Sleep"),value:avgSleep.value!=null?`${(avgSleep.value/3600).toFixed(1)} h`:"—",note:averageNote(avgSleep.count,data.sleep??[],"duration_seconds","night"),tone:"sleep"},
    {label:bi(lang,"Ruhepuls","Resting HR"),value:avgRhr.value!=null?`${Math.round(avgRhr.value)} bpm`:"—",note:averageNote(avgRhr.count,data.health??[],"resting_hr"),tone:"heart"},
    {label:bi(lang,"Schritte","Steps"),value:avgSteps.value!=null?Math.round(avgSteps.value).toLocaleString(lang==="de"?"de-DE":"en-US"):"—",note:averageNote(avgSteps.count,data.health??[],"steps"),tone:"steps"},
    {label:bi(lang,"Body Battery · Tageshoch","Body Battery · daily high"),value:avgBattery.value!=null?Math.round(avgBattery.value):"—",note:averageNote(avgBattery.count,data.health??[],"body_battery_high"),tone:"battery"},
    {label:"Stress",value:avgStress.value!=null?Math.round(avgStress.value):"—",note:averageNote(avgStress.count,data.health??[],"stress_avg"),tone:"stress"},
    {label:bi(lang,"Hydration","Hydration"),value:avgHydration.value!=null?`${(avgHydration.value/1000).toFixed(1)} L`:"—",note:avgHydration.count?`${averageNote(avgHydration.count,data.health??[],"hydration_ml")}${latestHydrationGoal?.hydration_goal_ml?` · ${bi(lang,"Ziel","Goal")} ${(latestHydrationGoal.hydration_goal_ml/1000).toFixed(1)} L`:""}`:bi(lang,"Keine Daten im Zeitraum","No data in period"),tone:"water"}
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
    <SourceOverview/>
    <section className="page-head-modern"><div><span className="eyebrow">{bi(lang,"Physiologie & Erholung","Physiology & recovery")}</span><h1>{bi(lang,"Gesundheit","Health")}</h1><p>{bi(lang,"Deine Gesundheitswerte im Verlauf – mit Quelle je Messwert und aktuellen Körperwerten aus allen verfügbaren Daten.","Your health trends, with a source for every reading and current body metrics from all available data.")}</p></div><div className="period-control"><span>{bi(lang,"Zeitraum","Period")}</span><select value={period} onChange={e=>setPeriod(e.target.value)}><option value="today">{bi(lang,"Heute","Today")}</option><option value="last7">{bi(lang,"Letzte 7 Tage","Last 7 days")}</option><option value="week">{bi(lang,"Diese Woche","This week")}</option><option value="month">{bi(lang,"Dieser Monat","This month")}</option><option value="3m">{bi(lang,"Letzte 3 Monate","Last 3 months")}</option><option value="6m">{bi(lang,"Letzte 6 Monate","Last 6 months")}</option><option value="year">{bi(lang,"Dieses Jahr","This year")}</option><option value="all">{bi(lang,"Alle","All")}</option></select></div></section>

    <section className="health-metric-grid health-page-metrics">{cards.filter(c=>c.tone!=="battery"||c.value!=="—").map(c=><div className={`health-metric-card tone-${c.tone}`} key={c.label}><div className="health-metric-top"><span className="health-metric-dot"/><span className="metric-label">{c.label}</span></div><div className="metric-value">{String(c.value)}</div><div className="kpi-note">{c.note}</div></div>)}</section>

    <HealthDevelopment data={development} vo2={vo2} lang={lang} periodLabel={periodLabel}/>

    <section className="card body-composition-card"><div className="section-heading"><div><span className="eyebrow">{bi(lang,"Körperzusammensetzung","Body composition")}</span><h2>{bi(lang,"Aktuelle Körperwerte","Current body metrics")}</h2><p>{bi(lang,"Verbundene Quellen und manuell gepflegte Werte. Ein manueller Wert bleibt aktiv, bis für dieselbe Kennzahl eine neuere Messung eintrifft.","Connected sources and manually maintained values. A manual value stays active until a newer measurement for the same metric arrives.")}</p></div><div className="body-heading-actions"><span className="period-badge">{bi(lang,"Aktuell","Current")}</span><button type="button" className="ghost" onClick={openManual}>{bi(lang,"Manuell erfassen","Add manually")}</button></div></div><div className="body-metric-grid">{bodyCards.map(item=><div className="body-metric" key={item.key}><small>{item.label}</small><strong>{item.value}</strong><span>{body?.[item.key as keyof BodyLatest]!=null?bodyMetricSource(body,item.key):bi(lang,"Keine Daten","No data")}</span></div>)}</div>{manualOpen&&<div className="manual-body-editor"><div className="manual-body-intro"><strong>{bi(lang,"Körperwerte manuell pflegen","Maintain body metrics manually")}</strong><small>{bi(lang,"Ideal ohne Smart-Waage. Leere Felder werden nicht erfunden; ältere vorhandene Werte bleiben als Fallback verfügbar.","Useful without a smart scale. Empty fields are never invented; older known values remain available as fallback.")}</small></div><div className="manual-body-grid"><label>{bi(lang,"Datum","Date")}<input type="date" value={manual.measured_on} onChange={e=>setManual({...manual,measured_on:e.target.value})}/></label><label>{bi(lang,"Gewicht","Weight")}<span className="unit-input"><input type="number" min="20" max="500" step="0.1" placeholder={body?.weight_kg!=null?body.weight_kg.toFixed(1):""} value={manual.weight_kg} onChange={e=>setManual({...manual,weight_kg:e.target.value})}/><b>kg</b></span></label><label>{bi(lang,"Größe","Height")}<span className="unit-input"><input type="number" min="50" max="260" step="0.1" placeholder={body?.height_cm!=null?body.height_cm.toFixed(0):""} value={manual.height_cm} onChange={e=>setManual({...manual,height_cm:e.target.value})}/><b>cm</b></span></label><label>{bi(lang,"Körperfett","Body fat")}<span className="unit-input"><input type="number" min="1" max="75" step="0.1" placeholder={body?.body_fat_percent!=null?body.body_fat_percent.toFixed(1):""} value={manual.body_fat_percent} onChange={e=>setManual({...manual,body_fat_percent:e.target.value})}/><b>%</b></span></label><label>{bi(lang,"Körperwasser","Body water")}<span className="unit-input"><input type="number" min="10" max="90" step="0.1" placeholder={body?.body_water_percent!=null?body.body_water_percent.toFixed(1):""} value={manual.body_water_percent} onChange={e=>setManual({...manual,body_water_percent:e.target.value})}/><b>%</b></span></label><label>{bi(lang,"Muskelmasse","Muscle mass")}<span className="unit-input"><input type="number" min="1" max="300" step="0.1" placeholder={body?.muscle_mass_kg!=null?body.muscle_mass_kg.toFixed(1):""} value={manual.muscle_mass_kg} onChange={e=>setManual({...manual,muscle_mass_kg:e.target.value})}/><b>kg</b></span></label><label>{bi(lang,"Knochenmasse","Bone mass")}<span className="unit-input"><input type="number" min="0.1" max="30" step="0.1" placeholder={body?.bone_mass_kg!=null?body.bone_mass_kg.toFixed(1):""} value={manual.bone_mass_kg} onChange={e=>setManual({...manual,bone_mass_kg:e.target.value})}/><b>kg</b></span></label></div>{manualError&&<div className="status-bad">{manualError}</div>}<div className="manual-body-actions"><button type="button" className="ghost" onClick={()=>setManualOpen(false)}>{bi(lang,"Abbrechen","Cancel")}</button><button type="button" className="primary" disabled={manualSaving} onClick={()=>void saveManual()}>{manualSaving?bi(lang,"Speichert…","Saving…"):bi(lang,"Körperwerte speichern","Save body metrics")}</button></div></div>}</section>

    <details className="card health-secondary-details">
      <summary><div><span className="eyebrow">DETAILS</span><h2>{bi(lang,"Weitere Gesundheitsverläufe","More health trends")}</h2><p>{bi(lang,"HRV, Ruhepuls, Schlaf, Schritte und Körperwerte mit Achsen und Tooltip statt einfacher Sparklines.","HRV, resting heart rate, sleep, steps and body metrics with axes and tooltips instead of basic sparklines.")}</p></div><span className="period-badge">{periodLabel}</span></summary>
      <div className="health-professional-grid">
        <div className="insight-chart-card"><div className="insight-title"><div><span className="eyebrow">HRV</span><h3>{bi(lang,"Nächtlicher Durchschnitt","Overnight average")}</h3></div></div><ProfessionalLineChart height={245} series={[{label:"HRV",points:(data.hrv??[]).map((x:any)=>({date:x.date,label:x.date,value:x.overnight_average})),unit:"ms",decimals:0}]}/></div>
        <div className="insight-chart-card"><div className="insight-title"><div><span className="eyebrow">HEART</span><h3>{bi(lang,"Ruhepuls","Resting HR")}</h3></div></div><ProfessionalLineChart height={245} series={[{label:bi(lang,"Ruhepuls","Resting HR"),points:(data.health??[]).map((x:any)=>({date:x.date,label:x.date,value:x.resting_hr})),unit:"bpm",decimals:0}]}/></div>
        <div className="insight-chart-card"><div className="insight-title"><div><span className="eyebrow">SLEEP</span><h3>{bi(lang,"Schlafdauer","Sleep duration")}</h3></div></div><ProfessionalLineChart height={245} series={[{label:bi(lang,"Schlaf","Sleep"),points:(data.sleep??[]).map((x:any)=>({date:x.date,label:x.date,value:x.duration_seconds?x.duration_seconds/3600:null})),unit:"h",decimals:1}]}/></div>
        <div className="insight-chart-card"><div className="insight-title"><div><span className="eyebrow">STEPS</span><h3>{bi(lang,"Tagesschritte","Daily steps")}</h3></div></div><ProfessionalLineChart height={245} series={[{label:bi(lang,"Schritte","Steps"),points:(data.health??[]).map((x:any)=>({date:x.date,label:x.date,value:x.steps})),decimals:0}]}/></div>
        <div className="insight-chart-card"><div className="insight-title"><div><span className="eyebrow">WEIGHT</span><h3>{bi(lang,"Gewicht","Weight")}</h3></div></div><ProfessionalLineChart height={245} series={[{label:bi(lang,"Gewicht","Weight"),points:(data.body??[]).map((x:any)=>({date:String(x.measured_at??"").slice(0,10),label:String(x.measured_at??"").slice(0,10),value:x.weight_kg})),unit:"kg",decimals:1}]}/></div>
        <div className="insight-chart-card"><div className="insight-title"><div><span className="eyebrow">BODY FAT</span><h3>{bi(lang,"Körperfett","Body fat")}</h3></div></div><ProfessionalLineChart height={245} series={[{label:bi(lang,"Körperfett","Body fat"),points:(data.body??[]).map((x:any)=>({date:String(x.measured_at??"").slice(0,10),label:String(x.measured_at??"").slice(0,10),value:x.body_fat_percent})),unit:"%",decimals:1}]}/></div>
      </div>
    </details>

    <section className="card data-quality-card"><div><span className="eyebrow">{bi(lang,"Datenqualität","Data coverage")}</span><h2>{bi(lang,"Abdeckung im gewählten Zeitraum","Coverage in selected period")}</h2><p>{bi(lang,"PenguCoach verwendet fehlende Werte nicht als Null und erfindet keine Gesundheitsdaten.","PenguCoach keeps missing values missing and never invents health data.")}</p></div><div className="coverage-pills"><span><strong>{data.health?.length??0}</strong>{bi(lang,"Gesundheitstage","health days")}</span><span><strong>{data.sleep?.length??0}</strong>{bi(lang,"Schlafnächte","sleep nights")}</span><span><strong>{data.hrv?.length??0}</strong>{bi(lang,"HRV-Tage","HRV days")}</span><span><strong>{data.body?.length??0}</strong>{bi(lang,"Körpermessungen","body readings")}</span><span><strong>{(vo2.running?.length??0)+(vo2.cycling?.length??0)}</strong>{bi(lang,"VO₂max-Werte","VO₂ max values")}</span></div></section>
  </AppShell>
}
