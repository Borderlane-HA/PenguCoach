"use client";
// Side panel for the Health page: sections, readings and the period it opens with.
import {useEffect,useRef,useState} from "react";
import Link from "next/link";
import {api} from "../lib/api";
import {bi,type Lang} from "../lib/i18n";
import {DEFAULT_HEALTH,HEALTH_METRICS,HEALTH_PERIODS,HEALTH_SECTIONS,normalizeHealth,type HealthPrefs} from "../lib/healthInsights";
import {move,toggle} from "../lib/todayLayout";

export default function HealthSettings({value,onSaved,lang,open,onClose}:{value:HealthPrefs;onSaved:(v:HealthPrefs)=>void;lang:Lang;open:boolean;onClose:()=>void}){
  const dialog=useRef<HTMLDialogElement>(null),de=lang==="de";
  const [draft,setDraft]=useState<HealthPrefs>(value),[tab,setTab]=useState<"sections"|"metrics">("sections"),[busy,setBusy]=useState(false),[msg,setMsg]=useState("");
  useEffect(()=>{if(open){setDraft(value);setMsg("");if(!dialog.current?.open)dialog.current?.showModal()}else if(dialog.current?.open)dialog.current.close()},[open,value]);
  const sections=draft.order.map(k=>HEALTH_SECTIONS.find(s=>s.key===k)!).filter(Boolean);
  async function save(){
    setBusy(true);setMsg("");
    try{onSaved(normalizeHealth(await api<HealthPrefs>("/settings/health-layout",{method:"PUT",body:JSON.stringify(draft)})));onClose()}
    catch(e){setMsg(e instanceof Error?e.message:String(e))}finally{setBusy(false)}
  }
  return <dialog ref={dialog} className="today-settings" aria-labelledby="health-settings-title" onClose={onClose} onClick={e=>{if(e.target===e.currentTarget)onClose()}}>
    <div className="today-settings-inner">
      <header><div><span className="eyebrow">{bi(lang,"Ganz nach dir","Make it yours")}</span><h2 id="health-settings-title">{bi(lang,"Gesundheit anpassen","Customize health")}</h2></div><button type="button" className="ghost icon-button" aria-label={bi(lang,"Schließen","Close")} onClick={onClose}>✕</button></header>
      <div className="today-settings-tabs two" role="tablist">{([["sections",bi(lang,"Bereiche","Sections")],["metrics",bi(lang,"Werte","Values")]] as const).map(([k,l])=><button key={k} type="button" role="tab" aria-selected={tab===k} className={tab===k?"active":""} onClick={()=>setTab(k)}>{l}</button>)}</div>
      <fieldset disabled={busy} className="today-settings-body">
        {tab==="sections"&&<>
          <ul className="today-card-list">{sections.map((c,i)=>{const on=!draft.hidden.includes(c.key);return <li key={c.key} className={on?"":"off"}>
            <label className="today-switch"><input type="checkbox" checked={on} onChange={e=>setDraft({...draft,hidden:toggle(draft.hidden,c.key,!e.target.checked)})}/><span aria-hidden="true"/><div><strong>{de?c.de:c.en}</strong><small>{de?c.descDe:c.descEn}</small></div></label>
            <div className="today-order-buttons"><button type="button" className="ghost icon-button" aria-label={bi(lang,`${c.de} nach oben`,`Move ${c.en} up`)} disabled={i===0} onClick={()=>setDraft({...draft,order:move(draft.order,c.key,-1)})}>↑</button><button type="button" className="ghost icon-button" aria-label={bi(lang,`${c.de} nach unten`,`Move ${c.en} down`)} disabled={i===sections.length-1} onClick={()=>setDraft({...draft,order:move(draft.order,c.key,1)})}>↓</button></div>
          </li>})}</ul>
          <div className="today-hours"><span>{bi(lang,"Zeitraum beim Öffnen","Period when opening")}</span><div className="health-period-pick">{HEALTH_PERIODS.map(p=><button type="button" key={p.id} aria-pressed={draft.period===p.id} className={draft.period===p.id?"on":""} onClick={()=>setDraft({...draft,period:p.id})}>{de?p.de:p.en}</button>)}</div></div>
        </>}
        {tab==="metrics"&&<>
          <p className="today-settings-hint">{bi(lang,"Diese Werte erscheinen als Kennzahlen und Verläufe.","These values appear as key figures and trends.")}</p>
          <div className="today-metric-picker">{HEALTH_METRICS.map(m=>{const on=draft.metrics.includes(m.key);return <button type="button" key={m.key} aria-pressed={on} className={on?"on":""} onClick={()=>setDraft({...draft,metrics:on?draft.metrics.filter(x=>x!==m.key):[...draft.metrics,m.key]})}>{on&&<span aria-hidden="true">✓ </span>}{m.label[lang]}</button>})}</div>
          {draft.metrics.length===0&&<p className="status-warn">{bi(lang,"Wähle mindestens einen Wert.","Choose at least one value.")}</p>}
        </>}
      </fieldset>
      {msg&&<p className="status-warn" role="alert">{msg}</p>}
      <footer><button type="button" className="ghost" disabled={busy} onClick={()=>setDraft({...DEFAULT_HEALTH})}>{bi(lang,"Standard","Defaults")}</button><Link prefetch={false} className="text-link" href="/help#health" onClick={onClose}>{bi(lang,"Hilfe","Help")}</Link><button type="button" disabled={busy||draft.metrics.length===0} onClick={()=>void save()}>{busy?bi(lang,"Speichert …","Saving …"):bi(lang,"Speichern","Save")}</button></footer>
    </div>
  </dialog>;
}
