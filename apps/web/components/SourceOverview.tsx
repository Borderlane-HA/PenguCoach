"use client";
import {useEffect,useState} from "react";
import {api} from "../lib/api";
import {bi,useI18n} from "../lib/i18n";
export default function SourceOverview(){
 const {lang}=useI18n();const [data,setData]=useState<any>(null);
 useEffect(()=>{api<any>("/health/sources").then(setData).catch(()=>{})},[]);
 return <div className="source-overview"><span>{bi(lang,"Deine Verbindungen","Your connections")}</span>{data?.connections?.map((s:any)=><a key={s.source} href={`/settings/${s.source}`} className={s.connected?"source-chip connected":"source-chip"}><i/><strong>{s.name}</strong><small>{s.connected?bi(lang,"Verbunden","Connected"):bi(lang,"Einrichten","Set up")}</small></a>)}<a href="/health" className="source-chip">{bi(lang,"Manuelle Körperwerte","Manual body metrics")} ↗</a></div>
}
