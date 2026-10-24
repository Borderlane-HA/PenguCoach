"use client";
// alpha.83 Health: key figures with trend, explanation and coach, charts, development and body – all optional and ordered.
import {useEffect,useMemo,useState} from "react";
import AppShell from "../../components/AppShell";
import NumberInput from "../../components/NumberInput";
import HealthDevelopment from "../../components/HealthDevelopment";
import ProfessionalLineChart from "../../components/ProfessionalLineChart";
import HealthTile,{CoachSpark} from "../../components/HealthTile";
import HealthRecap from "../../components/HealthRecap";
import HealthSettings from "../../components/HealthSettings";
import InfoTip from "../../components/InfoTip";
import {GearIcon} from "../../components/TodaySettings";
import Link from "next/link";
import {api} from "../../lib/api";
import {useCachedQuery} from "../../lib/data-cache";
import {bi,useI18n} from "../../lib/i18n";
import {sourceLabel,measuredLabel,localDate} from "../../lib/sources";
import {HEALTH_METRICS,HEALTH_PERIODS,normalizeHealth,overviewPrompt,summarize,tileColumns,type HealthPrefs,type MetricDef} from "../../lib/healthInsights";

type Vo2Data={running:any[];cycling:any[];latest?:{running?:number|null;cycling?:number|null}};
type BodyLatest={measured_at_by_metric?:Record<string,string>;weight_kg?:number;height_cm?:number;bmi?:number;body_fat_percent?:number;body_water_percent?:number;muscle_mass_kg?:number;bone_mass_kg?:number;sources?:Record<string,string>};
const rowsOf=(def:MetricDef,data:any)=>def.source==="sleep"?data.sleep:def.source==="hrv"?data.hrv:data.health;
function bodyMetricSource(body:BodyLatest|undefined,key:string){return [sourceLabel(body?.sources?.[key]),measuredLabel(body?.measured_at_by_metric?.[key])].filter(Boolean).join(" · ")}

