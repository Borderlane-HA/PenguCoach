"use client";
// Race mode (alpha.85): editor dialog, taper proposal dialog and the Today countdown card.
import {useEffect,useRef,useState} from "react";
import Link from "next/link";
import {api} from "../lib/api";
import {useCachedQuery,invalidateDataCache} from "../lib/data-cache";
import {bi,type Lang} from "../lib/i18n";
import {countdownText,formatDuration,journeyProgress,parseDuration,phaseLabel,RACE_SPORTS,sportLabel} from "../lib/races";
import InfoTip from "./InfoTip";

type O=Record<string,any>;
const PRESETS:Record<string,[number,string,string][]>={
  running:[[5,"5 km","5 km"],[10,"10 km","10 km"],[21.0975,"Halbmarathon","Half marathon"],[42.195,"Marathon","Marathon"]],
  cycling:[[100,"100 km","100 km"],[160,"160 km","160 km"],[200,"200 km","200 km"]],
};

function useDialog(open:boolean){
  const ref=useRef<HTMLDialogElement>(null);
  useEffect(()=>{const d=ref.current;if(!d)return;if(open&&!d.open)d.showModal();if(!open&&d.open)d.close()},[open]);
  return ref;
}

export function RaceEditor({race,open,onClose,onSaved,lang,defaultDate}:{race?:O|null;open:boolean;onClose:()=>void;onSaved:(r:O|null)=>void;lang:Lang;defaultDate?:string}){
  const ref=useDialog(open),de=lang==="de";
  const [form,setForm]=useState<O>({}),[target,setTarget]=useState(""),[busy,setBusy]=useState(false),[msg,setMsg]=useState(""),[confirmDelete,setConfirmDelete]=useState(false);
  useEffect(()=>{if(!open)return;setMsg("");setConfirmDelete(false);
    const base=race??{name:"",date:defaultDate??"",sport:"running",distance_km:10,priority:"A",notes:""};
    setForm({...base});setTarget(base.target_seconds?formatDuration(base.target_seconds):"")},[open,race,defaultDate]);
  const set=(k:string,v:unknown)=>setForm(f=>({...f,[k]:v}));
  async function save(){
    const seconds=target.trim()?parseDuration(target):null;
    if(target.trim()&&seconds==null){setMsg(bi(lang,"Zielzeit bitte als h:mm oder h:mm:ss angeben, z. B. 1:50 oder 0:48:30.","Enter the target time as h:mm or h:mm:ss, e.g. 1:50 or 0:48:30."));return}
    setBusy(true);setMsg("");
    try{
      const body={name:form.name,date:form.date,sport:form.sport,distance_km:form.distance_km?Number(form.distance_km):null,target_seconds:seconds,priority:form.priority,notes:form.notes??""};
      const saved=await api<O>(race?`/races/${race.id}`:"/races",{method:race?"PUT":"POST",body:JSON.stringify(body)});
      invalidateDataCache();onSaved(saved);onClose();
    }catch(e){setMsg(e instanceof Error?e.message:String(e))}finally{setBusy(false)}
  }
  async function remove(){
    if(!race)return;setBusy(true);
    try{await api(`/races/${race.id}`,{method:"DELETE"});invalidateDataCache();onSaved(null);onClose()}catch(e){setMsg(e instanceof Error?e.message:String(e))}finally{setBusy(false)}
  }
  const presets=PRESETS[form.sport]??[];
  return <dialog ref={ref} className="race-dialog" aria-labelledby="race-dialog-title" onClose={onClose} onClick={e=>{if(e.target===e.currentTarget)onClose()}}>
    <form className="race-dialog-inner" onSubmit={e=>{e.preventDefault();void save()}}>
      <header><div><span className="eyebrow">{bi(lang,"Wettkampf","Race")}</span><h2 id="race-dialog-title">{race?bi(lang,"Wettkampf bearbeiten","Edit race"):bi(lang,"Neuer Wettkampf","New race")}</h2></div><button type="button" className="ghost icon-button" aria-label={bi(lang,"Schließen","Close")} onClick={onClose}>✕</button></header>
      <fieldset disabled={busy}>
        <label>{bi(lang,"Name","Name")}<input required maxLength={120} value={form.name??""} onChange={e=>set("name",e.target.value)} placeholder={bi(lang,"z. B. Halbmarathon Hamburg","e.g. City half marathon")}/></label>
        <div className="race-grid">
          <label>{bi(lang,"Datum","Date")}<input required type="date" value={form.date??""} onChange={e=>set("date",e.target.value)}/></label>
          <label>{bi(lang,"Sportart","Sport")}<select value={form.sport??"running"} onChange={e=>set("sport",e.target.value)}>{RACE_SPORTS.map(s=><option key={s} value={s}>{sportLabel(s,lang)}</option>)}</select></label>
        </div>
        <div className="race-distance">
          <label>{bi(lang,"Distanz (km)","Distance (km)")}<input type="number" inputMode="decimal" min="0.1" max="1000" step="0.001" value={form.distance_km??""} onChange={e=>set("distance_km",e.target.value)}/></label>
          {presets.length>0&&<div className="race-presets">{presets.map(([km,dl,el])=><button type="button" key={km} className={Number(form.distance_km)===km?"on":""} onClick={()=>set("distance_km",km)}>{de?dl:el}</button>)}</div>}
        </div>
        <div className="race-grid">
          <label>{bi(lang,"Zielzeit (optional)","Target time (optional)")}<input value={target} onChange={e=>setTarget(e.target.value)} placeholder="1:50:00" inputMode="numeric"/></label>
          <label><span className="label-with-tip">{bi(lang,"Priorität","Priority")}<InfoTip label={bi(lang,"Was bedeutet die Priorität?","What does priority mean?")} text={bi(lang,"A ist dein Hauptziel: Der Countdown auf „Heute“ und der Taper-Vorschlag richten sich danach. B und C sind Vorbereitungs- oder Spaßrennen und erscheinen nur im Kalender.","A is your main goal: the countdown on Today and the taper proposal follow it. B and C are preparation or fun races and only appear in the calendar.")}/></span>
            <div className="race-priority" role="radiogroup">{(["A","B","C"] as const).map(p=><button type="button" key={p} role="radio" aria-checked={form.priority===p} className={form.priority===p?"on":""} onClick={()=>set("priority",p)}>{p}</button>)}</div></label>
        </div>
        <label>{bi(lang,"Notizen","Notes")}<textarea rows={2} maxLength={1500} value={form.notes??""} onChange={e=>set("notes",e.target.value)} placeholder={bi(lang,"Startzeit, Anreise, Verpflegung …","Start time, travel, nutrition …")}/></label>
      </fieldset>
      {msg&&<p className="status-warn" role="alert">{msg}</p>}
      <footer>
        {race&&(confirmDelete?<span className="race-delete-confirm">{bi(lang,"Wirklich löschen?","Delete for sure?")} <button type="button" className="ghost danger" disabled={busy} onClick={()=>void remove()}>{bi(lang,"Löschen","Delete")}</button><button type="button" className="ghost" onClick={()=>setConfirmDelete(false)}>{bi(lang,"Nein","No")}</button></span>:<button type="button" className="ghost danger" onClick={()=>setConfirmDelete(true)}>{bi(lang,"Löschen","Delete")}</button>)}
        <span className="spacer"/>
        <button type="button" className="ghost" onClick={onClose}>{bi(lang,"Abbrechen","Cancel")}</button>
        <button type="submit" disabled={busy||!form.name||!form.date}>{busy?bi(lang,"Speichert …","Saving …"):bi(lang,"Speichern","Save")}</button>
      </footer>
    </form>
  </dialog>;
}

