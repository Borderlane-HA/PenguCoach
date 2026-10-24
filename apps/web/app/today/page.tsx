"use client";
// alpha.82 Today: compact header, freely arranged cards, settings behind one gear.
import {useEffect,useMemo,useRef,useState} from "react";
import Link from "next/link";
import AppShell from "../../components/AppShell";
import MetricCard from "../../components/MetricCard";
import StepGoalCard from "../../components/StepGoalCard";
import SparkLine from "../../components/SparkLine";
import Deferred from "../../components/Deferred";
import PersonalProgress from "../../components/PersonalProgress";
import CheckinAssistant from "../../components/CheckinAssistant";
import ReflectionAssistant from "../../components/ReflectionAssistant";
import TodayReadiness from "../../components/TodayReadiness";
import TodaySettings,{GearIcon} from "../../components/TodaySettings";
import {DayPhases,TrainingPreparation,TodayWeather} from "../../components/TodayJourney";
import {api} from "../../lib/api";
import {useCachedQuery} from "../../lib/data-cache";
import {useGarminMode} from "../../lib/garminMode";
import {featureHint,featureUnavailable} from "../../lib/garminAuth";
import {bi,useI18n} from "../../lib/i18n";
import {useSession} from "../../lib/session";
import {activityTimeLabel,measuredLabel,sourceLabel} from "../../lib/sources";
import {greeting,normalizeToday,visibleCards,type TodayPrefs} from "../../lib/todayLayout";
import {tileColumns} from "../../lib/healthInsights";

type O=Record<string,any>;
type Body={weight_kg?:number;body_fat_percent?:number;sources?:Record<string,string>;measured_at_by_metric?:Record<string,string>};
type H={available:boolean;step_goal?:any;steps?:number;resting_hr?:number;stress_avg?:number;body_battery_high?:number;hydration_ml?:number;hydration_goal_ml?:number;training_readiness?:number;vo2max_running?:number;vo2max_cycling?:number;sources?:Record<string,string>;body?:Body;sleep?:{duration_seconds?:number;score?:number;source?:string};hrv?:{overnight_average?:number;status?:string;source?:string}};
type A={id:string;name?:string;sport_type?:string;distance_m?:number;duration_seconds?:number;started_at?:string};
const dur=(s?:number)=>s?`${Math.floor(s/3600)}h ${Math.round((s%3600)/60)}m`:"—";
const sportGlyph=(s?:string)=>{const v=(s||"").toLowerCase();if(v.includes("run"))return "RUN";if(v.includes("bik")||v.includes("cycl"))return "BIKE";if(v.includes("swim"))return "SWIM";if(v.includes("strength")||v.includes("weight"))return "GYM";return "MOVE"};

/** Readiness (fast) and briefing (full) merged the same way the companion always did. */
function useTodayData(){
  const ready=useCachedQuery<O>("/coach/readiness"),brief=useCachedQuery<O>("/coach/briefing");
  const data=useMemo<O|null>(()=>{
    const b=brief.data,q=ready.data;
    const base=b?.date===q?.date?{...b,...q,mode:q?.mode==="check_in"&&b?.upcoming?.length?"review_plan":q?.mode}:q||b;
    return base?{...base,briefing_ready:!!b&&b.date===base.date}:null;
  },[ready.data,brief.data]);
  const refresh=async()=>{await Promise.all([ready.refresh(),brief.refresh()])};
  return {data,loading:!data&&(ready.loading||brief.loading),failed:!!ready.error&&!data,refresh};
}

