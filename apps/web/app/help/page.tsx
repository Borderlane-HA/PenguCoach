"use client";
// Help in both languages, one section per area, each with links to where it is set.
import {useEffect,useState} from "react";
import Link from "next/link";
import AppShell from "../../components/AppShell";
import {bi,useI18n} from "../../lib/i18n";
import {useSession} from "../../lib/session";
import {filterHelp} from "../../lib/help";

export default function Help(){
  const{lang}=useI18n(),{me}=useSession(),admin=me?.role==="admin";
  const [query,setQuery]=useState(""),[openId,setOpenId]=useState<string|null>(null);
  const sections=filterHelp(query,lang,admin);
  useEffect(()=>{
    // Opening /help#garmin jumps to and highlights that section.
    const go=()=>{const id=location.hash.slice(1);if(!id)return;setOpenId(id);setTimeout(()=>document.getElementById(id)?.scrollIntoView({behavior:"smooth",block:"start"}),60)};
    go();window.addEventListener("hashchange",go);return()=>window.removeEventListener("hashchange",go);
  },[]);
  return <AppShell title={bi(lang,"Hilfe","Help")}>
    <div className="help-page">
      <header className="help-head">
        <span className="eyebrow">{bi(lang,"Hilfe","Help")}</span>
        <h1>{bi(lang,"Wie können wir helfen?","How can we help?")}</h1>
        <label className="help-search"><span className="sr-only">{bi(lang,"Hilfe durchsuchen","Search help")}</span><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg><input type="search" value={query} onChange={e=>setQuery(e.target.value)} placeholder={bi(lang,"Suche, z. B. API-Key, GPX, Theme …","Search, e.g. API key, GPX, theme …")}/></label>
        <nav className="help-toc" aria-label={bi(lang,"Themen","Topics")}>{sections.map(s=><a key={s.id} href={`#${s.id}`} className={openId===s.id?"active":""}>{s.title[lang]}</a>)}</nav>
      </header>
      {sections.length===0&&<p className="muted">{bi(lang,"Nichts gefunden. Versuche ein anderes Wort.","Nothing found. Try another word.")}</p>}
      <div className="help-sections">{sections.map(s=><section key={s.id} id={s.id} className={`card help-section ${openId===s.id?"focus":""}`}>
        <div className="help-section-head"><h2>{s.title[lang]}</h2><p>{s.intro[lang]}</p></div>
        <div className="help-topics">{s.topics.map((x,i)=><details key={i} open={!!query}><summary>{x.q[lang]}</summary><p>{x.a[lang]}</p></details>)}</div>
        <div className="help-links">{s.links.filter(l=>admin||!l.admin).map(l=><Link prefetch={false} key={l.href} href={l.href}>{l.label[lang]} →</Link>)}</div>
      </section>)}</div>
    </div>
  </AppShell>;
}
