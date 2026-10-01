"use client";

import {useMemo,useState} from "react";
import ProfessionalLineChart from "./ProfessionalLineChart";
import TrainingVolumeChart from "./TrainingVolumeChart";
import {bi} from "../lib/i18n";

type Props={data:any;vo2:any;lang:"de"|"en";periodLabel:string};

type Tab="overview"|"endurance"|"load"|"recovery";

const statusText=(status:string,lang:"de"|"en")=>{
  const de:{[key:string]:string}={rising:"steigend",falling:"sinkend",stable:"stabil",unknown:"noch offen"};
  const en:{[key:string]:string}={rising:"rising",falling:"falling",stable:"stable",unknown:"not enough data"};
  return (lang==="de"?de:en)[status]??status;
};
const arrow=(status:string)=>status==="rising"?"↗":status==="falling"?"↘":status==="stable"?"→":"·";
const pace=(v:number)=>{const m=Math.floor(v),s=Math.round((v-m)*60);return `${m}:${String(s).padStart(2,"0")}`};

export default function HealthDevelopment({data,vo2,lang,periodLabel}:Props){
  const[tab,setTab]=useState<Tab>("overview");
  const summary=data?.summary??{},eff=data?.efficiency??{},changes=Array.isArray(data?.changes)?data.changes:[];
  const bestEff=summary.efficiency??{};
  const vo2Series=useMemo(()=>{
    const make=(sport:"running"|"cycling",label:string)=>{
      const rows=Array.isArray(vo2?.[sport])?vo2[sport]:[];
      if(!rows.length)return null;
      return {label,points:rows.map((p:any)=>({date:p.date,label:p.date,value:Number(p.value)})),unit:"ml/kg/min",decimals:1,dashed:rows.every((p:any)=>p.measurement_kind==="estimated")};
    };
    return [make("running",bi(lang,"Laufen","Running")),make("cycling",bi(lang,"Radfahren","Cycling"))].filter(Boolean) as any[];
  },[vo2,lang]);
  const loadRows=Array.isArray(data?.load_recovery)?data.load_recovery:[];
  const loadSeries=[{label:data?.load_basis==="garmin_training_load"?"Garmin Load":bi(lang,"Trainingsminuten","Training minutes"),points:loadRows.map((x:any)=>({date:x.date,label:x.label,value:x.load})),unit:data?.load_basis==="garmin_training_load"?"":"min",decimals:0}];
  const recoverySeries=[
    {label:"HRV",points:loadRows.map((x:any)=>({date:x.date,label:x.label,value:x.hrv})),unit:"ms",decimals:0},
    {label:bi(lang,"Ruhepuls","Resting HR"),points:loadRows.map((x:any)=>({date:x.date,label:x.label,value:x.resting_hr})),unit:"bpm",decimals:0,axis:"right" as const},
  ];
  const loadRecoverySeries=[
    {label:data?.load_basis==="garmin_training_load"?"Garmin Load":bi(lang,"Trainingsminuten","Training minutes"),points:loadRows.map((x:any)=>({date:x.date,label:x.label,value:x.load})),unit:data?.load_basis==="garmin_training_load"?"":"min",decimals:0},
    {label:"HRV",points:loadRows.map((x:any)=>({date:x.date,label:x.label,value:x.hrv})),unit:"ms",decimals:0,axis:"right" as const},
  ];
  const tabs:[Tab,string][]=[["overview",bi(lang,"Überblick","Overview")],["endurance",bi(lang,"Ausdauer","Endurance")],["load",bi(lang,"Belastung","Load")],["recovery",bi(lang,"Erholung","Recovery")]];
  const effLabel=bestEff?.available?(bestEff.sport==="running"?bi(lang,"Lauf-Effizienz","Run efficiency"):bi(lang,"Rad-Effizienz","Cycling efficiency")):bi(lang,"Effizienz","Efficiency");
  const effValue=bestEff?.available&&bestEff.change_percent!=null?`${bestEff.change_percent>0?"+":""}${bestEff.change_percent.toFixed(1)} %`:"—";
  const load=summary.load??{};
  const cards=[
    {label:bi(lang,"Fitnessentwicklung","Fitness trend"),value:`${arrow(summary.fitness)} ${statusText(summary.fitness,lang)}`,note:bi(lang,"Aus VO₂max, Effizienz und Ruhepuls – ohne künstlichen Gesamtscore.","Based on VO₂ max, efficiency and resting HR – no synthetic total score.")},
    {label:bi(lang,"Trainingsbelastung","Training load"),value:`${arrow(load.status)} ${statusText(load.status,lang)}`,note:load.change_percent!=null?`${load.change_percent>0?"+":""}${load.change_percent.toFixed(1)} % · ${load.basis==="garmin_training_load"?"Garmin Load":bi(lang,"Trainingsminuten","training minutes")}`:bi(lang,"Noch nicht genug Vergleichsdaten","Not enough comparison data")},
    {label:effLabel,value:effValue,note:bestEff?.available?`${bi(lang,"vergleichbare HF","comparable HR")} ${bestEff.hr_band?.[0]??"—"}–${bestEff.hr_band?.[1]??"—"} bpm`:bi(lang,"Mindestens 3 vergleichbare Einheiten nötig","At least 3 comparable sessions required")},
    {label:bi(lang,"Erholungstrend","Recovery trend"),value:`${arrow(summary.recovery)} ${statusText(summary.recovery,lang)}`,note:bi(lang,"HRV und Ruhepuls im gewählten Zeitraum","HRV and resting HR in selected period")},
  ];

  return <section className="card health-development-card">
    <div className="section-heading health-development-heading"><div><span className="eyebrow">TRAINING & DEVELOPMENT</span><h2>{bi(lang,"Training & Entwicklung","Training & development")} · {periodLabel}</h2><p>{bi(lang,"Nicht nur VO₂max: Trainingsvolumen, Effizienz, Belastung und Erholung werden gemeinsam betrachtet. Details bleiben hinter Tabs, damit die Seite ruhig bleibt.","Beyond VO₂ max: volume, efficiency, load and recovery are viewed together. Details stay behind tabs to keep the page calm.")}</p></div><span className="period-badge">{summary.sessions??0} {bi(lang,"Einheiten","sessions")}</span></div>
    <div className="health-development-tabs" role="tablist">{tabs.map(([key,label])=><button key={key} type="button" className={tab===key?"active":""} onClick={()=>setTab(key)}>{label}</button>)}</div>

    {tab==="overview"&&<div className="health-development-pane">
      <div className="development-kpis">{cards.map(card=><div className="development-kpi" key={card.label}><small>{card.label}</small><strong>{card.value}</strong><span>{card.note}</span></div>)}</div>
      <div className="health-insight-grid">
        <div className="insight-chart-card"><div className="insight-title"><div><span className="eyebrow">VOLUME</span><h3>{bi(lang,"Trainingsumfang","Training volume")}</h3></div><strong>{Math.round(summary.minutes??0)} min</strong></div><TrainingVolumeChart rows={data?.volume??[]} lang={lang}/></div>
        <div className="insight-chart-card"><div className="insight-title"><div><span className="eyebrow">RECOVERY</span><h3>{bi(lang,"Belastung & Erholung","Load & recovery")}</h3></div></div><ProfessionalLineChart series={loadRecoverySeries} ariaLabel={bi(lang,"Trainingsbelastung und HRV Verlauf","Training load and HRV trend")}/></div>
      </div>
      <ChangePanel changes={changes} lang={lang}/>
    </div>}

    {tab==="endurance"&&<div className="health-development-pane">
      <div className="insight-chart-card wide"><div className="insight-title"><div><span className="eyebrow">VO₂MAX</span><h3>{bi(lang,"Ausdauerentwicklung","Endurance development")}</h3><p>{bi(lang,"Importierte Werte werden bevorzugt. Wenn kein Wert vorliegt, kann PenguCoach konservativ schätzen; die Linie ist dann gestrichelt und klar als Schätzung markiert.","Imported values take priority. If none exist, PenguCoach can estimate conservatively; estimated lines are dashed and clearly labelled.")}</p></div><Vo2Latest vo2={vo2} lang={lang}/></div><ProfessionalLineChart series={vo2Series} ariaLabel="VO2 max history"/></div>
      <div className="health-insight-grid">
        <EfficiencyCard item={eff.running} sport="running" lang={lang}/>
        <EfficiencyCard item={eff.cycling} sport="cycling" lang={lang}/>
      </div>
      <div className="estimate-note"><strong>{bi(lang,"Zur VO₂max-Schätzung","About VO₂ max estimation")}</strong><span>{bi(lang,"Das ist eine Trainingsschätzung, keine Spiroergometrie. Laufen wird nur aus ausreichend langen, relativ flachen Einheiten mit Herzfrequenz geschätzt. Radfahren wird nur geschätzt, wenn Leistung (Watt), Körpergewicht und Herzfrequenz vorhanden sind; reine Geschwindigkeit reicht bewusst nicht.","This is a training estimate, not a lab test. Running uses sufficiently long, relatively flat sessions with heart rate. Cycling is estimated only when power, body mass and heart rate are available; speed alone is intentionally not used.")}</span></div>
    </div>}

    {tab==="load"&&<div className="health-development-pane">
      <div className="health-insight-grid">
        <div className="insight-chart-card"><div className="insight-title"><div><span className="eyebrow">LOAD</span><h3>{bi(lang,"Belastungsverlauf","Load trend")}</h3><p>{data?.load_basis==="garmin_training_load"?bi(lang,"Garmin Training Load wird verwendet, wenn die Datenabdeckung ausreicht.","Garmin Training Load is used when coverage is sufficient."):bi(lang,"Fallback auf Trainingsminuten – kein erfundener Belastungsscore.","Fallback to training minutes – no invented load score.")}</p></div></div><ProfessionalLineChart series={loadSeries} ariaLabel={bi(lang,"Trainingsbelastung Verlauf","Training load trend")}/></div>
        <div className="insight-chart-card"><div className="insight-title"><div><span className="eyebrow">SPORT MIX</span><h3>{bi(lang,"Sportartenmix","Sport mix")}</h3></div></div><SportMix rows={data?.sport_mix??[]} lang={lang}/></div>
      </div>
      <div className="insight-chart-card wide"><div className="insight-title"><div><span className="eyebrow">VOLUME</span><h3>{bi(lang,"Volumen nach Sportart","Volume by sport")}</h3></div></div><TrainingVolumeChart rows={data?.volume??[]} lang={lang}/></div>
    </div>}

    {tab==="recovery"&&<div className="health-development-pane">
      <div className="insight-chart-card wide"><div className="insight-title"><div><span className="eyebrow">RECOVERY</span><h3>{bi(lang,"HRV & Ruhepuls","HRV & resting heart rate")}</h3><p>{bi(lang,"Zwei Achsen, damit beide Größen lesbar bleiben. Fehlende Tage werden nicht als Null gezeichnet.","Two axes keep both metrics readable. Missing days are never plotted as zero.")}</p></div></div><ProfessionalLineChart series={recoverySeries} ariaLabel={bi(lang,"Erholungsverlauf","Recovery trend")}/></div>
      <ChangePanel changes={changes.filter((x:any)=>["hrv","resting_hr"].includes(x.key))} lang={lang}/>
    </div>}
  </section>;
}