export default function Today(){
  const{lang}=useI18n(),{me}=useSession(),de=lang==="de";
  const prefsQuery=useCachedQuery<O>("/settings/today",60000);
  const [saved,setSaved]=useState<TodayPrefs|null>(null),[settingsOpen,setSettingsOpen]=useState(false),[phaseOverride,setPhaseOverride]=useState<string|null>(null),[status,setStatus]=useState("");
  const prefs=saved??normalizeToday(prefsQuery.data as Partial<TodayPrefs>);
  const loaded=!!prefsQuery.data,shown=(k:string)=>loaded&&!prefs.hidden.includes(k);
  useEffect(()=>{setSaved(null)},[prefsQuery.data]);
  const today=useTodayData(),data=today.data;
  const lastDate=useRef<string|null>(null);
  useEffect(()=>{if(data?.date){if(lastDate.current&&lastDate.current!==data.date)setPhaseOverride(null);lastDate.current=data.date}},[data?.date]);
  const phase=phaseOverride||data?.day_phase||"morning";

  const hQuery=useCachedQuery<H>(shown("metrics")?"/health/today?include_vo2=false":null);
  const actsQuery=useCachedQuery<A[]>(shown("activities")?"/activities?limit=4&include_stats=false":null);
  const trendQuery=useCachedQuery<O>(shown("trend")?"/health/resting-hr?days=14":null);
  const loadQuery=useCachedQuery<O>(shown("load")?"/coach/training-load":null);
  const vo2Query=useCachedQuery<O>(shown("metrics")&&prefs.pinned_metrics.includes("vo2max")?"/health/vo2-history?days=180":null,120000);
  const h=hQuery.data?{...hQuery.data,vo2max_running:hQuery.data.vo2max_running??vo2Query.data?.latest?.running,vo2max_cycling:hQuery.data.vo2max_cycling??vo2Query.data?.latest?.cycling}:null;
  const garminMode=useGarminMode(),readinessBlocked=featureUnavailable(garminMode,"training_readiness");

  const now=new Date();
  const date=new Intl.DateTimeFormat(de?"de-DE":"en-GB",{weekday:"long",day:"numeric",month:"long",...(data?.date?{timeZone:"UTC"}:{})}).format(data?.date?new Date(`${data.date}T12:00:00Z`):now);
  const next=data?.upcoming?.find((s:O)=>s.date===data?.date);
  const doneToday:O[]=data?.today_activities||[];
  const planLine=next?bi(lang,`Heute geplant: ${next.name} · ${next.duration_min} min`,`Planned today: ${next.name} · ${next.duration_min} min`)
    :doneToday.length?bi(lang,`Heute erledigt: ${doneToday.length} ${doneToday.length===1?"Aktivität":"Aktivitäten"}`,`Done today: ${doneToday.length} ${doneToday.length===1?"activity":"activities"}`)
    :data?bi(lang,"Heute ist nichts geplant","Nothing planned today"):"";

  const sleepHours=h?.sleep?.duration_seconds!=null?h.sleep.duration_seconds/3600:null;
  const src=(field:string)=>sourceLabel(h?.sources?.[field],lang);
  const bodySrc=(field:string)=>[sourceLabel(h?.body?.sources?.[field],lang),measuredLabel(h?.body?.measured_at_by_metric?.[field],lang)].filter(Boolean).join(" · ");
  const none=bi(lang,"Keine Daten","No data");
  const metrics:O[]=[
    {key:"sleep",label:bi(lang,"Schlaf","Sleep"),value:h?.sleep?.score!=null?`${h.sleep.score}`:sleepHours!=null?`${sleepHours.toFixed(1)} h`:"—",note:h?.sleep?[sourceLabel(h.sleep.source,lang),h.sleep.score!=null&&sleepHours!=null?`${sleepHours.toFixed(1)} h`:""].filter(Boolean).join(" · "):none,tone:"sleep"},
    {key:"hrv",label:"HRV",value:h?.hrv?.overnight_average!=null?`${h.hrv.overnight_average} ms`:"—",note:h?.hrv?[sourceLabel(h.hrv.source,lang),h.hrv.status].filter(Boolean).join(" · "):none,tone:"hrv"},
    {key:"resting_hr",label:bi(lang,"Ruhepuls","Resting HR"),value:h?.resting_hr!=null?`${h.resting_hr} bpm`:"—",note:h?.resting_hr!=null?src("resting_hr"):none,tone:"heart"},
    {key:"steps",label:bi(lang,"Schritte","Steps"),value:h?.steps!=null?h.steps.toLocaleString(de?"de-DE":"en-US"):"—",note:h?.steps!=null?src("steps"):bi(lang,"Heute","Today"),tone:"steps"},
    {key:"body_battery_high",label:"Body Battery",value:h?.body_battery_high??"—",note:h?.body_battery_high!=null?src("body_battery_high"):none,tone:"battery"},
    {key:"stress",label:"Stress",value:h?.stress_avg??"—",note:h?.stress_avg!=null?src("stress_avg"):none,tone:"stress"},
    {key:"hydration",label:bi(lang,"Trinkmenge","Water"),value:h?.hydration_ml!=null?`${(h.hydration_ml/1000).toFixed(1)} L`:"—",note:h?.hydration_ml!=null?[src("hydration_ml"),h.hydration_goal_ml?`${bi(lang,"Ziel","Goal")} ${(h.hydration_goal_ml/1000).toFixed(1)} L`:""].filter(Boolean).join(" · "):none,tone:"water"},
    {key:"training_readiness",label:bi(lang,"Geräte-Bereitschaft","Device readiness"),value:h?.training_readiness??"—",note:h?.training_readiness!=null?src("training_readiness"):readinessBlocked?featureHint("training_readiness",lang):none,tone:"ready",unavailable:readinessBlocked&&h?.training_readiness==null},
    {key:"weight",label:bi(lang,"Gewicht","Weight"),value:h?.body?.weight_kg!=null?`${h.body.weight_kg.toFixed(1)} kg`:"—",note:h?.body?.weight_kg!=null?bodySrc("weight_kg"):none,tone:"body"},
    {key:"body_fat",label:bi(lang,"Körperfett","Body fat"),value:h?.body?.body_fat_percent!=null?`${h.body.body_fat_percent.toFixed(1)} %`:"—",note:h?.body?.body_fat_percent!=null?bodySrc("body_fat_percent"):none,tone:"body"},
  ];
  const hLoading=!h&&!hQuery.error,hError=!!hQuery.error&&!h,errorNote=bi(lang,"Konnte nicht geladen werden","Could not be loaded");

  async function saveCheckin(draft:O){await api<O>("/coach/check-in",{method:"PUT",body:JSON.stringify(draft)});window.dispatchEvent(new Event("pengucoach-checkin-updated"));await today.refresh();setStatus(bi(lang,"Check-in gespeichert.","Check-in saved."))}
  async function resetCheckin(){await api("/coach/check-in",{method:"DELETE"});window.dispatchEvent(new Event("pengucoach-checkin-updated"));await today.refresh();setStatus(bi(lang,"Check-in gelöscht.","Check-in deleted."))}

  const load=loadQuery.data,trend:O[]=trendQuery.data?.health??[],acts=actsQuery.data??[];
  const week=data?.current_week,prev=data?.previous_week;
  const weekMax=Math.max(1,week?.minutes??0,prev?.minutes??0);

  const blocks:Record<string,React.ReactNode>={
    readiness:<TodayReadiness data={data} loading={today.loading} failed={today.failed} lang={lang} onRetry={()=>void today.refresh()}/>,
    checkin:<section className="card today-checkin"><div className="today-card-head"><span className="eyebrow">{bi(lang,"Ein Moment für dich","A moment for you")}</span><h2>{phase==="reflection"?bi(lang,"Dein Tag","Your day"):bi(lang,"Wie geht es dir?","How are you?")}</h2></div><div className="today-assistant-tiles"><CheckinAssistant key={`check-${data?.date}`} value={data?.checkin||{}} ready={!!data} lang={lang} onSave={saveCheckin} onReset={resetCheckin}/>{shown("reflection")&&<ReflectionAssistant key={`reflection-${data?.date}`} data={data} lang={lang}/>}</div>{status&&<p role="status" className="today-status-note">{status}</p>}</section>,
    metrics:<section className="today-metrics" aria-label={bi(lang,"Deine Messwerte","Your readings")}><div className="health-metric-grid" style={{"--cols":tileColumns(prefs.pinned_metrics.length)} as React.CSSProperties}>{prefs.pinned_metrics.filter(k=>k!=="vo2max").map(k=>metrics.find(m=>m.key===k)).filter((m):m is O=>!!m).map((m:O)=>m.key==="steps"?<StepGoalCard key={m.key} summary={h?.step_goal} value={String(m.value)} note={hError?errorNote:m.note} loading={hLoading} error={hError}/>:<MetricCard key={m.key} label={m.label} value={String(m.value)} note={hError?errorNote:m.note} tone={m.tone} unavailable={Boolean(m.unavailable)} loading={hLoading} error={hError}/>)}{prefs.pinned_metrics.includes("vo2max")&&<div className="health-metric-card metric-card-modern tone-vo2 vo2-dual-card" data-metric="vo2max"><div className="health-metric-top"><span className="health-metric-dot"/><span className="metric-label">VO₂max</span></div><div className="vo2-dual-values"><div><small>{bi(lang,"Laufen","Running")}</small><strong>{h?.vo2max_running??"—"}</strong></div><div><small>{bi(lang,"Rad","Cycling")}</small><strong>{h?.vo2max_cycling??"—"}</strong></div></div><div className="kpi-note">ml/kg/min</div></div>}</div></section>,
    dayphases:<DayPhases data={data} phase={phase} onChange={setPhaseOverride} automatic={phaseOverride==null} lang={lang}/>,
    preparation:<TrainingPreparation data={data} phase={phase} lang={lang}/>,
    weather:data?.date?<Deferred label={bi(lang,"Wetter wird geladen","Loading weather")}><TodayWeather minutes={data?.checkin?.minutes??next?.duration_min??45} preferences={prefs} lang={lang}/></Deferred>:null,
    progress:<Deferred label={bi(lang,"Entwicklung wird geladen","Loading progress")}><PersonalProgress lang={lang}/></Deferred>,
    load:load?<section className={`card today-load-card load-${load.status||"unknown"}`}><div className="today-card-head"><span className="eyebrow">{bi(lang,"Belastung","Load")}</span><h2>{load.trend==="strongly_rising"?bi(lang,"Steigt stark","Rising strongly"):load.trend==="rising"?bi(lang,"Steigt leicht","Rising slightly"):load.trend==="falling"?bi(lang,"Sinkt","Falling"):bi(lang,"Stabil","Stable")}</h2></div><div className="today-load-metrics"><span><small>{bi(lang,"7 Tage","7 days")}</small><strong>{load.acute_7d}</strong></span><span><small>{bi(lang,"Ø 28 Tage","28d avg")}</small><strong>{load.chronic_28d_weekly}</strong></span><span><small>{bi(lang,"Volumen","Volume")}</small><strong>{load.minutes_7d} min</strong></span></div>{Array.isArray(load.sport_mix)&&load.sport_mix.length>0&&<div className="today-sport-mix">{load.sport_mix.slice(0,4).map((x:O)=><span key={x.sport}>{x.sport} <b>{x.percent}%</b></span>)}</div>}</section>:null,
    trend:<section className="card trend-card"><div className="today-card-head row"><div><span className="eyebrow">{bi(lang,"Ruhepuls","Resting HR")}</span><h2>{bi(lang,"14 Tage","14 days")}</h2></div><Link prefetch={false} className="icon-link" href="/health" aria-label={bi(lang,"Gesundheit öffnen","Open health")}>→</Link></div><div className="trend-visual"><SparkLine values={trend.map(x=>x.resting_hr)}/></div></section>,
    activities:<section className="card recent-card"><div className="today-card-head row"><div><span className="eyebrow">{bi(lang,"Training","Training")}</span><h2>{bi(lang,"Zuletzt","Recent")}</h2></div><Link prefetch={false} className="icon-link" href="/activities" aria-label={bi(lang,"Alle Aktivitäten","All activities")}>→</Link></div>{acts.length?<div className="recent-list">{acts.map(a=><Link prefetch={false} className="recent-activity" key={a.id} href={`/activities/${a.id}`}><span className="sport-badge">{sportGlyph(a.sport_type)}</span><span className="recent-main"><strong>{a.name??a.sport_type??"Activity"}</strong><small>{a.started_at?activityTimeLabel(a,lang):""}</small></span><span className="recent-stat">{a.distance_m?`${(a.distance_m/1000).toFixed(1)} km`:dur(a.duration_seconds)}</span></Link>)}</div>:<p className="muted">{actsQuery.loading?bi(lang,"Wird geladen …","Loading …"):bi(lang,"Noch keine Aktivitäten","No activities yet")}</p>}</section>,
    week:week?<section className="card today-week"><div className="today-card-head"><span className="eyebrow">{bi(lang,"7 Tage","7 days")}</span><h2>{(week.minutes??0)>=(prev?.minutes??0)?bi(lang,"Mehr als die Woche davor","More than the week before"):bi(lang,"Weniger als die Woche davor","Less than the week before")}</h2></div>{[[bi(lang,"Diese 7 Tage","These 7 days"),week,"now"],[bi(lang,"Die 7 davor","7 before"),prev||{},"prev"]].map(([label,w,cls]:any)=><div className={`today-week-row ${cls}`} key={cls}><span>{label}</span><span className="today-week-bar" aria-hidden="true"><i style={{width:`${Math.round((w.minutes??0)/weekMax*100)}%`}}/></span><b>{w.minutes??0} min</b><small>{w.sessions??0} {bi(lang,"Einheiten","sessions")}</small></div>)}</section>:null,
  };
  const layout=visibleCards(prefs);

  return <AppShell>
    <div className={`today-v2 density-${prefs.density}`}>
      <header className="today-header">
        <div className="today-header-copy">
          <span className="eyebrow">{date}</span>
          <h1>{greeting(now.getHours(),lang,me?.username)}</h1>
          {planLine&&<p>{next?<Link prefetch={false} href={`/training?plan=${next.plan_id}`}>{planLine} →</Link>:planLine}</p>}
        </div>
        <button type="button" className="today-gear" onClick={()=>setSettingsOpen(true)} aria-label={bi(lang,"Heute anpassen","Customize Today")} title={bi(lang,"Heute anpassen","Customize Today")}><GearIcon/><span>{bi(lang,"Anpassen","Customize")}</span></button>
      </header>
      {!loaded&&!prefsQuery.error&&<div className="today-grid"><div className="card today-skeleton span-7"/><div className="card today-skeleton span-5"/><div className="card today-skeleton span-12"/></div>}
      {prefsQuery.error&&!loaded&&<p className="status-warn">{bi(lang,"Deine Heute-Einstellungen konnten nicht geladen werden.","Could not load your Today settings.")} <button type="button" className="ghost compact" onClick={()=>void prefsQuery.refresh()}>{bi(lang,"Erneut laden","Retry")}</button></p>}
      {loaded&&<div className="today-grid">{layout.map(({key,span})=><div key={key} className={`today-slot span-${span} ${span<12?"half":""}`} data-today-card={key}>{blocks[key]}</div>)}</div>}
      {loaded&&layout.length===0&&<div className="card today-empty"><strong>{bi(lang,"Alle Bereiche ausgeblendet","All sections hidden")}</strong><button type="button" onClick={()=>setSettingsOpen(true)}>{bi(lang,"Heute anpassen","Customize Today")}</button></div>}
    </div>
    <TodaySettings value={prefs} onSaved={setSaved} lang={lang} open={settingsOpen} onClose={()=>setSettingsOpen(false)}/>
  </AppShell>;
}
