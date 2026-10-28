"use client";
// Animated health story ("Gesundheits-Rückblick"): sleep, heart, steps and energy for a period, compared with the period before.
import {useCallback,useEffect,useMemo,useRef,useState} from "react";
import Link from "next/link";
import {api} from "../lib/api";
import {bi,type Lang} from "../lib/i18n";
import {CountUp} from "./ActivityRecap";
import {display,metricDef,overviewPrompt,recapSlides,sparkPath,summarize,type MetricDef,type Summary} from "../lib/healthInsights";

type O=Record<string,any>;
const PERIODS=[{days:7,de:"Woche",en:"Week"},{days:30,de:"Monat",en:"Month"},{days:90,de:"3 Monate",en:"3 months"},{days:365,de:"Jahr",en:"Year"}];
const DURATION:Record<string,number>={intro:4500,sleep:6500,heart:7000,steps:6500,energy:6500};
const KEYS=["sleep","hrv","resting_hr","steps","body_battery_high","stress"];

function rowsFor(def:MetricDef,data:O){return def.source==="sleep"?data.sleep:def.source==="hrv"?data.hrv:data.health}
function split(data:O,days:number){
  const cut=new Date();cut.setDate(cut.getDate()-days+1);const iso=cut.toISOString().slice(0,10);
  const part=(rows:O[]|undefined,now:boolean)=>(rows??[]).filter(r=>(String(r.date).slice(0,10)>=iso)===now);
  return {now:{health:part(data.health,true),sleep:part(data.sleep,true),hrv:part(data.hrv,true)},before:{health:part(data.health,false),sleep:part(data.sleep,false),hrv:part(data.hrv,false)}};
}