function Vo2Latest({vo2,lang}:{vo2:any;lang:"de"|"en"}){
  const confidence=(value:string|undefined)=>({high:bi(lang,"gute Datenbasis","strong data basis"),medium:bi(lang,"mittlere Datenbasis","moderate data basis"),low:bi(lang,"begrenzte Datenbasis","limited data basis")}[value??""]??value??"");
  return <div className="vo2-latest-modern">{(["running","cycling"] as const).map(sport=>{const meta=vo2?.latest_meta?.[sport],estimate=meta?.measurement_kind==="estimated";return <div key={sport}><small>{sport==="running"?bi(lang,"Laufen","Running"):bi(lang,"Rad","Cycling")}</small><strong>{vo2?.latest?.[sport]??"—"}</strong><span>{meta?(estimate?`${bi(lang,"geschätzt","estimated")} · ${confidence(meta.confidence)}`:bi(lang,"importiert","imported")):bi(lang,"kein Wert","no value")}</span><em>ml/kg/min</em></div>})}</div>;
}

function EfficiencyCard({item,sport,lang}:{item:any;sport:"running"|"cycling";lang:"de"|"en"}){
  const title=sport==="running"?bi(lang,"Lauf-Effizienz","Running efficiency"):bi(lang,"Rad-Effizienz","Cycling efficiency");
  if(!item?.available)return <div className="insight-chart-card"><div className="insight-title"><div><span className="eyebrow">EFFICIENCY</span><h3>{title}</h3><p>{bi(lang,"Noch nicht genug vergleichbare Einheiten mit Herzfrequenzdaten.","Not enough comparable sessions with heart-rate data yet.")}</p></div></div><div className="pro-chart-empty">—</div></div>;
  const points=(item.points??[]).map((x:any)=>({date:x.date,label:x.label,value:x.value}));
  const unit=item.metric==="pace_min_km"?"min/km":"W";
  const displayChange=item.change_percent!=null?`${item.change_percent>0?"+":""}${item.change_percent.toFixed(1)} %`:"—";
  return <div className="insight-chart-card"><div className="insight-title"><div><span className="eyebrow">EFFICIENCY</span><h3>{title}</h3><p>{bi(lang,"Nur Einheiten mit ähnlicher Ø Herzfrequenz","Only sessions with similar average HR")} · {item.hr_band?.[0]}–{item.hr_band?.[1]} bpm</p></div><strong className={item.change_percent>0?"trend-good":item.change_percent<0?"trend-bad":""}>{displayChange}</strong></div><ProfessionalLineChart series={[{label:item.metric==="pace_min_km"?bi(lang,"Pace","Pace"):bi(lang,"Leistung","Power"),points,unit,decimals:item.metric==="pace_min_km"?2:0}]} ariaLabel={title}/>{item.metric==="pace_min_km"&&points.length>0&&<div className="efficiency-foot">{bi(lang,"Letzter Wert","Latest")}: <b>{pace(points[points.length-1].value)} min/km</b></div>}</div>;
}

