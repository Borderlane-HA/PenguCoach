"use client";
// Side panel to shape the Today page: which blocks, in which order, which readings, how dense.
import {useEffect,useRef,useState} from "react";
import Link from "next/link";
import {api} from "../lib/api";
import {bi,type Lang} from "../lib/i18n";
import {TODAY_CARDS,TODAY_METRICS,DEFAULT_TODAY,move,normalizeToday,toggle,type TodayPrefs} from "../lib/todayLayout";

export const metricNames=(lang:Lang):Record<string,string>=>({steps:bi(lang,"Schritte","Steps"),sleep:bi(lang,"Schlaf","Sleep"),resting_hr:bi(lang,"Ruhepuls","Resting HR"),hrv:"HRV",stress:"Stress",hydration:bi(lang,"Trinkmenge","Water"),body_battery_high:"Body Battery",floors:bi(lang,"Etagen","Floors"),weight:bi(lang,"Gewicht","Weight"),body_fat:bi(lang,"Körperfett","Body fat"),training_readiness:bi(lang,"Geräte-Bereitschaft","Device readiness"),vo2max:"VO₂max"});

export function GearIcon(){return <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M4 7h10M18 7h2M4 17h4M12 17h8"/><circle cx="16" cy="7" r="2.2"/><circle cx="10" cy="17" r="2.2"/></svg>}

export default function TodaySettings({value,onSaved,lang,open,onClose}:{value:TodayPrefs;onSaved:(v:TodayPrefs)=>void;lang:Lang;open:boolean;onClose:()=>void}){
  const dialog=useRef<HTMLDialogElement>(null);
  const [draft,setDraft]=useState<TodayPrefs>(value),[tab,setTab]=useState<"cards"|"metrics"|"view">("cards"),[busy,setBusy]=useState(false),[msg,setMsg]=useState("");
  useEffect(()=>{if(open){setDraft(value);setMsg("");if(!dialog.current?.open)dialog.current?.showModal()}else if(dialog.current?.open)dialog.current.close()},[open,value]);
  const names=metricNames(lang),de=lang==="de";
  const cards=draft.order.map(k=>TODAY_CARDS.find(c=>c.key===k)!).filter(Boolean);
  const placed=cards.filter(c=>c.placed);
  const invalid=draft.preferred_end_hour<=draft.preferred_start_hour||draft.pinned_metrics.length===0;
  async function save(){
    setBusy(true);setMsg("");
    try{const result=await api<TodayPrefs>("/settings/today",{method:"PUT",body:JSON.stringify(draft)});onSaved(normalizeToday(result));onClose()}
    catch(e){setMsg(e instanceof Error?e.message:String(e))}finally{setBusy(false)}
  }
  const tabs:[typeof tab,string][]=[["cards",bi(lang,"Bereiche","Sections")],["metrics",bi(lang,"Messwerte","Readings")],["view",bi(lang,"Ansicht","View")]];
  return <dialog ref={dialog} className="today-settings" aria-labelledby="today-settings-title" onClose={onClose} onClick={e=>{if(e.target===e.currentTarget)onClose()}}>
    <div className="today-settings-inner">
      <header><div><span className="eyebrow">{bi(lang,"Ganz nach dir","Make it yours")}</span><h2 id="today-settings-title">{bi(lang,"Heute anpassen","Customize Today")}</h2></div><button type="button" className="ghost icon-button" aria-label={bi(lang,"Schließen","Close")} onClick={onClose}>✕</button></header>
      <div className="today-settings-tabs" role="tablist">{tabs.map(([k,l])=><button key={k} type="button" role="tab" aria-selected={tab===k} className={tab===k?"active":""} onClick={()=>setTab(k)}>{l}</button>)}</div>
      <fieldset disabled={busy} className="today-settings-body">
        {tab==="cards"&&<>
          <p className="today-settings-hint">{bi(lang,"Schalte Bereiche an oder aus und ändere die Reihenfolge mit den Pfeilen.","Switch sections on or off and change the order with the arrows.")}</p>
          <ul className="today-card-list">{placed.map((c,i)=>{const on=!draft.hidden.includes(c.key);return <li key={c.key} className={on?"":"off"}>
            <label className="today-switch"><input type="checkbox" checked={on} onChange={e=>setDraft({...draft,hidden:toggle(draft.hidden,c.key,!e.target.checked)})}/><span aria-hidden="true"/><div><strong>{de?c.de:c.en}</strong><small>{de?c.descDe:c.descEn}</small></div></label>
            <div className="today-order-buttons"><button type="button" className="ghost icon-button" aria-label={bi(lang,`${c.de} nach oben`,`Move ${c.en} up`)} disabled={i===0} onClick={()=>setDraft({...draft,order:move(draft.order,c.key,-1)})}>↑</button><button type="button" className="ghost icon-button" aria-label={bi(lang,`${c.de} nach unten`,`Move ${c.en} down`)} disabled={i===placed.length-1} onClick={()=>setDraft({...draft,order:move(draft.order,c.key,1)})}>↓</button></div>
          </li>})}</ul>
          <label className="today-switch standalone"><input type="checkbox" checked={!draft.hidden.includes("reflection")} onChange={e=>setDraft({...draft,hidden:toggle(draft.hidden,"reflection",!e.target.checked)})}/><span aria-hidden="true"/><div><strong>{bi(lang,"Tagesabschluss im Check-in","Daily wrap-up in check-in")}</strong><small>{bi(lang,"Abends ein kurzer Rückblick auf deinen Tag","A short look back at your day in the evening")}</small></div></label>
        </>}
        {tab==="metrics"&&<>
          <p className="today-settings-hint">{bi(lang,"Wähle, welche Werte oben auf Heute erscheinen. Die Reihenfolge folgt deiner Auswahl.","Choose which readings appear on Today. The order follows your selection.")}</p>
          <div className="today-metric-picker">{TODAY_METRICS.map(k=>{const on=draft.pinned_metrics.includes(k);return <button type="button" key={k} aria-pressed={on} className={on?"on":""} onClick={()=>setDraft({...draft,pinned_metrics:on?draft.pinned_metrics.filter(x=>x!==k):[...draft.pinned_metrics,k]})}>{on&&<span aria-hidden="true">✓ </span>}{names[k]}</button>})}</div>
          {draft.pinned_metrics.length===0&&<p className="status-warn">{bi(lang,"Wähle mindestens einen Wert.","Choose at least one reading.")}</p>}
        </>}
        {tab==="view"&&<>
          <div className="today-density" role="radiogroup" aria-label={bi(lang,"Dichte","Density")}>{(["comfortable","compact"] as const).map(d=><button type="button" key={d} role="radio" aria-checked={draft.density===d} className={draft.density===d?"on":""} onClick={()=>setDraft({...draft,density:d})}><strong>{d==="compact"?bi(lang,"Kompakt","Compact"):bi(lang,"Luftig","Comfortable")}</strong><small>{d==="compact"?bi(lang,"Mehr auf einen Blick, weniger Abstand","More at a glance, less spacing"):bi(lang,"Mehr Raum, größere Werte","More room, larger figures")}</small></button>)}</div>
          <div className="today-hours"><span>{bi(lang,"Bevorzugte Trainingszeit (für Wetterfenster)","Preferred training time (for weather windows)")}</span><div><label>{bi(lang,"Von","From")}<select value={draft.preferred_start_hour} onChange={e=>setDraft({...draft,preferred_start_hour:Number(e.target.value)})}>{Array.from({length:24},(_,h)=><option key={h} value={h}>{String(h).padStart(2,"0")}:00</option>)}</select></label><label>{bi(lang,"Bis","To")}<select value={draft.preferred_end_hour} onChange={e=>setDraft({...draft,preferred_end_hour:Number(e.target.value)})}>{Array.from({length:24},(_,h)=>h+1).map(h=><option key={h} value={h}>{String(h).padStart(2,"0")}:00</option>)}</select></label></div>{draft.preferred_end_hour<=draft.preferred_start_hour&&<small className="status-warn">{bi(lang,"Das Ende muss nach dem Beginn liegen.","The end must be after the start.")}</small>}</div>
        </>}
      </fieldset>
      {msg&&<p className="status-warn" role="alert">{msg}</p>}
      <footer><button type="button" className="ghost" disabled={busy} onClick={()=>setDraft({...DEFAULT_TODAY})}>{bi(lang,"Standard","Defaults")}</button><Link prefetch={false} className="text-link" href="/help#today" onClick={onClose}>{bi(lang,"Hilfe","Help")}</Link><button type="button" disabled={busy||invalid} onClick={()=>void save()}>{busy?bi(lang,"Speichert …","Saving …"):bi(lang,"Speichern","Save")}</button></footer>
    </div>
  </dialog>;
}
