"use client";
import {useEffect,useState} from "react";
import {api} from "../lib/api";
import {bi,useI18n} from "../lib/i18n";
import {sourceLabel} from "../lib/sources";
export type ContextData={training:boolean;zones:boolean;sleep_hrv:boolean;recovery:boolean;daily_activity:boolean;hydration:boolean;body:boolean};
export const defaultContext:ContextData={training:true,zones:true,sleep_hrv:true,recovery:true,daily_activity:true,hydration:true,body:true};
const options:[keyof ContextData,string,string,string,string][]=[
 ["training","Aktivitäten","Activities","Einheiten, Umfang & Belastung","Sessions, volume & load"],
 ["sleep_hrv","Schlaf & HRV","Sleep & HRV","Nächte & Erholungstrends","Nights & recovery trends"],
 ["recovery","Erholung & Stress","Recovery & stress","Ruhepuls, Stress & weitere Messwerte","Resting HR, stress & other readings"],
 ["daily_activity","Alltagsbewegung","Daily movement","Schritte, Strecke & aktive Kalorien","Steps, distance & active calories"],
 ["hydration","Trinkmenge","Water intake","Erfasste Menge & vorhandenes Tagesziel","Recorded intake & available daily goal"],
 ["body","Körperwerte","Body metrics","Aktuelles Gewicht, Größe & Zusammensetzung","Latest weight, height & composition"],
 ["zones","Trainingszonen","Training zones","Nur tatsächlich vorhandene Zonengrenzen","Only available zone boundaries"],
];
export default function ContextPicker({value,onChange,days,disabled=false}:{value:ContextData;onChange:(value:ContextData)=>void;days:number;disabled?:boolean}){
 const {lang}=useI18n();const [coverage,setCoverage]=useState<any>(null),[error,setError]=useState(false);
 useEffect(()=>{let active=true;setCoverage(null);setError(false);if(days>0)api<any>(`/coach/context-preview?days=${days}`).then(x=>{if(active)setCoverage(x)}).catch(()=>{if(active)setError(true)});return()=>{active=false}},[days]);
 const selected=options.filter(([key])=>value[key]);
 return <details className="context-picker"><summary><span className="context-picker-symbol">◎</span><span><strong>{bi(lang,"Meine Daten für die KI","My data for AI")}</strong><small>{days===0?bi(lang,"Kontext ausgeschaltet","Context disabled"):`${selected.length} / ${options.length} ${bi(lang,"Bereiche ausgewählt","categories selected")} · ${days} ${bi(lang,"Tage","days")}`}</small></span><span className="context-picker-toggle">{bi(lang,"Anpassen","Customize")} ⌄</span></summary><div className="context-picker-content"><p>{bi(lang,"Du entscheidest, welche Bereiche in diese Anfrage einfließen. Verwendet werden nur vorhandene Daten. Fehlende Werte werden nicht geschätzt.","Choose which categories to include in this request. Only available data is used. Missing readings are not estimated.")}</p><div className="context-presets"><button type="button" className="ghost compact" disabled={disabled||days===0} onClick={()=>onChange({...defaultContext,body:false,hydration:false,daily_activity:false})}>{bi(lang,"Training & Erholung","Training & recovery")}</button><button type="button" className="ghost compact" disabled={disabled||days===0} onClick={()=>onChange({...defaultContext})}>{bi(lang,"Alle verfügbaren Bereiche","All available categories")}</button></div><div className="context-data-grid">{options.map(([key,de,en,descDe,descEn])=><label key={key}><input type="checkbox" checked={value[key]} disabled={disabled||days===0} onChange={e=>onChange({...value,[key]:e.target.checked})}/><span><b>{bi(lang,de,en)}</b><small>{bi(lang,descDe,descEn)}</small>{coverage&&<em>{coverage.categories?.[key]?.count??0} {bi(lang,"Datensätze","records")}{coverage.categories?.[key]?.sources?.length?` · ${coverage.categories[key].sources.map((s:string)=>sourceLabel(s,lang)).join(" + ")}`:""}</em>}</span></label>)}</div>{days>0&&error&&<small role="status">{bi(lang,"Datenübersicht konnte nicht geladen werden. Deine Auswahl bleibt gültig.","Data overview could not be loaded. Your selection remains valid.")}</small>}<small>{bi(lang,"Körperwerte: jeweils letzte bekannte Messung. Zeitraum: Trainings- und Tagesdaten. Trinkmenge ist eine Aufzeichnung, keine Aussage zum Flüssigkeitsbedarf.","Body metrics: latest known measurement per field. Period: workouts and daily data. Intake is a record, not an assessment of fluid needs.")}</small></div></details>
}