function ChangePanel({changes,lang}:{changes:any[];lang:"de"|"en"}){
  if(!changes.length)return null;
  const labels:{[key:string]:[string,string]}={vo2:["VO₂max","VO₂ max"],efficiency:["Effizienz","Efficiency"],resting_hr:["Ruhepuls","Resting HR"],hrv:["HRV","HRV"],volume:["Trainingsvolumen","Training volume"]};
  return <div className="change-panel"><div><span className="eyebrow">CHANGE</span><h3>{bi(lang,"Was hat sich verändert?","What changed?")}</h3><p>{bi(lang,"Vergleich zwischen früherem und aktuellem Teil des gewählten Zeitraums.","Comparison between the earlier and recent part of the selected period.")}</p></div><div className="change-list">{changes.map(row=>{const positive=row.positive_when==="up"?row.delta>0:row.positive_when==="down"?row.delta<0:null;return <div key={row.key}><span>{labels[row.key]?.[lang==="de"?0:1]??row.label}{row.key==="vo2"&&row.measurement_kind==="estimated"?` · ${bi(lang,"geschätzt","estimated")}`:""}</span><strong className={positive===true?"trend-good":positive===false?"trend-bad":""}>{row.delta>0?"+":""}{row.delta} {row.unit}</strong><small>{arrow(row.trend)} {statusText(row.trend,lang)}</small></div>})}</div></div>;
}

function SportMix({rows,lang}:{rows:any[];lang:"de"|"en"}){
  const labels:{[key:string]:[string,string]}={running:["Laufen","Running"],cycling:["Radfahren","Cycling"],strength:["Kraft","Strength"],mobility:["Mobility","Mobility"],swimming:["Schwimmen","Swimming"],walking:["Gehen/Wandern","Walk/Hike"],other:["Sonstiges","Other"]};
  if(!rows.length)return <div className="pro-chart-empty">—</div>;
  return <div className="sport-mix-modern">{rows.slice(0,7).map((row:any,i:number)=><div key={row.sport}><div><span>{labels[row.sport]?.[lang==="de"?0:1]??row.sport}</span><b>{row.percent}%</b></div><div className="sport-mix-track"><i className={`pro-series-bg-${i%4}`} style={{width:`${Math.max(2,row.percent)}%`}}/></div><small>{Math.round(row.minutes)} min</small></div>)}</div>;
}
