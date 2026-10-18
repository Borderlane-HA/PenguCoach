"use client";
import {useCachedQuery} from "../lib/data-cache";
import {bi,useI18n} from "../lib/i18n";
export default function UpdateNotice({version,mobile=false}:{version:string;mobile?:boolean}){
 const {lang}=useI18n(),{data}=useCachedQuery<{status:string;latest_version?:string;url:string}>("/settings/update-status",600000);
 const available=data?.status==="available";
 const label=available?bi(lang,`Update verfügbar · ${data.latest_version}`,`Update available · ${data.latest_version}`):bi(lang,"GitHub-Releases öffnen","Open GitHub releases");
 return <div className={`version-notice ${mobile?"mobile-version-notice":""} ${available?"has-update":""}`}><a className="side-version" href="https://github.com/Borderlane-HA/PenguCoach/releases" target="_blank" rel="noopener noreferrer" title={bi(lang,"Installierte PenguCoach-Version","Installed PenguCoach version")}>v{version}</a>{available&&<a className="update-notice-link" href={data.url} target="_blank" rel="noopener noreferrer" aria-label={label} title={label}><span className="update-notice-icon" aria-hidden="true">↑</span><span><strong>{bi(lang,"Update verfügbar","Update available")}</strong><small>{data.latest_version}</small></span></a>}</div>;
}