export function TaperDialog({raceId,open,onClose,lang}:{raceId:string|null;open:boolean;onClose:()=>void;lang:Lang}){
  const ref=useDialog(open);
  const [data,setData]=useState<O|null>(null),[busy,setBusy]=useState(false),[msg,setMsg]=useState(""),[done,setDone]=useState<O|null>(null),[chosen,setChosen]=useState<Record<string,boolean>>({});
  useEffect(()=>{if(!open||!raceId)return;setData(null);setDone(null);setMsg("");
    api<O>(`/races/${raceId}/taper`).then(d=>{setData(d);const all:Record<string,boolean>={};for(const p of d.plans)for(const c of p.changes)all[`${p.plan_id}:${c.session_id}`]=true;setChosen(all)}).catch(e=>setMsg(e instanceof Error?e.message:String(e)))},[open,raceId]);
  async function apply(){
    if(!data)return;setBusy(true);setMsg("");
    try{
      const plans=data.plans.map((p:O)=>({plan_id:p.plan_id,revision:p.revision,session_ids:p.changes.filter((c:O)=>chosen[`${p.plan_id}:${c.session_id}`]).map((c:O)=>c.session_id)})).filter((p:O)=>p.session_ids.length);
      if(!plans.length){onClose();return}
      setDone(await api<O>(`/races/${raceId}/taper`,{method:"POST",body:JSON.stringify({plans})}));invalidateDataCache();
    }catch(e){setMsg(e instanceof Error?e.message:String(e))}finally{setBusy(false)}
  }
  const day=(d:string)=>new Date(`${d}T12:00:00`).toLocaleDateString(lang==="de"?"de-DE":"en-GB",{weekday:"short",day:"2-digit",month:"2-digit"});
  const total=data?.plans?.reduce((n:number,p:O)=>n+p.changes.length,0)??0;
  return <dialog ref={ref} className="race-dialog taper-dialog" aria-labelledby="taper-title" onClose={onClose} onClick={e=>{if(e.target===e.currentTarget)onClose()}}>
    <div className="race-dialog-inner">
      <header><div><span className="eyebrow">{bi(lang,"Vorschlag","Proposal")}</span><h2 id="taper-title">{bi(lang,"Tapering vor dem Wettkampf","Taper before the race")}</h2></div><button type="button" className="ghost icon-button" aria-label={bi(lang,"Schließen","Close")} onClick={onClose}>✕</button></header>
      {!data&&!msg&&<p className="muted">{bi(lang,"Wird berechnet …","Calculating …")}</p>}
      {data&&!done&&<>
        <p className="taper-lead">{bi(lang,`In den letzten ${data.phase.taper_days} Tagen vor „${data.race.name}“ weniger Umfang, gleiche Intensität – so kommst du frisch an. Nichts ändert sich, bevor du bestätigst.`,`Less volume, same intensity in the last ${data.phase.taper_days} days before “${data.race.name}” – so you arrive fresh. Nothing changes before you confirm.`)}</p>
        {total===0?<p className="muted">{bi(lang,"Im Taper-Zeitraum ist keine Einheit geplant, die gekürzt werden müsste.","No planned session in the taper window needs shortening.")}</p>:
        data.plans.map((p:O)=><section key={p.plan_id} className="taper-plan"><h3>{p.plan_title}</h3><ul>{p.changes.map((c:O)=>{const key=`${p.plan_id}:${c.session_id}`;return <li key={key}>
          <label className="checkline"><input type="checkbox" checked={!!chosen[key]} onChange={e=>setChosen(v=>({...v,[key]:e.target.checked}))}/>
            <span className="taper-day">{day(c.date)}</span><span className="taper-name">{c.name}</span>
            <span className="taper-change">{c.action==="skip"?bi(lang,"streichen (Wettkampftag)","cancel (race day)"):<><s>{c.before_minutes} min</s> → <strong>{c.after_minutes} min</strong></>}</span></label></li>})}</ul></section>)}
      </>}
      {done&&<div className="taper-done" role="status"><strong>{bi(lang,`${done.applied} Einheiten angepasst.`,`${done.applied} sessions adjusted.`)}</strong>{done.locked?.length>0&&<p className="status-warn">{bi(lang,`${done.locked.length} Einheit(en) sind schon auf der Garmin-Uhr und blieben unverändert: `,`${done.locked.length} session(s) are already on the Garmin watch and stayed unchanged: `)}{done.locked.map((l:O)=>l.name).join(", ")}</p>}</div>}
      {msg&&<p className="status-warn" role="alert">{msg}</p>}
      <footer><span className="spacer"/>{done?<button type="button" onClick={onClose}>{bi(lang,"Fertig","Done")}</button>:<><button type="button" className="ghost" onClick={onClose}>{bi(lang,"Später","Later")}</button><button type="button" disabled={busy||!data||total===0||!Object.values(chosen).some(Boolean)} onClick={()=>void apply()}>{busy?bi(lang,"Übernimmt …","Applying …"):bi(lang,"Vorschlag übernehmen","Apply proposal")}</button></>}</footer>
    </div>
  </dialog>;
}