export default function Health(){
  const{lang}=useI18n(),de=lang==="de";
  const prefsQuery=useCachedQuery<any>("/settings/health-layout",60000);
  const [saved,setSaved]=useState<HealthPrefs|null>(null),[settingsOpen,setSettingsOpen]=useState(false),[periodChoice,setPeriodChoice]=useState<string|null>(null);
  const prefs=saved??normalizeHealth(prefsQuery.data);
  useEffect(()=>{setSaved(null)},[prefsQuery.data]);
  const loaded=!!prefsQuery.data||!!prefsQuery.error;
  const period=periodChoice??prefs.period;
  const p=HEALTH_PERIODS.find(x=>x.id===period)??HEALTH_PERIODS[1];
  const periodLabel=de?p.longDe:p.longEn;
  const suffix=p.days===0?"?all=true":`?days=${p.days}`;
  const shown=(k:string)=>loaded&&!prefs.hidden.includes(k);
  const rangeQuery=useCachedQuery<any>(loaded?`/health/range${suffix}`:null);
  const devQuery=useCachedQuery<any>(shown("development")?`/health/development${suffix}`:null,60000);
  const data=rangeQuery.data??{health:[],sleep:[],hrv:[],body:[],body_latest:null};
  const development=devQuery.data,vo2=(development?.vo2_display??{running:[],cycling:[]}) as Vo2Data;
  const metrics=useMemo(()=>prefs.metrics.map(k=>HEALTH_METRICS.find(m=>m.key===k)!).filter(Boolean),[prefs.metrics]);
  const summaries=useMemo(()=>Object.fromEntries(metrics.map(d=>[d.key,summarize(rowsOf(d,data),d)])),[metrics,data]);
  const loading=!rangeQuery.data&&!rangeQuery.error;

  const[manualOpen,setManualOpen]=useState(false),[manualSaving,setManualSaving]=useState(false),[manualError,setManualError]=useState("");
  const[manual,setManual]=useState<Record<string,string>>({measured_on:localDate(),weight_kg:"",height_cm:"",body_fat_percent:"",body_water_percent:"",muscle_mass_kg:"",bone_mass_kg:""});
  const body:BodyLatest|undefined=data.body_latest??undefined;
  function openManual(){setManual({measured_on:localDate(),weight_kg:"",height_cm:"",body_fat_percent:"",body_water_percent:"",muscle_mass_kg:"",bone_mass_kg:""});setManualError("");setManualOpen(true)}
  async function saveManual(){
    setManualSaving(true);setManualError("");
    try{const payload:any={measured_on:manual.measured_on};for(const key of ["weight_kg","height_cm","body_fat_percent","body_water_percent","muscle_mass_kg","bone_mass_kg"]){const raw=manual[key]?.trim();if(raw)payload[key]=Number(raw)}
      await api("/health/body/manual",{method:"PUT",body:JSON.stringify(payload)});await rangeQuery.refresh();setManualOpen(false)}
    catch(e){setManualError(e instanceof Error?e.message:String(e))}finally{setManualSaving(false)}
  }
  const bodyCards=[
    {label:bi(lang,"Gewicht","Weight"),key:"weight_kg",value:body?.weight_kg!=null?`${body.weight_kg.toFixed(1)} kg`:"—"},
    {label:bi(lang,"Körperfett","Body fat"),key:"body_fat_percent",value:body?.body_fat_percent!=null?`${body.body_fat_percent.toFixed(1)} %`:"—"},
    {label:bi(lang,"Muskelmasse","Muscle mass"),key:"muscle_mass_kg",value:body?.muscle_mass_kg!=null?`${body.muscle_mass_kg.toFixed(1)} kg`:"—"},
    {label:bi(lang,"Körperwasser","Body water"),key:"body_water_percent",value:body?.body_water_percent!=null?`${body.body_water_percent.toFixed(1)} %`:"—"},
    {label:bi(lang,"Knochenmasse","Bone mass"),key:"bone_mass_kg",value:body?.bone_mass_kg!=null?`${body.bone_mass_kg.toFixed(1)} kg`:"—"},
    {label:"BMI",key:"bmi",value:body?.bmi!=null?body.bmi.toFixed(1):"—"},
    {label:bi(lang,"Größe","Height"),key:"height_cm",value:body?.height_cm!=null?`${body.height_cm.toFixed(0)} cm`:"—"}
  ].filter(c=>c.value!=="—"||["weight_kg","body_fat_percent","height_cm"].includes(c.key));
  const summaryPrompt=overviewPrompt(metrics.map(def=>({def,s:summaries[def.key]})),lang,periodLabel);

  const blocks:Record<string,React.ReactNode>={
    overview:<section className="health-overview" aria-label={bi(lang,"Kennzahlen","Key figures")} style={{"--cols":tileColumns(metrics.length)} as React.CSSProperties}>{metrics.map(def=><HealthTile key={def.key} def={def} s={summaries[def.key]} lang={lang} periodLabel={periodLabel} loading={loading}/>)}</section>,
    trends:<section className="health-trends">{metrics.map(def=>{const rows=rowsOf(def,data)??[];return <div className="card health-chart" key={def.key}><div className="health-chart-head"><h3>{def.label[lang]}</h3><InfoTip label={bi(lang,`Was ist ${def.label.de}?`,`What is ${def.label.en}?`)} text={def.info[lang]}/></div><ProfessionalLineChart height={200} series={[{label:def.label[lang],points:rows.map((x:any)=>({date:x.date,label:x.date,value:x[def.field]!=null?Number(x[def.field])*(def.scale??1):null})),unit:def.unit||undefined,decimals:def.digits}]}/></div>})}</section>,
    development:development?<HealthDevelopment data={development} vo2={vo2} lang={lang} periodLabel={periodLabel}/>:<section className="card loading-panel" aria-busy={!devQuery.error}><p>{devQuery.error?bi(lang,"Die Entwicklung konnte nicht geladen werden.","Progress could not be loaded."):bi(lang,"Wird geladen …","Loading …")}</p>{devQuery.error?<button type="button" className="ghost compact" onClick={()=>void devQuery.refresh()}>{bi(lang,"Erneut versuchen","Try again")}</button>:<span className="metric-skeleton"/>}</section>,
    body:<section className="card body-composition-card"><div className="health-section-head"><div><h2>{bi(lang,"Körperwerte","Body")}</h2><span className="period-badge">{bi(lang,"Aktuell","Current")}</span><InfoTip label={bi(lang,"Woher kommen die Körperwerte?","Where do the body values come from?")} text={bi(lang,"Aus deiner Waage, Garmin, SparkyFitness oder deinen eigenen Einträgen. Ein eigener Eintrag gilt, bis eine neuere Messung kommt.","From your scale, Garmin, SparkyFitness or your own entries. Your entry applies until a newer measurement arrives.")}/></div><button type="button" className="ghost" onClick={openManual}>{bi(lang,"Eintragen","Add")}</button></div><div className="body-metric-grid">{bodyCards.map(item=><div className="body-metric" key={item.key}><small>{item.label}</small><strong>{item.value}</strong><span>{body?.[item.key as keyof BodyLatest]!=null?bodyMetricSource(body,item.key):bi(lang,"Keine Daten","No data")}</span></div>)}</div>{(data.body??[]).some((x:any)=>x.weight_kg!=null)&&<div className="health-body-chart"><ProfessionalLineChart height={180} series={[{label:bi(lang,"Gewicht","Weight"),points:(data.body??[]).map((x:any)=>({date:String(x.measured_at??"").slice(0,10),label:String(x.measured_at??"").slice(0,10),value:x.weight_kg})),unit:"kg",decimals:1}]}/></div>}{manualOpen&&<div className="manual-body-editor"><div className="manual-body-intro"><strong>{bi(lang,"Körperwerte manuell pflegen","Maintain body metrics manually")}</strong><small>{bi(lang,"Ideal ohne Smart-Waage. Leere Felder werden nicht erfunden; ältere vorhandene Werte bleiben als Fallback verfügbar.","Useful without a smart scale. Empty fields are never invented; older known values remain available as fallback.")}</small></div><div className="manual-body-grid"><label>{bi(lang,"Datum","Date")}<input type="date" value={manual.measured_on} onChange={e=>setManual({...manual,measured_on:e.target.value})}/></label><label>{bi(lang,"Gewicht","Weight")}<span className="unit-input"><NumberInput allowEmpty min="20" max="500" step="0.1" placeholder={body?.weight_kg!=null?body.weight_kg.toFixed(1):""} value={manual.weight_kg} onValueChange={raw=>setManual({...manual,weight_kg:raw})}/><b>kg</b></span></label><label>{bi(lang,"Größe","Height")}<span className="unit-input"><NumberInput allowEmpty min="50" max="260" step="0.1" placeholder={body?.height_cm!=null?body.height_cm.toFixed(0):""} value={manual.height_cm} onValueChange={raw=>setManual({...manual,height_cm:raw})}/><b>cm</b></span></label><label>{bi(lang,"Körperfett","Body fat")}<span className="unit-input"><NumberInput allowEmpty min="1" max="75" step="0.1" placeholder={body?.body_fat_percent!=null?body.body_fat_percent.toFixed(1):""} value={manual.body_fat_percent} onValueChange={raw=>setManual({...manual,body_fat_percent:raw})}/><b>%</b></span></label><label>{bi(lang,"Körperwasser","Body water")}<span className="unit-input"><NumberInput allowEmpty min="10" max="90" step="0.1" placeholder={body?.body_water_percent!=null?body.body_water_percent.toFixed(1):""} value={manual.body_water_percent} onValueChange={raw=>setManual({...manual,body_water_percent:raw})}/><b>%</b></span></label><label>{bi(lang,"Muskelmasse","Muscle mass")}<span className="unit-input"><NumberInput allowEmpty min="1" max="300" step="0.1" placeholder={body?.muscle_mass_kg!=null?body.muscle_mass_kg.toFixed(1):""} value={manual.muscle_mass_kg} onValueChange={raw=>setManual({...manual,muscle_mass_kg:raw})}/><b>kg</b></span></label><label>{bi(lang,"Knochenmasse","Bone mass")}<span className="unit-input"><NumberInput allowEmpty min="0.1" max="30" step="0.1" placeholder={body?.bone_mass_kg!=null?body.bone_mass_kg.toFixed(1):""} value={manual.bone_mass_kg} onValueChange={raw=>setManual({...manual,bone_mass_kg:raw})}/><b>kg</b></span></label></div>{manualError&&<div className="status-bad">{manualError}</div>}<div className="manual-body-actions"><button type="button" className="ghost" onClick={()=>setManualOpen(false)}>{bi(lang,"Abbrechen","Cancel")}</button><button type="button" className="primary" disabled={manualSaving} onClick={()=>void saveManual()}>{manualSaving?bi(lang,"Speichert…","Saving…"):bi(lang,"Körperwerte speichern","Save body metrics")}</button></div></div>}</section>,
    coverage:<section className="card data-quality-card"><div className="health-section-head"><div><h2>{bi(lang,"Datenabdeckung","Data coverage")}</h2><InfoTip label={bi(lang,"Was zeigt die Datenabdeckung?","What does coverage show?")} text={bi(lang,"Wie viele Tage im Zeitraum Werte haben. Fehlende Tage bleiben leer und werden nie als Null gezählt.","How many days in the period have values. Missing days stay empty and are never counted as zero.")}/></div></div><div className="coverage-pills"><span><strong>{data.health?.length??0}</strong>{bi(lang,"Tage","days")}</span><span><strong>{data.sleep?.length??0}</strong>{bi(lang,"Nächte","nights")}</span><span><strong>{data.hrv?.length??0}</strong>HRV</span><span><strong>{data.body?.length??0}</strong>{bi(lang,"Körpermessungen","body readings")}</span><span><strong>{(vo2.running?.length??0)+(vo2.cycling?.length??0)}</strong>VO₂max</span></div></section>,
  };

  return <AppShell>
    <div className="health-v2">
      <header className="health-header">
        <div className="health-header-copy"><span className="eyebrow">{bi(lang,"Erholung & Körper","Recovery & body")}</span><h1>{bi(lang,"Gesundheit","Health")}</h1></div>
        <div className="health-header-tools">
          <div className="health-periods" role="radiogroup" aria-label={bi(lang,"Zeitraum","Period")}>{HEALTH_PERIODS.map(x=><button key={x.id} type="button" role="radio" aria-checked={period===x.id} className={period===x.id?"active":""} onClick={()=>setPeriodChoice(x.id)}>{de?x.de:x.en}</button>)}</div>
          <HealthRecap lang={lang}/>
          <Link prefetch={false} className="health-coach-button" href={`/coach?prompt=${encodeURIComponent(summaryPrompt)}`} title={bi(lang,"Zusammenfassung vom Coach","Summary from the coach")}><CoachSpark/><span>{bi(lang,"Einordnen","Assess")}</span></Link>
          <button type="button" className="today-gear" onClick={()=>setSettingsOpen(true)} aria-label={bi(lang,"Gesundheit anpassen","Customize health")} title={bi(lang,"Gesundheit anpassen","Customize health")}><GearIcon/><span>{bi(lang,"Anpassen","Customize")}</span></button>
        </div>
      </header>
      {rangeQuery.error&&<div className="notice card" role="alert">{bi(lang,"Die Werte konnten nicht geladen werden.","Values could not be loaded.")} <button type="button" className="ghost compact" onClick={()=>void rangeQuery.refresh()}>{bi(lang,"Erneut versuchen","Try again")}</button></div>}
      {prefs.order.filter(shown).map(k=><div key={k} className={`health-block health-block-${k}`} data-health-section={k}>{blocks[k]}</div>)}
    </div>
    <HealthSettings value={prefs} onSaved={v=>{setSaved(v);setPeriodChoice(null)}} lang={lang} open={settingsOpen} onClose={()=>setSettingsOpen(false)}/>
  </AppShell>
}
