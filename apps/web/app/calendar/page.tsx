"use client";
// alpha.85 Calendar: year heatmap with streaks, races, a month view with drag & drop
// for planned sessions, and a calendar subscription for phone and Outlook.
import {useEffect,useMemo,useRef,useState} from "react";
import Link from "next/link";
import AppShell from "../../components/AppShell";
import InfoTip from "../../components/InfoTip";
import {RaceEditor,TaperDialog} from "../../components/Races";
import {api,API} from "../../lib/api";
import {useCachedQuery,invalidateDataCache} from "../../lib/data-cache";
import {bi,useI18n,type Lang} from "../../lib/i18n";
import {countdownText,formatDuration,iso,levels,monthGrid,phaseLabel,sportLabel,yearWeeks} from "../../lib/races";

type O=Record<string,any>;
type Metric="training"|"steps"|"floors";
const ICON:Record<string,string>={running:"🏃",cycling:"🚴",swimming:"🏊",walking:"🚶",hiking:"🥾",strength:"🏋️",mobility:"🧘",yoga:"🧘",pilates:"🤸",hiit:"⚡",cardio:"❤️",triathlon:"🏅"};
const icon=(s:string)=>ICON[s]??"●";

function errorText(e:unknown,lang:Lang){
  const m=e instanceof Error?e.message:String(e);
  const map:Record<string,[string,string]>={
    SCHEDULE_CHANGED_RELOAD:["Der Plan wurde gerade an anderer Stelle geändert. Die Ansicht wurde neu geladen – bitte noch einmal versuchen.","The plan was just changed elsewhere. The view was reloaded – please try again."],
    EXPORTED_SESSION_LOCKED:["Diese Einheit ist schon auf der Garmin-Uhr. Entferne sie zuerst unter Training aus Garmin, dann kannst du sie hier ändern.","This session is already on the Garmin watch. Remove it from Garmin under Training first, then you can change it here."],
    DATE_OUTSIDE_PLAN:["Dieser Tag liegt außerhalb des Trainingsplans.","This day is outside the training plan."],
    CANNOT_MOVE_INTO_PAST:["In die Vergangenheit kann nichts verschoben werden.","Sessions cannot be moved into the past."],
    PAST_SESSION_LOCKED:["Vergangene Einheiten bleiben, wo sie sind.","Past sessions stay where they are."],
  };
  const hit=Object.keys(map).find(k=>m.includes(k));
  return hit?bi(lang,map[hit][0],map[hit][1]):m;
}

