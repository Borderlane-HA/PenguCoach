import {bi,type Lang} from "./i18n";
export type O=Record<string,any>;
export function addDays(day:string,amount:number){const d=new Date(`${day}T12:00:00Z`);d.setUTCDate(d.getUTCDate()+amount);return d.toISOString().slice(0,10)}
export function weekIndex(start:string,day:string,weeks:number){return Math.max(0,Math.min(Math.max(0,weeks-1),Math.floor((Date.parse(`${day}T12:00:00Z`)-Date.parse(`${start}T12:00:00Z`))/604800000)))}
export function dateText(day:string,lang:Lang,options:Intl.DateTimeFormatOptions={day:"numeric",month:"long"}){return new Date(`${day}T12:00:00Z`).toLocaleDateString(lang==="de"?"de-DE":"en-GB",{...options,timeZone:"UTC"})}
export function valueText(value:number|null|undefined,lang:Lang){return value==null?"—":Number(value).toLocaleString(lang==="de"?"de-DE":"en-GB",{maximumFractionDigits:2})}
export function goalUnit(goal:O,lang:Lang){return goal.metric==="distance_km"?"km":goal.metric==="duration_min"?bi(lang,"Minuten","minutes"):bi(lang,"Einheiten","sessions")}
export function sessionStatus(s:O,lang:Lang){return s.status==="matched"?bi(lang,"Erledigt","Completed"):s.status==="ambiguous"?bi(lang,"Zuordnung prüfen","Review match"):s.status==="unmatched"?bi(lang,"Nicht absolviert","Not completed"):s.status==="pending"?bi(lang,"Abgleich offen","Matching pending"):bi(lang,"Geplant","Planned")}
export function sportIcon(sport:string){return sport==="cycling"?"cycling":sport==="strength"?"strength":sport==="swimming"?"swim":sport==="mobility"||sport==="yoga"?"sun":"run"}
