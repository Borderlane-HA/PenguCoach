"use client";
import Link from "next/link";
import AppShell from "../../../components/AppShell";
import Changelog from "../../../components/Changelog";
import AboutPenguCoach from "../../../components/AboutPenguCoach";
import {UpdateCheck} from "../../../components/UpdateNotice";
import {bi,useI18n} from "../../../lib/i18n";
import {useSession} from "../../../lib/session";
export default function Updates(){const{lang}=useI18n(),{me}=useSession();return <AppShell title={bi(lang,"Versionen & Release Notes","Versions & release notes")}><div className="system-updates"><UpdateCheck/>{me?.role==="admin"?<Link className="maintenance-download" prefetch={false} href="/admin/system#updates">{bi(lang,"System & Wartung öffnen","Open system maintenance")} →</Link>:<p className="muted">{bi(lang,"Updates und Sicherungen verwaltet dein Administrator.","Your administrator manages updates and backups.")}</p>}<Changelog installedVersion={me?.app_version}/><AboutPenguCoach lang={lang} version={me?.app_version}/></div></AppShell>}
