// Pure helpers for the Today page layout. No DOM access: unit-tested in node.
export type Lang = "de" | "en";
export type Density = "comfortable" | "compact";
export type TodayPrefs = {order:string[];hidden:string[];pinned_metrics:string[];preferred_start_hour:number;preferred_end_hour:number;density:Density};

/** Every block of Today. `span` is the desktop width on a 12-column grid. */
export const TODAY_CARDS:{key:string;span:number;de:string;en:string;descDe:string;descEn:string;placed:boolean}[] = [
  {key:"readiness",span:7,de:"Tagesampel",en:"Daily readiness",descDe:"Deine Bereitschaft für heute mit Begründung",descEn:"Your readiness for today, with reasons",placed:true},
  {key:"checkin",span:5,de:"Check-in",en:"Check-in",descDe:"Energie, Muskelkater und verfügbare Zeit",descEn:"Energy, soreness and available time",placed:true},
  {key:"race",span:12,de:"Wettkampf-Countdown",en:"Race countdown",descDe:"Tage bis zum Wettkampf, Phase und Prognose",descEn:"Days to your race, phase and prognosis",placed:true},
  {key:"metrics",span:12,de:"Messwerte",en:"Readings",descDe:"Deine ausgewählten Tageswerte",descEn:"Your selected daily readings",placed:true},
  {key:"dayphases",span:12,de:"Tagesverlauf",en:"Day timeline",descDe:"Morgen, Vorbereitung, Rückblick",descEn:"Morning, preparation, reflection",placed:true},
  {key:"preparation",span:6,de:"Trainingsvorbereitung",en:"Workout preparation",descDe:"Deine heutige Einheit vorbereiten",descEn:"Get ready for today's session",placed:true},
  {key:"weather",span:6,de:"Wetterfenster",en:"Weather windows",descDe:"Gute Zeitfenster für draußen",descEn:"Good windows for outdoor training",placed:true},
  {key:"progress",span:12,de:"Persönliche Entwicklung",en:"Personal progress",descDe:"Dein Verlauf über Wochen",descEn:"Your trend over weeks",placed:true},
  {key:"load",span:6,de:"Trainingsbelastung",en:"Training load",descDe:"7 Tage gegenüber deinem Mittel",descEn:"7 days versus your average",placed:true},
  {key:"trend",span:6,de:"Ruhepuls-Verlauf",en:"Resting HR trend",descDe:"Die letzten 14 Tage",descEn:"The last 14 days",placed:true},
  {key:"activities",span:6,de:"Letzte Aktivitäten",en:"Recent activities",descDe:"Deine letzten Einheiten",descEn:"Your latest sessions",placed:true},
  {key:"week",span:6,de:"Wochenvergleich",en:"Week comparison",descDe:"Diese 7 Tage gegen die 7 davor",descEn:"These 7 days versus the 7 before",placed:true},
  {key:"reflection",span:0,de:"Tagesabschluss",en:"Daily wrap-up",descDe:"Abendlicher Rückblick im Check-in",descEn:"Evening reflection inside the check-in",placed:false},
];
export const CARD_KEYS = TODAY_CARDS.map(c=>c.key);
export const TODAY_METRICS = ["steps","sleep","resting_hr","hrv","stress","hydration","body_battery_high","floors","weight","body_fat","training_readiness","vo2max"];

export const DEFAULT_TODAY:TodayPrefs = {
  order:[...CARD_KEYS],hidden:[],pinned_metrics:["steps","sleep","resting_hr","hrv","weight","stress"],
  preferred_start_hour:7,preferred_end_hour:21,density:"comfortable",
};

/** Merge server values with defaults; unknown keys are dropped, missing cards appended. */
export function normalizeToday(value:Partial<TodayPrefs>|null|undefined):TodayPrefs{
  const v=value??{};
  const known=(list:unknown,allowed:string[])=>Array.isArray(list)?Array.from(new Set(list.filter((k):k is string=>typeof k==="string"&&allowed.includes(k)))):[];
  const order=known(v.order,CARD_KEYS);
  for(const key of CARD_KEYS)if(!order.includes(key))order.push(key);
  const pinned=known(v.pinned_metrics,TODAY_METRICS);
  return {
    order,hidden:known(v.hidden,CARD_KEYS),pinned_metrics:pinned.length?pinned:[...DEFAULT_TODAY.pinned_metrics],
    preferred_start_hour:Number.isInteger(v.preferred_start_hour)?v.preferred_start_hour!:7,
    preferred_end_hour:Number.isInteger(v.preferred_end_hour)?v.preferred_end_hour!:21,
    density:v.density==="compact"?"compact":"comfortable",
  };
}

/** Cards to render, in order. Half-width cards pair up; a card without a partner takes the full row. */
export function visibleCards(prefs:TodayPrefs){
  const card=(k:string)=>TODAY_CARDS.find(c=>c.key===k)!;
  const shown=prefs.order.filter(k=>!prefs.hidden.includes(k)&&card(k)?.placed);
  const out:{key:string;span:number}[]=[];
  for(let i=0;i<shown.length;i++){
    const a=card(shown[i]);
    if(a.span>=12){out.push({key:a.key,span:12});continue}
    const b=shown[i+1]?card(shown[i+1]):null;
    if(b&&b.span<12){
      const exact=a.span+b.span===12;
      out.push({key:a.key,span:exact?a.span:6},{key:b.key,span:exact?b.span:6});
      i++;
    }else out.push({key:a.key,span:12});
  }
  return out;
}

export function move(order:string[],key:string,delta:number){
  const list=[...order],i=list.indexOf(key),j=i+delta;
  if(i<0||j<0||j>=list.length)return list;
  [list[i],list[j]]=[list[j],list[i]];
  return list;
}

export function toggle(list:string[],key:string,on:boolean){
  return on?Array.from(new Set([...list,key])):list.filter(k=>k!==key);
}

/** Short greeting by local hour. */
export function greeting(hour:number,lang:Lang,name?:string|null){
  const de=lang==="de";
  const word=hour<5?(de?"Gute Nacht":"Good night"):hour<11?(de?"Guten Morgen":"Good morning"):hour<17?(de?"Hallo":"Hello"):hour<22?(de?"Guten Abend":"Good evening"):(de?"Gute Nacht":"Good night");
  return name?`${word}, ${name}`:word;
}

/** Readiness gauge: stroke length of a ring for a 0–100 score. */
export function ringDash(score:number|null|undefined,radius:number){
  const length=2*Math.PI*radius;
  const value=typeof score==="number"&&Number.isFinite(score)?Math.max(0,Math.min(100,score)):0;
  return {length,dash:length*value/100};
}

/** Worst state across connections, for the status pill. */
export function overallStatus(connections:{connected?:boolean;status?:string|null}[]|undefined,online:boolean){
  if(!online)return "offline";
  const list=connections??[];
  if(list.some(c=>c.status==="reauth_required"||c.status==="error"))return "attention";
  if(list.length&&!list.some(c=>c.connected))return "idle";
  return "ok";
}
