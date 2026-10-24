"use client";
// Kept so old links keep working: "About" now lives in System & Updates (admins) and Updates (users).
import {useEffect} from "react";
import AppShell from "../../../components/AppShell";
import AboutPenguCoach from "../../../components/AboutPenguCoach";
import {useSession} from "../../../lib/session";
import {bi,useI18n} from "../../../lib/i18n";

export default function About(){
  const{lang}=useI18n(),{me}=useSession();
  useEffect(()=>{if(me)location.replace(me.role==="admin"?"/admin/system#about":"/settings/updates#about")},[me]);
  return <AppShell title={bi(lang,"Über PenguCoach","About PenguCoach")}><AboutPenguCoach lang={lang} version={me?.app_version??"0.1.0-alpha.82"}/></AppShell>
}