/** Today card: countdown, phase journey, prognosis, taper nudge and the result afterwards. */
export function RaceCountdown({lang}:{lang:Lang}){
  const query=useCachedQuery<O>("/races/next",60000);
  const [taper,setTaper]=useState(false);
  const race=query.data?.race;
  if(!race)return null;
  const p=race.phase,days=p.days_to_race,de=lang==="de";
  const steps=["base","build","peak","taper"];
  const progress=journeyProgress(days);
  const prog=race.prognosis;
  const date=new Date(`${race.date}T12:00:00`).toLocaleDateString(de?"de-DE":"en-GB",{weekday:"short",day:"numeric",month:"long"});
  const result=race.result;
  return <section className={`card race-countdown phase-${p.key}`} aria-label={bi(lang,"Wettkampf-Countdown","Race countdown")}>
    <div className="race-countdown-main">
      <div className="race-flag" aria-hidden="true">🏁</div>
      <div className="race-countdown-copy">
        <span className="eyebrow">{race.name}{race.distance_km?` · ${Number(race.distance_km).toLocaleString(de?"de-DE":"en-GB",{maximumFractionDigits:1})} km`:""} · {date}</span>
        <h2>{p.key==="done"||p.key==="past"?(result?bi(lang,"Geschafft!","You did it!"):bi(lang,"Wettkampf vorbei","Race over")):countdownText(days,lang)}</h2>
        {p.key!=="done"&&p.key!=="past"&&<p className="race-phase-line"><strong>{phaseLabel(p.key,lang)}</strong>{p.key==="taper"?bi(lang," – jetzt zählt Frische, nicht Umfang."," – freshness counts now, not volume."):p.key==="race"?bi(lang," – viel Erfolg!"," – good luck!"):p.key==="peak"?bi(lang," – die härtesten Wochen, danach wird entlastet."," – the hardest weeks, then you ease off."):""}</p>}
      </div>
      <div className="race-countdown-side">
        {result?<div className="race-figure"><small>{bi(lang,"Deine Zeit","Your time")}</small><strong>{formatDuration(result.seconds)}</strong>{race.target_seconds&&result.target_delta_seconds!=null&&<span className={result.target_delta_seconds<=0?"good":"bad"}>{result.target_delta_seconds<=0?"−":"+"}{formatDuration(Math.abs(result.target_delta_seconds))} {bi(lang,"zum Ziel","vs target")}</span>}</div>
        :prog?<div className="race-figure"><small>{bi(lang,"Prognose","Prognosis")} <InfoTip label={bi(lang,"Wie entsteht die Prognose?","How is the prognosis made?")} text={bi(lang,`Geschätzt aus deinen ${prog.basis_count} schnellsten passenden Einheiten der letzten 8 Wochen (mindestens 30 % der Wettkampfdistanz), hochgerechnet mit der Riegel-Formel. Eine Schätzung, keine Garantie – Tagesform, Strecke und Wetter zählen mit.`,`Estimated from your ${prog.basis_count} fastest matching sessions of the last 8 weeks (at least 30 % of the race distance), projected with Riegel's formula. An estimate, not a promise – form, course and weather matter too.`)}/></small><strong>{formatDuration(prog.low_seconds)}–{formatDuration(prog.high_seconds)}</strong>{race.target_seconds&&<span className={prog.target_reachable?"good":"neutral"}>{bi(lang,"Ziel","Target")} {formatDuration(race.target_seconds)}</span>}</div>
        :race.target_seconds?<div className="race-figure"><small>{bi(lang,"Ziel","Target")}</small><strong>{formatDuration(race.target_seconds)}</strong></div>:null}
      </div>
    </div>
    {p.key!=="done"&&p.key!=="past"&&<div className="race-journey" aria-label={bi(lang,"Phasen bis zum Wettkampf","Phases until the race")}>
      <div className="race-journey-track"><i style={{width:`${Math.round(progress*100)}%`}}/></div>
      <div className="race-journey-steps">{steps.map(s=><span key={s} className={s===p.key?"now":steps.indexOf(s)<steps.indexOf(p.key)||p.key==="race"?"past":""}>{phaseLabel(s,lang)}</span>)}</div>
    </div>}
    <div className="race-actions">
      {race.taper_changes>0&&<button type="button" onClick={()=>setTaper(true)}>{bi(lang,"Taper-Vorschlag ansehen","View taper proposal")}</button>}
      {race.taper_applied_at&&p.key==="taper"&&<span className="race-note">✓ {bi(lang,"Tapering übernommen","Taper applied")}</span>}
      {result&&<Link prefetch={false} className="text-link" href={`/activities/${result.activity_id}`}>{bi(lang,"Wettkampf ansehen →","View race →")}</Link>}
      <Link prefetch={false} className="text-link" href="/calendar#races">{bi(lang,"Im Kalender","In calendar")}</Link>
    </div>
    <TaperDialog raceId={race.id} open={taper} onClose={()=>{setTaper(false);void query.refresh()}} lang={lang}/>
  </section>;
}