export default function HealthRecap({lang}:{lang:Lang}){
  const de=lang==="de";
  const [open,setOpen]=useState(false),[days,setDays]=useState(30),[raw,setRaw]=useState<O|null>(null),[loading,setLoading]=useState(false),[error,setError]=useState("");
  const [index,setIndex]=useState(0),[paused,setPaused]=useState(false),[progress,setProgress]=useState(0);
  const opener=useRef<HTMLButtonElement>(null),closer=useRef<HTMLButtonElement>(null),elapsed=useRef(0);
  useEffect(()=>{
    if(!open)return;let active=true;setLoading(true);setError("");setIndex(0);setProgress(0);elapsed.current=0;
    api<O>(`/health/range?days=${days*2}`).then(v=>{if(active)setRaw(v)}).catch(e=>{if(active)setError(e instanceof Error?e.message:String(e))}).finally(()=>{if(active)setLoading(false)});
    return()=>{active=false};
  },[open,days]);
  const view=useMemo(()=>{
    if(!raw)return null;const {now,before}=split(raw,days);
    const cur:Record<string,Summary>={},prev:Record<string,Summary>={};
    for(const k of KEYS){const d=metricDef(k)!;cur[k]=summarize(rowsFor(d,now),d);prev[k]=summarize(rowsFor(d,before),d)}
    return {cur,prev,dayCount:new Set([...now.health,...now.sleep,...now.hrv].map(r=>String(r.date).slice(0,10))).size};
  },[raw,days]);
  const list=view?recapSlides(view.cur):[],slide=list[Math.min(index,Math.max(0,list.length-1))];
  const go=useCallback((d:number)=>{elapsed.current=0;setProgress(0);setIndex(i=>Math.max(0,Math.min(list.length-1,i+d)))},[list.length]);
  useEffect(()=>{
    if(!open||!slide||slide==="finale"||paused||loading)return;
    let frame=0,last=performance.now();const total=DURATION[slide]??6500;
    const step=(now:number)=>{elapsed.current+=(now-last)/total;last=now;if(elapsed.current>=1){go(1);return}setProgress(elapsed.current);frame=requestAnimationFrame(step)};
    frame=requestAnimationFrame(step);return()=>cancelAnimationFrame(frame);
  },[open,slide,paused,loading,go]);
  useEffect(()=>{
    if(!open)return;closer.current?.focus();document.body.style.overflow="hidden";
    const key=(e:KeyboardEvent)=>{if(e.key==="Escape")setOpen(false);else if(e.key==="ArrowRight")go(1);else if(e.key==="ArrowLeft")go(-1);else if(e.key===" "&&!(e.target instanceof HTMLButtonElement)){e.preventDefault();setPaused(p=>!p)}};
    const hidden=()=>{if(document.visibilityState!=="visible")setPaused(true)};
    document.addEventListener("keydown",key);document.addEventListener("visibilitychange",hidden);
    return()=>{document.removeEventListener("keydown",key);document.removeEventListener("visibilitychange",hidden);document.body.style.overflow="";opener.current?.focus()};
  },[open,go]);
  const periodWord=(PERIODS.find(p=>p.days===days)??PERIODS[1])[de?"de":"en"];
  const versus=(k:string)=>{
    if(!view)return null;const a=view.cur[k],b=view.prev[k],d=metricDef(k)!;
    if(a.avg==null||b.avg==null||!b.count)return null;
    const diff=a.avg-b.avg,rel=Math.abs(diff)/Math.max(1e-9,Math.abs(b.avg));if(rel<.02)return <p className="recap-fact recap-delay">{bi(lang,"So stabil wie davor","As steady as before")}</p>;
    const good=(diff>0)===(d.better==="up");
    const amount=display(d,Math.abs(diff),lang);
    return <p className={`recap-fact recap-delay health-recap-change ${good?"good":"bad"}`}>{diff>0?"▲":"▼"} {amount} {bi(lang,"gegenüber davor","versus before")}</p>;
  };
  const line=(k:string)=>{const p=sparkPath(view?.cur[k].values.map(v=>v.value)??[],800,180,10);return p?<svg className="health-recap-line" viewBox="0 0 800 180" aria-hidden="true"><path d={p} pathLength={1} className="recap-route"/></svg>:null};
  function stageClick(e:React.MouseEvent<HTMLDivElement>){if((e.target as HTMLElement).closest("button,a"))return;const r=e.currentTarget.getBoundingClientRect();go(e.clientX-r.left<r.width*.3?-1:1)}

  function content(){
    if(loading&&!view)return <div className="recap-center"><span className="recap-loader" aria-hidden="true"/><p>{bi(lang,"Dein Gesundheits-Rückblick entsteht …","Building your health recap …")}</p></div>;
    if(error)return <div className="recap-center"><p>{error}</p></div>;
    if(!view||!list.length)return <div className="recap-center"><h2 className="recap-title">{bi(lang,"Noch zu wenig Daten","Not enough data yet")}</h2><p className="recap-sub">{bi(lang,"Wähle oben einen längeren Zeitraum.","Pick a longer period above.")}</p></div>;
    const c=view.cur;
    switch(slide){
      case "intro":return <div className="recap-slide recap-intro"><span className="recap-eyebrow">{bi(lang,"DEIN GESUNDHEITS-RÜCKBLICK","YOUR HEALTH RECAP")}</span><h2 className="recap-title">{bi(lang,`Dein ${periodWord}`,`Your ${periodWord.toLowerCase()}`)}</h2><div className="recap-hero"><CountUp value={view.dayCount} lang={lang}/></div><p className="recap-label">{bi(lang,"Tage mit Messwerten","days with readings")}</p></div>;
      case "sleep":return <div className="recap-slide"><span className="recap-eyebrow">{bi(lang,"SCHLAF","SLEEP")}</span><div className="recap-hero"><CountUp value={(c.sleep.avg??0)/3600} digits={1} lang={lang}/><span className="recap-unit">h</span></div><p className="recap-label">{bi(lang,"im Schnitt pro Nacht","per night on average")}</p>{versus("sleep")}{line("sleep")}</div>;
      case "heart":return <div className="recap-slide recap-split">{c.hrv.count>0&&<div><span className="recap-eyebrow">HRV</span><div className="recap-hero recap-hero-md"><CountUp value={c.hrv.avg??0} lang={lang}/><span className="recap-unit">ms</span></div>{versus("hrv")}</div>}{c.resting_hr.count>0&&<div><span className="recap-eyebrow">{bi(lang,"RUHEPULS","RESTING HR")}</span><div className="recap-hero recap-hero-md"><CountUp value={c.resting_hr.avg??0} lang={lang}/><span className="recap-unit">bpm</span></div>{versus("resting_hr")}</div>}{line(c.hrv.count?"hrv":"resting_hr")}</div>;
      case "steps":{const total=c.steps.values.reduce((s,v)=>s+v.value,0),max=Math.max(1,...c.steps.values.map(v=>v.value));return <div className="recap-slide"><span className="recap-eyebrow">{bi(lang,"SCHRITTE","STEPS")}</span><div className="recap-hero"><CountUp value={total} lang={lang} compactLarge/></div><p className="recap-label">{bi(lang,`≈ ${Math.round(total*0.75/1000).toLocaleString("de-DE")} km zu Fuß · Ø ${Math.round(c.steps.avg??0).toLocaleString("de-DE")} am Tag`,`≈ ${Math.round(total*0.75/1000).toLocaleString("en-GB")} km on foot · avg ${Math.round(c.steps.avg??0).toLocaleString("en-GB")} a day`)}</p>{versus("steps")}<div className="recap-bars" aria-hidden="true">{c.steps.values.slice(-60).map((v,n,a)=><i key={v.date} style={{height:`${Math.max(4,v.value/max*100)}%`,animationDelay:`${200+n*Math.min(40,1600/a.length)}ms`}}/>)}</div></div>}
      case "energy":return <div className="recap-slide recap-split">{c.body_battery_high.count>0&&<div><span className="recap-eyebrow">BODY BATTERY</span><div className="recap-hero recap-hero-md"><CountUp value={c.body_battery_high.avg??0} lang={lang}/></div><p className="recap-label">{bi(lang,"Ø Tageshoch","avg daily high")}</p>{versus("body_battery_high")}</div>}{c.stress.count>0&&<div><span className="recap-eyebrow">STRESS</span><div className="recap-hero recap-hero-md"><CountUp value={c.stress.avg??0} lang={lang}/></div><p className="recap-label">{(c.stress.avg??0)<25?bi(lang,"meist ruhig","mostly calm"):(c.stress.avg??0)<50?bi(lang,"im mittleren Bereich","moderate"):bi(lang,"eher hoch","rather high")}</p>{versus("stress")}</div>}</div>;
      default:{const items=KEYS.map(k=>({def:metricDef(k)!,s:c[k]})).filter(x=>x.s.count);
        return <div className="recap-slide"><span className="recap-eyebrow">{bi(lang,"DAS WAR DEIN ","THAT WAS YOUR ")}{periodWord.toUpperCase()}</span><h2 className="recap-title recap-title-sm">{bi(lang,"Auf einen Blick","At a glance")}</h2><div className="health-recap-grid">{items.map(({def,s},n)=><div key={def.key} style={{animationDelay:`${200+n*140}ms`}}><span>{def.label[lang]}</span><strong>{display(def,s.avg,lang)}</strong></div>)}</div><Link prefetch={false} className="health-recap-coach" href={`/coach?prompt=${encodeURIComponent(overviewPrompt(items,lang,bi(lang,`die letzten ${days} Tage`,`the last ${days} days`)))}`}>{bi(lang,"Mit dem Coach besprechen","Discuss with the coach")} →</Link></div>}
    }
  }
  return <>
    <button ref={opener} type="button" className="recap-trigger" onClick={()=>{setOpen(true);setPaused(false)}}><svg aria-hidden="true" viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M3 12a9 9 0 1 0 3-6.7"/><path d="M3 4v4h4"/><path d="M12 7v5l3 2"/></svg>{bi(lang,"Rückblick","Recap")}</button>
    {open&&<div className="recap-overlay health-recap" role="dialog" aria-modal="true" aria-label={bi(lang,"Gesundheits-Rückblick","Health recap")}>
      <div className="recap-top">
        <div className="recap-progress" aria-hidden="true">{list.map((s,n)=><i key={s}><b style={{width:`${n<index?100:n===index?progress*100:0}%`}}/></i>)}</div>
        <div className="recap-toolbar">
          <div className="recap-periods" role="radiogroup" aria-label={bi(lang,"Zeitraum","Period")}>{PERIODS.map(p=><button key={p.days} type="button" role="radio" aria-checked={days===p.days} className={days===p.days?"active":""} onClick={()=>setDays(p.days)}>{de?p.de:p.en}</button>)}</div>
          <div className="recap-tools">{slide&&slide!=="finale"&&<button type="button" className="recap-icon" aria-label={paused?bi(lang,"Fortsetzen","Resume"):bi(lang,"Pausieren","Pause")} onClick={()=>setPaused(p=>!p)}>{paused?"▶":"❚❚"}</button>}<button ref={closer} type="button" className="recap-icon" aria-label={bi(lang,"Schließen","Close")} onClick={()=>setOpen(false)}>✕</button></div>
        </div>
      </div>
      <div className="recap-stage" onClick={stageClick} key={`${days}-${slide}`}>{content()}</div>
      {list.length>1&&<div className="recap-nav"><button type="button" className="recap-icon" disabled={index===0} aria-label={bi(lang,"Zurück","Previous")} onClick={()=>go(-1)}>‹</button><span>{index+1} / {list.length}</span><button type="button" className="recap-icon" disabled={index>=list.length-1} aria-label={bi(lang,"Weiter","Next")} onClick={()=>go(1)}>›</button></div>}
    </div>}
  </>;
}
