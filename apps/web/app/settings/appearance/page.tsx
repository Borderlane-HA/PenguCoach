"use client";

import {ChangeEvent,useEffect,useState} from "react";
import AppShell from "../../../components/AppShell";
import {api} from "../../../lib/api";
import {bi,useI18n} from "../../../lib/i18n";

type Appearance={theme:string;has_avatar:boolean;has_app_icon:boolean;avatar_version?:number;app_icon_version?:number};
const themes=[
  {id:"light",nameDe:"Mint Light",nameEn:"Mint Light",descDe:"Das helle PenguCoach Gesundheitsdesign.",descEn:"The bright PenguCoach health theme.",swatches:["#f5faf7","#ffffff","#16866d"]},
  {id:"dark",nameDe:"Midnight Health",nameEn:"Midnight Health",descDe:"Dunkel, kontrastreich und angenehm am Abend.",descEn:"Dark, high-contrast and comfortable at night.",swatches:["#0d1512","#15211d","#5fd0ad"]},
  {id:"ocean",nameDe:"Ocean",nameEn:"Ocean",descDe:"Kühles Blau mit klaren Aqua-Akzenten.",descEn:"Cool blues with clean aqua accents.",swatches:["#f4f8fb","#ffffff","#287fa3"]},
  {id:"forest",nameDe:"Forest",nameEn:"Forest",descDe:"Ruhige Naturtöne mit kräftigem Grün.",descEn:"Calm natural tones with deep green.",swatches:["#f6f8f3","#ffffff","#4d7d53"]},
  {id:"lavender",nameDe:"Lavender",nameEn:"Lavender",descDe:"Sanfte Violetttöne mit modernem Health-Look.",descEn:"Soft violet tones with a modern health look.",swatches:["#f8f6fb","#ffffff","#7568a8"]},
];

export default function Appearance(){
  const{lang}=useI18n();const[a,setA]=useState<Appearance|null>(null),[msg,setMsg]=useState("");
  const refresh=()=>api<Appearance>("/settings/appearance").then(v=>{setA(v);document.documentElement.dataset.theme=v.theme||"light"});
  useEffect(()=>{void refresh()},[]);
  async function choose(theme:string){const v=await api<Appearance>("/settings/appearance",{method:"PUT",body:JSON.stringify({theme})});setA(v);document.documentElement.dataset.theme=theme;setMsg(bi(lang,"Theme gespeichert","Theme saved"))}
  async function upload(kind:"avatar"|"app-icon",e:ChangeEvent<HTMLInputElement>){const file=e.target.files?.[0];if(!file)return;const body=new FormData();body.append("file",file);const res=await fetch(`/api/v1/settings/${kind}`,{method:"POST",body,credentials:"include"});if(!res.ok){setMsg(`${bi(lang,"Upload fehlgeschlagen","Upload failed")}: ${res.status}`);return}const v=await res.json();setA(v);setMsg(bi(lang,"Bild gespeichert","Image saved"));e.target.value="";window.dispatchEvent(new Event("pengucoach-appearance-changed"))}
  async function remove(kind:"avatar"|"app-icon"){const v=await api<Appearance>(`/settings/${kind}`,{method:"DELETE"});setA(v);setMsg(bi(lang,"Bild entfernt","Image removed"));window.dispatchEvent(new Event("pengucoach-appearance-changed"))}
  return <AppShell title={bi(lang,"Darstellung","Appearance")}>
    <div className="page-head-modern"><div><span className="eyebrow">PERSONALIZATION</span><h1>{bi(lang,"Dein PenguCoach","Your PenguCoach")}</h1><p className="muted">{bi(lang,"Wähle Theme, App-Icon und dein Benutzerbild. Alle Einstellungen gelten nur für deinen Account.","Choose your theme, app icon and profile picture. These settings apply only to your account.")}</p></div></div>
    {msg&&<div className="ai-toast">{msg}</div>}
    <section className="card appearance-card"><div className="section-heading"><div><span className="eyebrow">THEMES</span><h2>{bi(lang,"Farbstil","Color style")}</h2></div><span className="badge">{a?.theme??"light"}</span></div><div className="theme-grid">{themes.map(t=><button type="button" key={t.id} onClick={()=>choose(t.id)} className={`theme-tile ${a?.theme===t.id?"active":""}`}><div className="theme-preview">{t.swatches.map((s,i)=><i key={s} style={{background:s,width:i===2?"28%":"36%"}}/>)}</div><strong>{lang==="de"?t.nameDe:t.nameEn}</strong><small>{lang==="de"?t.descDe:t.descEn}</small>{a?.theme===t.id&&<span className="theme-check">✓</span>}</button>)}</div></section>
    <section className="grid2 appearance-upload-grid"><div className="card asset-card"><div className="asset-preview avatar-preview">{a?.has_avatar?<img src={`/api/v1/settings/avatar?v=${a.avatar_version??0}`} alt=""/>:<span>YOU</span>}</div><div><span className="eyebrow">PROFILE</span><h2>{bi(lang,"Benutzerbild","Profile picture")}</h2><p className="muted">{bi(lang,"Wird in der Benutzer-Ecke und Navigation angezeigt. PNG, JPEG oder WebP bis 3 MB.","Shown in the user corner and navigation. PNG, JPEG or WebP up to 3 MB.")}</p><div className="form-actions"><label className="upload-button">{bi(lang,"Bild auswählen","Choose image")}<input hidden type="file" accept="image/png,image/jpeg,image/webp" onChange={e=>upload("avatar",e)}/></label>{a?.has_avatar&&<button className="ghost" onClick={()=>remove("avatar")}>{bi(lang,"Entfernen","Remove")}</button>}</div></div></div>
    <div className="card asset-card"><div className="asset-preview icon-preview">{a?.has_app_icon?<img src={`/api/v1/settings/app-icon?v=${a.app_icon_version??0}`} alt=""/>:<span>P</span>}</div><div><span className="eyebrow">BRANDING</span><h2>{bi(lang,"Eigenes App-Icon","Custom app icon")}</h2><p className="muted">{bi(lang,"Ersetzt das PenguCoach-P in der Seitenleiste. Am besten quadratisch mit transparentem Hintergrund.","Replaces the PenguCoach P in the sidebar. A square image with transparent background works best.")}</p><div className="form-actions"><label className="upload-button">{bi(lang,"Icon auswählen","Choose icon")}<input hidden type="file" accept="image/png,image/jpeg,image/webp" onChange={e=>upload("app-icon",e)}/></label>{a?.has_app_icon&&<button className="ghost" onClick={()=>remove("app-icon")}>{bi(lang,"Entfernen","Remove")}</button>}</div></div></div></section>
  </AppShell>
}
