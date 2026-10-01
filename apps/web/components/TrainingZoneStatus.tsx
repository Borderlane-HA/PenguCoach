"use client";

import {useEffect,useState} from "react";
import {api} from "../lib/api";
import {bi,useI18n} from "../lib/i18n";

type AnyObj=Record<string,any>;

export default function TrainingZoneStatus({compact=false}:{compact?:boolean}){
  const{lang}=useI18n();
  const[data,setData]=useState<AnyObj|null>(null);
  useEffect(()=>{const load=()=>void api<AnyObj>("/garmin/zones").then(setData).catch(()=>setData(null));load();const timer=window.setInterval(load,60000);return()=>window.clearInterval(timer)},[]);
  if(!data?.connected)return null;
  const hr=Number(data?.heart_rate?.profile_count??0),power=Number(data?.power?.profile_count??0);
  const synced=Boolean(data?.synced);
  const when=data?.synced_at?new Date(data.synced_at).toLocaleString(lang.startsWith("de")?"de-DE":"en-GB",{dateStyle:"short",timeStyle:"short"}):"";
  return <div className={`training-zone-status ${compact?"compact":""} ${synced?"synced":"missing"}`}>
    <div className="training-zone-status-head"><span className="zone-sync-dot"/><div><strong>{bi(lang,"Garmin Trainingszonen","Garmin training zones")}</strong><small>{synced?bi(lang,"Synchronisiert und für die KI verfügbar","Synced and available to AI"):bi(lang,"Noch nicht synchronisiert","Not synced yet")}</small></div></div>
    {synced?<><div className="zone-sync-pills"><span>♥ {bi(lang,"HF","HR")} · {hr} {bi(lang,"Profile","profiles")}</span><span>⚡ {bi(lang,"Leistung","Power")} · {power} {bi(lang,"Profile","profiles")}</span></div><small className="zone-sync-note">{compact?bi(lang,"Letzter Zonen-Sync","Last zone sync"):bi(lang,"Aktivitätsanalyse und Trainingsplanung verwenden die sportartspezifischen Garmin-Zonen. Zeit in Zonen wird aus FIT-Daten lokal berechnet, wenn verfügbar.","Activity analysis and training planning use sport-specific Garmin zones. Time in zones is calculated locally from FIT data when available.")}{when?` · ${when}`:""}</small></>:<small className="zone-sync-note">{bi(lang,"Starte einmal Garmin → Synchronisieren. Danach werden Herzfrequenz- und Leistungszonen hier angezeigt.","Run Garmin → Sync once. Heart-rate and power zones will then appear here.")}</small>}
  </div>
}
