"use client";
import Link from "next/link";
import {useCachedQuery} from "../lib/data-cache";
import {bi,useI18n} from "../lib/i18n";
export default function SourceOverview(){
 const {lang}=useI18n();const {data}=useCachedQuery<any>("/health/sources",60000);
 return <div className="source-overview"><span>{bi(lang,"Deine Verbindungen","Your connections")}</span>{data?.connections?.map((s:any)=><Link prefetch={false} key={s.source} href={`/settings/${s.source}`} className={s.connected?"source-chip connected":"source-chip"}><i/><strong>{s.name}</strong><small>{s.connected?bi(lang,"Verbunden","Connected"):bi(lang,"Einrichten","Set up")}</small></Link>)}<Link prefetch={false} href="/health" className="source-chip">{bi(lang,"Manuelle Körperwerte","Manual body metrics")} ↗</Link></div>
}