export default function CalendarPage(){
  const {lang}=useI18n(),de=lang==="de";
  const today=iso(new Date());
  const [year,setYear]=useState(new Date().getFullYear()),[metric,setMetric]=useState<Metric>("training");
  const [cursor,setCursor]=useState(()=>{const d=new Date();return {y:d.getFullYear(),m:d.getMonth()}});
  const [selected,setSelected]=useState(today),[openSession,setOpenSession]=useState<O|null>(null),[moving,setMoving]=useState<O|null>(null);
  const [dragOver,setDragOver]=useState(""),[notice,setNotice]=useState(""),[busy,setBusy]=useState(false);
  const [raceEdit,setRaceEdit]=useState<{open:boolean;race:O|null;date?:string}>({open:false,race:null}),[taperFor,setTaperFor]=useState<string|null>(null),[feedOpen,setFeedOpen]=useState(false);
  const overview=useCachedQuery<O>(`/calendar/overview?year=${year}`,60000);
  const grid=useMemo(()=>monthGrid(cursor.y,cursor.m),[cursor]);
  const monthQuery=useCachedQuery<O>(`/calendar/month?start=${grid[0].date}&end=${grid.at(-1)!.date}`,30000);
  const racesQuery=useCachedQuery<O>("/races",60000);
  useEffect(()=>{if(typeof window!=="undefined"&&window.location.hash==="#subscribe")setFeedOpen(true)},[]);
  // On narrow screens the year scrolls sideways: start at the current week, not in January.
  const heatRef=useRef<HTMLDivElement>(null);
  useEffect(()=>{const el=heatRef.current;if(!el||el.scrollWidth<=el.clientWidth)return;const now=el.querySelector<HTMLElement>(".cal-cell.today");el.scrollLeft=now?Math.max(0,now.offsetLeft-el.clientWidth*.75):year<new Date().getFullYear()?el.scrollWidth:0},[overview.data,year]);

  const byDay=useMemo(()=>{
    const map:Record<string,{activities:O[];sessions:O[];races:O[]}>={};
    const get=(d:string)=>map[d]??=(map[d]={activities:[],sessions:[],races:[]});
    for(const a of monthQuery.data?.activities??[])get(a.date).activities.push(a);
    for(const s of monthQuery.data?.sessions??[])get(s.date).sessions.push(s);
    for(const r of monthQuery.data?.races??[])get(r.date).races.push(r);
    return map;
  },[monthQuery.data]);

  async function change(session:O,body:O,success?:string){
    setBusy(true);setNotice("");
    try{
      const result=await api<O>(`/calendar/plans/${session.plan_id}/sessions/${encodeURIComponent(session.id)}`,{method:"PATCH",body:JSON.stringify({revision:session.revision,...body})});
      invalidateDataCache();
      setNotice(result.swapped_with?bi(lang,"Verschoben – die Einheit an diesem Tag hat den Platz getauscht.","Moved – the session on that day swapped places."):success??bi(lang,"Gespeichert.","Saved."));
      return true;
    }catch(e){setNotice(errorText(e,lang));if(String(e).includes("SCHEDULE_CHANGED_RELOAD"))void monthQuery.refresh();return false}
    finally{setBusy(false)}
  }
  async function moveTo(session:O,date:string){
    setMoving(null);setDragOver("");
    if(session.date===date)return;
    if(!session.editable||date<today){setNotice(errorText(new Error(date<today?"CANNOT_MOVE_INTO_PAST":"PAST_SESSION_LOCKED"),lang));return}
    await change(session,{date},bi(lang,"Einheit verschoben.","Session moved."));
  }
  function dayClick(date:string){if(moving){void moveTo(moving,date);return}setSelected(date)}

  const ov=overview.data;
  const values=useMemo(()=>{
    const out:Record<string,number>={};
    for(const [d,v] of Object.entries<O>(ov?.days??{}))out[d]=metric==="training"?v.minutes??0:metric==="steps"?v.steps??0:v.floors??0;
    return out;
  },[ov,metric]);
  const levelOf=useMemo(()=>levels(Object.values(values)),[values]);
  const weeks=useMemo(()=>yearWeeks(year),[year]);
  const monthName=(m:number,style:"short"|"long"="short")=>new Date(2026,m,1).toLocaleDateString(de?"de-DE":"en-GB",{month:style});
  const valueText=(d:string)=>{const v=ov?.days?.[d];if(!v)return bi(lang,"keine Daten","no data");
    const parts=[v.sessions?`${v.sessions} ${bi(lang,v.sessions===1?"Einheit":"Einheiten",v.sessions===1?"session":"sessions")} · ${Math.round(v.minutes)} min`:bi(lang,"kein Training","no training")];
    if(v.steps!=null)parts.push(`${v.steps.toLocaleString(de?"de-DE":"en-GB")} ${bi(lang,"Schritte","steps")}${v.step_goal&&v.steps>=v.step_goal?" ✓":""}`);
    if(v.floors!=null)parts.push(`${v.floors} ${bi(lang,"Etagen","floors")}`);
    if(v.race)parts.push(`🏁 ${v.race}`);
    return parts.join(" · ")};
  const longDate=(d:string)=>new Date(`${d}T12:00:00`).toLocaleDateString(de?"de-DE":"en-GB",{weekday:"long",day:"numeric",month:"long"});
  const streak=ov?.streaks;
  const upcoming=(racesQuery.data?.items??[]).filter((r:O)=>r.date>=today);
  const past=(racesQuery.data?.items??[]).filter((r:O)=>r.date<today).reverse().slice(0,3);
  const sel=byDay[selected]??{activities:[],sessions:[],races:[]};

  const sessionChip=(s:O)=><button type="button" key={`${s.plan_id}:${s.id}`} className={`cal-session status-${s.status}${s.optional?" optional":""}`}
    draggable={s.editable&&!s.skipped} onDragStart={e=>{e.dataTransfer.setData("text/plain",`${s.plan_id}|${s.id}`);e.dataTransfer.effectAllowed="move";setMoving(null)}}
    onClick={e=>{e.stopPropagation();setOpenSession(s)}} title={`${s.name} · ${s.duration_min} min${s.skipped?bi(lang," · gestrichen"," · cancelled"):""}`}>
    <span aria-hidden="true">{icon(s.sport)}</span><span className="cal-chip-text">{s.start_time?`${s.start_time} `:""}{s.name}</span><small>{s.duration_min}′</small></button>;

  return <AppShell>
    <div className="calendar-page">
      <header className="calendar-header">
        <div><span className="eyebrow">{bi(lang,"Training im Überblick","Training at a glance")}</span><h1>{bi(lang,"Kalender","Calendar")}</h1></div>
        <div className="calendar-header-tools">
          <button type="button" className="ghost" onClick={()=>setRaceEdit({open:true,race:null,date:selected>=today?selected:undefined})}>🏁 {bi(lang,"Wettkampf","Race")}</button>
          <button type="button" className="ghost" onClick={()=>setFeedOpen(true)}>📅 {bi(lang,"Abonnieren","Subscribe")}</button>
        </div>
      </header>

      <section className="card cal-year" aria-label={bi(lang,"Jahresübersicht","Year overview")}>
        <div className="cal-year-head">
          <div className="cal-year-nav"><button type="button" className="ghost icon-button" aria-label={bi(lang,"Vorjahr","Previous year")} onClick={()=>setYear(y=>y-1)}>‹</button><h2>{year}</h2><button type="button" className="ghost icon-button" aria-label={bi(lang,"Nächstes Jahr","Next year")} disabled={year>=new Date().getFullYear()} onClick={()=>setYear(y=>y+1)}>›</button></div>
          <div className="health-periods" role="radiogroup" aria-label={bi(lang,"Anzeigen","Show")}>{(["training","steps","floors"] as Metric[]).map(m=><button key={m} type="button" role="radio" aria-checked={metric===m} className={metric===m?"active":""} onClick={()=>setMetric(m)}>{m==="training"?bi(lang,"Training","Training"):m==="steps"?bi(lang,"Schritte","Steps"):bi(lang,"Etagen","Floors")}</button>)}</div>
        </div>
        <div className="cal-heatmap-scroll" ref={heatRef}><div className="cal-heatmap" style={{"--weeks":weeks.length} as React.CSSProperties}>
          <div className="cal-heatmap-months">{weeks.map((w,i)=>{const first=w.find(d=>d.inYear&&d.date.endsWith("-01")||(i===0&&d.inYear));return <span key={i}>{first&&(first.date.endsWith("-01")||i===0)?monthName(Number(first.date.slice(5,7))-1):""}</span>})}</div>
          <div className="cal-heatmap-days" aria-hidden="true"><span>{bi(lang,"Mo","Mon")}</span><span/><span>{bi(lang,"Mi","Wed")}</span><span/><span>{bi(lang,"Fr","Fri")}</span><span/><span/></div>
          <div className="cal-heatmap-grid">{weeks.map((w,i)=><div key={i} className="cal-week">{w.map(d=>{const lvl=d.inYear?levelOf(values[d.date]??0):-1;const race=ov?.days?.[d.date]?.race;
            return <button type="button" key={d.date} className={`cal-cell l${lvl}${d.date===today?" today":""}${race?" race":""}${d.date>today?" future":""}`} disabled={!d.inYear}
              title={d.inYear?`${longDate(d.date)}: ${valueText(d.date)}`:undefined} aria-label={d.inYear?`${longDate(d.date)}: ${valueText(d.date)}`:undefined}
              onClick={()=>{const x=new Date(`${d.date}T12:00:00`);setCursor({y:x.getFullYear(),m:x.getMonth()});setSelected(d.date);document.getElementById("cal-month")?.scrollIntoView({behavior:"smooth",block:"start"})}}/>})}</div>)}</div>
        </div></div>
        <div className="cal-legend"><span>{bi(lang,"Weniger","Less")}</span>{[0,1,2,3,4].map(l=><i key={l} className={`cal-cell l${l}`}/>)}<span>{bi(lang,"Mehr","More")}</span><i className="cal-cell race"/><span>{bi(lang,"Wettkampf","Race")}</span></div>
        {ov&&<div className="cal-streaks">
          <div className="cal-streak"><span aria-hidden="true">🔥</span><div><strong>{streak.active_weeks.current} {bi(lang,streak.active_weeks.current===1?"aktive Woche":"aktive Wochen",streak.active_weeks.current===1?"active week":"active weeks")}</strong><small>{bi(lang,`in Folge · Rekord ${streak.active_weeks.best}`,`in a row · best ${streak.active_weeks.best}`)} <InfoTip label={bi(lang,"Was ist eine aktive Woche?","What is an active week?")} text={bi(lang,`Eine Woche mit mindestens ${streak.active_weeks.minimum} Trainingstagen. Ruhetage unterbrechen nichts – und die laufende Woche zählt erst, wenn sie erreicht ist. Diese Woche: ${streak.active_weeks.this_week_days} Tag(e).`,`A week with at least ${streak.active_weeks.minimum} training days. Rest days never break it – and the current week only counts once reached. This week: ${streak.active_weeks.this_week_days} day(s).`)}/></small></div></div>
          <div className="cal-streak"><span aria-hidden="true">👣</span><div><strong>{streak.step_goal.current} {bi(lang,streak.step_goal.current===1?"Tag":"Tage","days")}</strong><small>{bi(lang,`Schrittziel in Folge · Rekord ${streak.step_goal.best}`,`step goal in a row · best ${streak.step_goal.best}`)} <InfoTip label={bi(lang,"Welches Schrittziel?","Which step goal?")} text={bi(lang,`Dein Tagesziel von ${Number(streak.step_goal.target).toLocaleString("de-DE")} Schritten${streak.step_goal.configured?"":" (Standard – auf „Heute“ an der Schritte-Kachel änderbar)"}. Heute zählt mit, sobald es erreicht ist.`,`Your daily goal of ${Number(streak.step_goal.target).toLocaleString("en-GB")} steps${streak.step_goal.configured?"":" (default – change it on the steps tile on Today)"}. Today counts once reached.`)}/></small></div></div>
          <div className="cal-streak"><span aria-hidden="true">📆</span><div><strong>{ov.totals.training_days} {bi(lang,"Trainingstage","training days")}</strong><small>{ov.totals.sessions} {bi(lang,"Einheiten","sessions")} · {Math.round(ov.totals.minutes/60)} h{ov.totals.best_month?` · ${bi(lang,"stärkster Monat","best month")} ${monthName(ov.totals.best_month.month-1,"long")}`:""}</small></div></div>
        </div>}
      </section>

      {(upcoming.length>0||past.length>0)&&<section className="card cal-races" id="races" aria-label={bi(lang,"Wettkämpfe","Races")}>
        <div className="health-section-head"><div><h2>{bi(lang,"Wettkämpfe","Races")}</h2></div></div>
        <div className="cal-race-list">{[...upcoming,...past].map((r:O)=><article key={r.id} className={`cal-race ${r.date<today?"past":""} prio-${r.priority}`}>
          <div className="cal-race-date"><strong>{new Date(`${r.date}T12:00:00`).getDate()}</strong><small>{monthName(new Date(`${r.date}T12:00:00`).getMonth())}</small></div>
          <div className="cal-race-body"><strong>{r.name} <span className="cal-prio">{r.priority}</span></strong>
            <small>{sportLabel(r.sport,lang)}{r.distance_km?` · ${Number(r.distance_km).toLocaleString(de?"de-DE":"en-GB",{maximumFractionDigits:1})} km`:""}{r.target_seconds?` · ${bi(lang,"Ziel","target")} ${formatDuration(r.target_seconds)}`:""}</small>
            <small>{r.date>=today?`${countdownText(r.phase.days_to_race,lang)} · ${phaseLabel(r.phase.key,lang)}`:r.result?`${bi(lang,"Ergebnis","Result")} ${formatDuration(r.result.seconds)}`:bi(lang,"Vorbei","Past")}{r.prognosis?` · ${bi(lang,"Prognose","prognosis")} ${formatDuration(r.prognosis.low_seconds)}–${formatDuration(r.prognosis.high_seconds)}`:""}</small></div>
          <div className="cal-race-actions">{r.date>=today&&r.priority==="A"&&(r.phase.key==="taper"||r.phase.key==="peak")&&<button type="button" className="ghost compact" onClick={()=>setTaperFor(r.id)}>{bi(lang,"Tapering","Taper")}</button>}<button type="button" className="ghost compact" onClick={()=>setRaceEdit({open:true,race:r})}>{bi(lang,"Bearbeiten","Edit")}</button></div>
        </article>)}</div>
      </section>}

      <section className="card cal-month" id="cal-month" aria-label={bi(lang,"Monat","Month")}>
        <div className="cal-month-head">
          <div className="cal-year-nav"><button type="button" className="ghost icon-button" aria-label={bi(lang,"Voriger Monat","Previous month")} onClick={()=>setCursor(c=>c.m?{y:c.y,m:c.m-1}:{y:c.y-1,m:11})}>‹</button><h2>{new Date(cursor.y,cursor.m,1).toLocaleDateString(de?"de-DE":"en-GB",{month:"long",year:"numeric"})}</h2><button type="button" className="ghost icon-button" aria-label={bi(lang,"Nächster Monat","Next month")} onClick={()=>setCursor(c=>c.m===11?{y:c.y+1,m:0}:{y:c.y,m:c.m+1})}>›</button></div>
          <div className="cal-month-tools"><button type="button" className="ghost compact" onClick={()=>{const d=new Date();setCursor({y:d.getFullYear(),m:d.getMonth()});setSelected(today)}}>{bi(lang,"Heute","Today")}</button>
          <InfoTip label={bi(lang,"Wie bearbeite ich Einheiten?","How do I edit sessions?")} text={bi(lang,"Geplante Einheiten ziehst du mit der Maus auf einen anderen Tag. Auf dem Handy tippst du die Einheit an, wählst „Verschieben“ und tippst den neuen Tag. Liegt dort schon eine Einheit desselben Plans, tauschen beide den Platz. Antippen öffnet auch Bearbeiten und Streichen.","Drag planned sessions to another day. On a phone, tap the session, choose “Move” and tap the new day. If a session of the same plan is already there, both swap places. Tapping also opens edit and cancel.")}/></div>
        </div>
        {moving&&<div className="cal-moving" role="status">{bi(lang,`Tippe auf den neuen Tag für „${moving.name}“.`,`Tap the new day for “${moving.name}”.`)} <button type="button" className="ghost compact" onClick={()=>setMoving(null)}>{bi(lang,"Abbrechen","Cancel")}</button></div>}
        {notice&&<p className="cal-notice" role="status">{notice}</p>}
        <div className="cal-weekdays" aria-hidden="true">{(de?["Mo","Di","Mi","Do","Fr","Sa","So"]:["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]).map(d=><span key={d}>{d}</span>)}</div>
        <div className={`cal-grid${monthQuery.loading&&!monthQuery.data?" loading":""}${moving?" moving":""}`} aria-busy={busy}>
          {grid.map(({date,inMonth})=>{const items=byDay[date];const n=Number(date.slice(8));
            return <div key={date} role="button" tabIndex={0} aria-label={longDate(date)} className={`cal-day${inMonth?"":" outside"}${date===today?" today":""}${date===selected?" selected":""}${date<today?" past":""}${dragOver===date?" drop":""}`}
              onClick={()=>dayClick(date)} onKeyDown={e=>{if(e.key==="Enter"||e.key===" "){e.preventDefault();dayClick(date)}}}
              onDragOver={e=>{e.preventDefault();e.dataTransfer.dropEffect="move";setDragOver(date)}} onDragLeave={()=>setDragOver(d=>d===date?"":d)}
              onDrop={e=>{e.preventDefault();const [plan,id]=e.dataTransfer.getData("text/plain").split("|");const s=(monthQuery.data?.sessions??[]).find((x:O)=>x.plan_id===plan&&x.id===id);setDragOver("");if(s)void moveTo(s,date)}}>
              <span className="cal-day-num">{n}</span>
              {items?.races.map(r=><span key={r.id} className="cal-race-flag" title={r.name}>🏁 <span className="cal-chip-text">{r.name}</span></span>)}
              <div className="cal-day-items">
                {items?.activities.map(a=><Link prefetch={false} key={a.id} href={`/activities/${a.id}`} className="cal-activity" onClick={e=>e.stopPropagation()} title={`${a.name} · ${Math.round(a.minutes)} min`}><span aria-hidden="true">✓{icon(a.sport)}</span><span className="cal-chip-text">{a.name}</span><small>{Math.round(a.minutes)}′</small></Link>)}
                {items?.sessions.filter(s=>s.status!=="matched").map(sessionChip)}
              </div>
              <span className="cal-dots" aria-hidden="true">{items?.activities.length?<i className="dot-done"/>:null}{items?.sessions.some(s=>s.status==="planned")?<i className="dot-plan"/>:null}{items?.races.length?<i className="dot-race"/>:null}</span>
            </div>})}
        </div>
        <div className="cal-day-detail" aria-live="polite">
          <h3>{longDate(selected)}</h3>
          {!sel.activities.length&&!sel.sessions.length&&!sel.races.length&&<p className="muted">{selected>=today?bi(lang,"Nichts geplant.","Nothing planned."):bi(lang,"Kein Training aufgezeichnet.","No training recorded.")}</p>}
          {sel.races.map(r=><button type="button" key={r.id} className="cal-detail-row race" onClick={()=>setRaceEdit({open:true,race:(racesQuery.data?.items??[]).find((x:O)=>x.id===r.id)??r})}>🏁 <strong>{r.name}</strong><small>{r.distance_km?`${r.distance_km} km`:""}</small></button>)}
          {sel.activities.map(a=><Link prefetch={false} key={a.id} href={`/activities/${a.id}`} className="cal-detail-row done">✓ {icon(a.sport)} <strong>{a.name}</strong><small>{a.time} · {Math.round(a.minutes)} min{a.distance_km?` · ${a.distance_km} km`:""}</small></Link>)}
          {sel.sessions.map(s=><button type="button" key={s.id} className={`cal-detail-row status-${s.status}`} onClick={()=>setOpenSession(s)}>{icon(s.sport)} <strong>{s.name}</strong><small>{s.duration_min} min · {s.plan_title}{s.status==="matched"?bi(lang," · erledigt"," · done"):s.skipped?bi(lang," · gestrichen"," · cancelled"):""}</small></button>)}
          <button type="button" className="ghost compact" onClick={()=>setRaceEdit({open:true,race:null,date:selected})} hidden={selected<today}>+ {bi(lang,"Wettkampf an diesem Tag","Race on this day")}</button>
        </div>
      </section>
    </div>
    <SessionDialog session={openSession} onClose={()=>setOpenSession(null)} lang={lang} busy={busy}
      onSave={async(body)=>{if(openSession&&await change(openSession,body))setOpenSession(null)}}
      onMove={()=>{setMoving(openSession);setOpenSession(null)}}/>
    <RaceEditor open={raceEdit.open} race={raceEdit.race} defaultDate={raceEdit.date} lang={lang} onClose={()=>setRaceEdit({open:false,race:null})} onSaved={()=>{void racesQuery.refresh();void monthQuery.refresh();void overview.refresh()}}/>
    <TaperDialog raceId={taperFor} open={!!taperFor} onClose={()=>{setTaperFor(null);void monthQuery.refresh()}} lang={lang}/>
    <FeedDialog open={feedOpen} onClose={()=>setFeedOpen(false)} lang={lang}/>
  </AppShell>;
}

function SessionDialog({session,onClose,onSave,onMove,lang,busy}:{session:O|null;onClose:()=>void;onSave:(b:O)=>void;onMove:()=>void;lang:Lang;busy:boolean}){
  const ref=useRef<HTMLDialogElement>(null);
  const [form,setForm]=useState<O>({});
  useEffect(()=>{const d=ref.current;if(!d)return;if(session){setForm({name:session.name,duration_min:session.duration_min,start_time:session.start_time??"",notes:session.notes??""});if(!d.open)d.showModal()}else if(d.open)d.close()},[session]);
  if(!session)return <dialog ref={ref} className="race-dialog"/>;
  const editable=session.editable&&session.status!=="matched";
  return <dialog ref={ref} className="race-dialog session-dialog" aria-labelledby="session-title" onClose={onClose} onClick={e=>{if(e.target===e.currentTarget)onClose()}}>
    <form className="race-dialog-inner" onSubmit={e=>{e.preventDefault();onSave({name:form.name,duration_min:Number(form.duration_min),start_time:form.start_time||"",notes:form.notes})}}>
      <header><div><span className="eyebrow">{session.plan_title}</span><h2 id="session-title">{icon(session.sport)} {session.name}</h2></div><button type="button" className="ghost icon-button" aria-label={bi(lang,"Schließen","Close")} onClick={onClose}>✕</button></header>
      <p className="muted">{new Date(`${session.date}T12:00:00`).toLocaleDateString(lang==="de"?"de-DE":"en-GB",{weekday:"long",day:"numeric",month:"long"})}{session.status==="matched"?bi(lang," · erledigt"," · done"):session.status==="unmatched"?bi(lang," · nicht erfasst"," · not recorded"):session.skipped?bi(lang," · gestrichen"," · cancelled"):""}</p>
      <fieldset disabled={!editable||busy}>
        <label>{bi(lang,"Name","Name")}<input required maxLength={120} value={form.name??""} onChange={e=>setForm({...form,name:e.target.value})}/></label>
        <div className="race-grid">
          <label>{bi(lang,"Dauer (min)","Duration (min)")}<input type="number" min={5} max={480} value={form.duration_min??""} onChange={e=>setForm({...form,duration_min:e.target.value})}/></label>
          <label>{bi(lang,"Uhrzeit (optional)","Time (optional)")}<input type="time" value={form.start_time??""} onChange={e=>setForm({...form,start_time:e.target.value})}/></label>
        </div>
        <label>{bi(lang,"Notizen","Notes")}<textarea rows={3} maxLength={1500} value={form.notes??""} onChange={e=>setForm({...form,notes:e.target.value})}/></label>
        {session.has_steps&&<p className="muted small">{bi(lang,"Intervalle und Schritte bearbeitest du im Trainingsplan.","Edit intervals and steps in the training plan.")} <Link prefetch={false} className="text-link" href="/training">{bi(lang,"Zum Plan →","Open plan →")}</Link></p>}
      </fieldset>
      {!session.editable&&<p className="muted small">{bi(lang,"Vergangene Einheiten lassen sich nicht mehr ändern.","Past sessions can no longer be changed.")}</p>}
      <footer>
        {editable&&<button type="button" className="ghost" disabled={busy} onClick={onMove}>{bi(lang,"Verschieben","Move")}</button>}
        {session.editable&&<button type="button" className="ghost danger" disabled={busy} onClick={()=>onSave({skipped:!session.skipped})}>{session.skipped?bi(lang,"Wiederherstellen","Restore"):bi(lang,"Streichen","Cancel session")}</button>}
        <span className="spacer"/>
        {editable&&<button type="submit" disabled={busy}>{bi(lang,"Speichern","Save")}</button>}
      </footer>
    </form>
  </dialog>;
}

function FeedDialog({open,onClose,lang}:{open:boolean;onClose:()=>void;lang:Lang}){
  const ref=useRef<HTMLDialogElement>(null);
  const [feed,setFeed]=useState<O|null>(null),[busy,setBusy]=useState(false),[copied,setCopied]=useState(false),[msg,setMsg]=useState("");
  useEffect(()=>{const d=ref.current;if(!d)return;if(open){if(!d.open)d.showModal();setCopied(false);setMsg("");api<O>("/calendar/feed").then(setFeed).catch(e=>setMsg(String(e)))}else if(d.open)d.close()},[open]);
  const origin=typeof window!=="undefined"?window.location.origin:"";
  const https=feed?.path?`${origin}${feed.path}`:"";
  const webcal=https.replace(/^https?:/,"webcal:");
  async function call(method:string,body?:O){setBusy(true);setMsg("");try{setFeed(await api<O>("/calendar/feed",{method,body:body?JSON.stringify(body):undefined}))}catch(e){setMsg(e instanceof Error?e.message:String(e))}finally{setBusy(false)}}
  async function copy(){try{await navigator.clipboard.writeText(https);setCopied(true)}catch{setMsg(bi(lang,"Kopieren nicht möglich – Link bitte markieren und kopieren.","Copy failed – please select and copy the link."))}}
  return <dialog ref={ref} className="race-dialog feed-dialog" aria-labelledby="feed-title" onClose={onClose} onClick={e=>{if(e.target===e.currentTarget)onClose()}}>
    <div className="race-dialog-inner">
      <header><div><span className="eyebrow">{bi(lang,"Kalender-Export","Calendar export")}</span><h2 id="feed-title">{bi(lang,"Im Handy- oder Outlook-Kalender","In your phone or Outlook calendar")}</h2></div><button type="button" className="ghost icon-button" aria-label={bi(lang,"Schließen","Close")} onClick={onClose}>✕</button></header>
      <p>{bi(lang,"Geplante Einheiten und Wettkämpfe erscheinen in deinem Kalender – auch ohne Garmin-Kalender.","Planned sessions and races appear in your calendar – even without the Garmin calendar.")}</p>
      <section className="feed-block">
        <h3>{bi(lang,"Abonnieren (bleibt aktuell)","Subscribe (stays up to date)")}</h3>
        {!feed?<p className="muted">{bi(lang,"Wird geladen …","Loading …")}</p>:feed.enabled?<>
          <div className="feed-link"><input readOnly value={https} onFocus={e=>e.currentTarget.select()} aria-label={bi(lang,"Abo-Link","Subscription link")}/><button type="button" className="ghost compact" onClick={()=>void copy()}>{copied?bi(lang,"Kopiert ✓","Copied ✓"):bi(lang,"Kopieren","Copy")}</button></div>
          <div className="feed-actions"><a className="primary-link" href={webcal}>{bi(lang,"In Kalender-App öffnen","Open in calendar app")}</a>
            <label className="checkline"><input type="checkbox" checked={!!feed.include_activities} disabled={busy} onChange={e=>void call("POST",{include_activities:e.target.checked})}/>{bi(lang,"Erledigte Aktivitäten (60 Tage) mit anzeigen","Also show completed activities (60 days)")}</label></div>
          <details className="feed-help"><summary>{bi(lang,"So geht’s – und was im Heimnetz gilt","How to – and what applies at home")}</summary>
            <ul>
              <li><strong>iPhone/iPad:</strong> {bi(lang,"„In Kalender-App öffnen“ tippen oder Einstellungen → Kalender → Accounts → Account hinzufügen → Andere → Kalenderabo, Link einfügen.","Tap “Open in calendar app” or Settings → Calendar → Accounts → Add Account → Other → Subscribed Calendar, paste the link.")}</li>
              <li><strong>Outlook (Windows/Mac):</strong> {bi(lang,"Kalender → Kalender hinzufügen → Aus dem Internet, Link einfügen.","Calendar → Add calendar → From internet, paste the link.")}</li>
              <li><strong>Android/Google:</strong> {bi(lang,"calendar.google.com → Weitere Kalender → Per URL. Google holt den Kalender von seinen eigenen Servern – das klappt nur, wenn PenguCoach aus dem Internet erreichbar ist. Ohne das: die Datei unten herunterladen und importieren, oder eine Kalender-App mit Abo-Funktion nutzen (z. B. ICSx⁵).","calendar.google.com → Other calendars → From URL. Google fetches the calendar from its own servers – that only works if PenguCoach is reachable from the internet. Otherwise: download the file below and import it, or use a calendar app with subscriptions (e.g. ICSx⁵).")}</li>
              <li><strong>{bi(lang,"Nur im Heimnetz erreichbar?","Only reachable at home?")}</strong> {bi(lang,"Kein Problem für iPhone, ICSx⁵ und Outlook: Unterwegs schlägt die Aktualisierung still fehl, der Kalender behält den letzten Stand. Sobald du wieder im WLAN zu Hause bist, gleicht er sich von selbst ab (meist innerhalb einer Stunde).","No problem for iPhone, ICSx⁵ and Outlook: on the road the refresh fails silently and the calendar keeps the last state. Once you are back on your home Wi-Fi it updates by itself (usually within an hour).")}</li>
              <li><strong>{bi(lang,"Selbst signiertes HTTPS-Zertifikat?","Self-signed HTTPS certificate?")}</strong> {bi(lang,"iPhone und Outlook lehnen solche Abos oft ab. Dann den Link mit http:// statt https:// im Heimnetz nutzen oder ein gültiges Zertifikat einrichten.","iPhone and Outlook often reject such subscriptions. Then use the link with http:// instead of https:// at home or set up a valid certificate.")}</li>
            </ul>
          </details>
          <div className="feed-actions"><button type="button" className="ghost compact" disabled={busy} onClick={()=>void call("POST",{include_activities:!!feed.include_activities,rotate:true})}>{bi(lang,"Neuen Link erzeugen","New link")}</button><button type="button" className="ghost compact danger" disabled={busy} onClick={()=>void call("DELETE")}>{bi(lang,"Abo beenden","Stop subscription")}</button>
            <InfoTip label={bi(lang,"Wozu ein neuer Link?","Why a new link?")} text={bi(lang,"Der Link ist geheim – wer ihn kennt, sieht deine geplanten Einheiten. Ein neuer Link macht den alten sofort ungültig; danach im Kalender neu abonnieren.","The link is secret – anyone who has it sees your planned sessions. A new link invalidates the old one immediately; then subscribe again in your calendar.")}/></div>
        </>:<button type="button" disabled={busy} onClick={()=>void call("POST",{include_activities:false})}>{bi(lang,"Abo-Link erstellen","Create subscription link")}</button>}
      </section>
      <section className="feed-block">
        <h3>{bi(lang,"Einmalig herunterladen","Download once")}</h3>
        <p className="muted small">{bi(lang,"Eine .ics-Datei mit dem aktuellen Stand – zum Importieren in jeden Kalender. Ändert sich der Plan, einfach neu herunterladen.","An .ics file with the current state – import it into any calendar. If the plan changes, simply download again.")}</p>
        <a className="ghost-link" href={`${API}/calendar/export.ics`} download="pengucoach.ics">⬇ {bi(lang,"pengucoach.ics herunterladen","Download pengucoach.ics")}</a>
      </section>
      {msg&&<p className="status-warn" role="alert">{msg}</p>}
    </div>
  </dialog>;
}
