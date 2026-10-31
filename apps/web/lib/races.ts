// Race mode and calendar helpers (alpha.85). Pure functions, tested in tests/races.test.cjs.
export type Lang = "de" | "en";

export const RACE_SPORTS = ["running","cycling","swimming","triathlon","hiking","other"] as const;
export const PHASES = ["base","build","peak","taper","race","done","past"] as const;

export function sportLabel(sport:string, lang:Lang){
  const de:Record<string,string>={running:"Laufen",cycling:"Radfahren",swimming:"Schwimmen",triathlon:"Triathlon",hiking:"Wandern",other:"Sonstiges"};
  const en:Record<string,string>={running:"Running",cycling:"Cycling",swimming:"Swimming",triathlon:"Triathlon",hiking:"Hiking",other:"Other"};
  return (lang==="de"?de:en)[sport]??sport;
}

export function phaseLabel(key:string, lang:Lang){
  const de:Record<string,string>={base:"Grundlage",build:"Aufbau",peak:"Spitze",taper:"Tapering",race:"Wettkampftag",done:"Geschafft",past:"Vorbei"};
  const en:Record<string,string>={base:"Base",build:"Build",peak:"Peak",taper:"Taper",race:"Race day",done:"Done",past:"Past"};
  return (lang==="de"?de:en)[key]??key;
}

/** 5400 → "1:30:00", 1500 → "25:00". */
export function formatDuration(seconds:number|null|undefined){
  if(seconds==null||!Number.isFinite(seconds)||seconds<0)return "—";
  const s=Math.round(seconds),h=Math.floor(s/3600),m=Math.floor(s%3600/60),r=s%60;
  return h?`${h}:${String(m).padStart(2,"0")}:${String(r).padStart(2,"0")}`:`${m}:${String(r).padStart(2,"0")}`;
}

/** "1:50" (h:mm), "1:50:30", "50:30" (mm:ss when the first part is large), "105" (minutes). Null when unreadable. */
export function parseDuration(text:string):number|null{
  const value=(text||"").trim();
  if(!value)return null;
  if(/^\d+$/.test(value)){const n=Number(value);return n>0?n*60:null}
  const parts=value.split(":").map(p=>p.trim());
  if(parts.length<2||parts.length>3||parts.some(p=>!/^\d+$/.test(p)))return null;
  const n=parts.map(Number);
  let seconds:number;
  if(n.length===3){if(n[1]>59||n[2]>59)return null;seconds=n[0]*3600+n[1]*60+n[2]}
  else if(n[0]>=10){if(n[1]>59)return null;seconds=n[0]*60+n[1]}        // 50:30 → minutes:seconds
  else{if(n[1]>59)return null;seconds=n[0]*3600+n[1]*60}               // 1:50 → hours:minutes
  return seconds>0?seconds:null;
}

/** Progress through the preparation from 0 to 1 (base start = 16 weeks before, at the latest the creation day). */
export function journeyProgress(daysToRace:number, totalDays=112){
  if(daysToRace<=0)return 1;
  return Math.max(0,Math.min(1,1-daysToRace/totalDays));
}

export function countdownText(days:number, lang:Lang){
  if(days===0)return lang==="de"?"Heute ist Wettkampftag":"Race day is today";
  if(days===1)return lang==="de"?"Morgen ist es so weit":"Tomorrow is the day";
  if(days<0)return lang==="de"?`vor ${-days} ${days===-1?"Tag":"Tagen"}`:`${-days} ${days===-1?"day":"days"} ago`;
  return lang==="de"?`noch ${days} Tage`:`${days} days to go`;
}

// --- Calendar ------------------------------------------------------------------

/** ISO date (YYYY-MM-DD) in local time. */
export function iso(d:Date){return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,"0")}-${String(d.getDate()).padStart(2,"0")}`}

/** Monday-based weeks covering a year, for the heatmap (columns = weeks, rows = Mon..Sun). */
export function yearWeeks(year:number){
  const first=new Date(year,0,1,12),start=new Date(first);start.setDate(first.getDate()-((first.getDay()+6)%7));
  const weeks:{date:string;inYear:boolean}[][]=[];
  const cursor=new Date(start);
  while(cursor.getFullYear()<year||(cursor.getFullYear()===year)){
    const week=[];
    for(let i=0;i<7;i++){week.push({date:iso(cursor),inYear:cursor.getFullYear()===year});cursor.setDate(cursor.getDate()+1)}
    weeks.push(week);
    if(cursor.getFullYear()>year)break;
  }
  return weeks;
}

/** Days of a month grid: Monday of the first week to Sunday of the last week. */
export function monthGrid(year:number, month:number){
  const first=new Date(year,month,1,12),start=new Date(first);start.setDate(1-((first.getDay()+6)%7));
  const last=new Date(year,month+1,0,12),end=new Date(last);end.setDate(last.getDate()+(7-((last.getDay()+6)%7)-1));
  const days:{date:string;inMonth:boolean}[]=[];
  for(const d=new Date(start);d<=end;d.setDate(d.getDate()+1))days.push({date:iso(d),inMonth:d.getMonth()===month});
  return days;
}

/** Heatmap level 0–4 by quantiles of the year's non-zero values, so a light and a heavy year both use the full scale. */
export function levels(values:number[]){
  const v=values.filter(x=>x>0).sort((a,b)=>a-b);
  if(!v.length)return (x:number)=>x>0?1:0;
  const q=(p:number)=>v[Math.min(v.length-1,Math.floor(p*(v.length-1)))];
  const a=q(.25),b=q(.5),c=q(.8);
  return (x:number)=>!x||x<=0?0:x<=a?1:x<=b?2:x<=c?3:4;
}
