// Pure helpers for the Health page: metric definitions, explanations, trends and coach summaries.
// No DOM access: unit-tested in node.
export type Lang = "de" | "en";
type Text = {de:string;en:string};
const t=(de:string,en:string):Text=>({de,en});
export type Row = Record<string,any>;

export type MetricDef = {
  key:string;source:"health"|"sleep"|"hrv";field:string;label:Text;unit:string;digits:number;
  scale?:number;better:"up"|"down";tone:string;info:Text;
};

/** Health readings in display order. `scale` converts the stored value for display (seconds → hours). */
export const HEALTH_METRICS:MetricDef[] = [
  {key:"hrv",source:"hrv",field:"overnight_average",label:t("HRV","HRV"),unit:"ms",digits:0,better:"up",tone:"hrv",
   info:t("Herzfrequenzvariabilität: wie stark die Abstände zwischen deinen Herzschlägen in der Nacht schwanken. Liegt sie über deinem üblichen Bereich, bist du meist gut erholt. Vergleiche dich nur mit dir selbst – Werte sind sehr individuell.","Heart rate variability: how much the gaps between your heartbeats vary overnight. Above your usual range usually means you are well recovered. Only compare with yourself – values are very individual.")},
  {key:"sleep",source:"sleep",field:"duration_seconds",label:t("Schlaf","Sleep"),unit:"h",digits:1,scale:1/3600,better:"up",tone:"sleep",
   info:t("Wie lange du geschlafen hast, laut Uhr oder Ring. Für die meisten Erwachsenen sind 7 bis 9 Stunden erholsam. Regelmäßige Zeiten helfen oft mehr als einzelne lange Nächte.","How long you slept, according to your watch or ring. 7 to 9 hours is restorative for most adults. Regular times often help more than single long nights.")},
  {key:"resting_hr",source:"health",field:"resting_hr",label:t("Ruhepuls","Resting HR"),unit:"bpm",digits:0,better:"down",tone:"heart",
   info:t("Dein Puls in völliger Ruhe, meist nachts gemessen. Sinkt er über Wochen, ist das oft ein Zeichen besserer Ausdauer. Ein plötzlicher Anstieg kann auf Stress, wenig Schlaf oder einen beginnenden Infekt hinweisen.","Your pulse at complete rest, usually measured overnight. A drop over weeks often reflects better endurance. A sudden rise can point to stress, short sleep or an emerging infection.")},
  {key:"steps",source:"health",field:"steps",label:t("Schritte","Steps"),unit:"",digits:0,better:"up",tone:"steps",
   info:t("Schritte pro Tag. Mehr Alltagsbewegung zählt – auch ohne Training. Dein Tagesziel stellst du auf „Heute“ an der Schritte-Kachel ein.","Steps per day. Everyday movement counts – even without training. Set your daily target on the steps tile on Today.")},
  {key:"floors",source:"health",field:"floors_ascended",label:t("Etagen","Floors"),unit:"",digits:0,better:"up",tone:"steps",
   info:t("Gestiegene Etagen pro Tag, gemessen vom Höhenmesser der Uhr (eine Etage ≈ 3 m). Treppen statt Aufzug zählen hier direkt.","Floors climbed per day, measured by the watch's barometer (one floor ≈ 3 m). Taking the stairs counts right here.")},
  {key:"body_battery_high",source:"health",field:"body_battery_high",label:t("Body Battery","Body Battery"),unit:"",digits:0,better:"up",tone:"battery",
   info:t("Garmins Schätzung deiner Energiereserve von 0 bis 100. Gezeigt wird der höchste Wert des Tages – meist morgens nach dem Schlaf. Ein hoher Morgenwert heißt: gut aufgeladen.","Garmin's estimate of your energy reserve from 0 to 100. Shown is the day's highest value – usually in the morning after sleep. A high morning value means well recharged.")},
  {key:"stress",source:"health",field:"stress_avg",label:t("Stress","Stress"),unit:"",digits:0,better:"down",tone:"stress",
   info:t("Garmins Stresswert von 0 bis 100 im Tagesmittel, abgeleitet aus deiner Herzfrequenzvariabilität. Unter 25 gilt als ruhig, über 50 als hoch. Training hebt den Wert kurzzeitig – entscheidend sind ruhige Phasen danach.","Garmin's stress score from 0 to 100 as a daily average, derived from your heart rate variability. Below 25 is calm, above 50 high. Training raises it briefly – what matters are calm phases afterwards.")},
  {key:"hydration",source:"health",field:"hydration_ml",label:t("Trinkmenge","Water"),unit:"L",digits:1,scale:1/1000,better:"up",tone:"water",
   info:t("Was du in der Uhr-App oder in SparkyFitness als getrunken eingetragen hast. Der Bedarf steigt mit Training, Hitze und Körpergewicht.","What you logged as drunk in the watch app or SparkyFitness. Needs rise with training, heat and body weight.")},
];

export function metricDef(key:string){return HEALTH_METRICS.find(m=>m.key===key)}

/** Display value of a stored number. */
export function display(def:MetricDef,value:number|null|undefined,lang:Lang){
  if(value==null||!Number.isFinite(value))return "—";
  const v=value*(def.scale??1);
  const text=v.toLocaleString(lang==="de"?"de-DE":"en-GB",{minimumFractionDigits:def.digits,maximumFractionDigits:def.digits});
  return def.unit?`${text} ${def.unit}`:text;
}

export type Summary = {avg:number|null;count:number;latest:number|null;latestDate:string|null;first:number|null;second:number|null;change:number|null;trend:"up"|"down"|"flat"|null;good:boolean|null;values:{date:string;value:number}[]};

/** Average, latest value and the change between the first and second half of the period. */
export function summarize(rows:Row[]|undefined,def:MetricDef):Summary{
  // A missing reading (null) is not a zero; a real zero only counts where it can happen (stress, floors).
  const values=(rows??[]).map(r=>({date:String(r.date??"").slice(0,10),value:r[def.field]==null||r[def.field]===""?NaN:Number(r[def.field])})).filter(v=>v.date&&r(v.value));
  function r(x:number){return Number.isFinite(x)&&(x!==0||def.key==="stress"||def.key==="floors")}
  const n=values.length;
  if(!n)return {avg:null,count:0,latest:null,latestDate:null,first:null,second:null,change:null,trend:null,good:null,values:[]};
  const mean=(a:{value:number}[])=>a.length?a.reduce((s,x)=>s+x.value,0)/a.length:null;
  const half=Math.floor(n/2),first=n>=4?mean(values.slice(0,half)):null,second=n>=4?mean(values.slice(n-half)):null;
  const change=first!=null&&second!=null?second-first:null;
  // Ignore tiny changes (< 2 % of the level) – noise, not a trend.
  const flat=change==null||Math.abs(change)<Math.max(Math.abs(first??0)*.02,def.key==="stress"?1:0.0001);
  const trend=change==null?null:flat?"flat":change>0?"up":"down";
  const good=trend==null||trend==="flat"?null:trend===def.better;
  return {avg:mean(values),count:n,latest:values[n-1].value,latestDate:values[n-1].date,first,second,change,trend,good,values};
}

export function changeText(def:MetricDef,s:Summary,lang:Lang){
  if(s.change==null||s.trend==null)return "";
  if(s.trend==="flat")return lang==="de"?"stabil":"stable";
  const v=Math.abs(s.change)*(def.scale??1);
  const text=v.toLocaleString(lang==="de"?"de-DE":"en-GB",{maximumFractionDigits:def.digits||(v<10?1:0)});
  return `${s.change>0?"+":"−"}${text}${def.unit?` ${def.unit}`:""}`;
}

/** Prompt handed to the coach: what the value is, my numbers, and how to improve. */
export function coachPrompt(def:MetricDef,s:Summary,lang:Lang,periodLabel:string){
  const de=lang==="de",name=def.label[lang];
  const avg=display(def,s.avg,lang),latest=display(def,s.latest,lang);
  const facts=s.count?(de
    ?`Meine Daten (${periodLabel}): Durchschnitt ${avg} aus ${s.count} Werten, letzter Wert ${latest}${s.latestDate?` am ${s.latestDate}`:""}${s.first!=null&&s.second!=null?`, erste Hälfte ${display(def,s.first,lang)}, zweite Hälfte ${display(def,s.second,lang)}`:""}.`
    :`My data (${periodLabel}): average ${avg} from ${s.count} values, latest ${latest}${s.latestDate?` on ${s.latestDate}`:""}${s.first!=null&&s.second!=null?`, first half ${display(def,s.first,lang)}, second half ${display(def,s.second,lang)}`:""}.`)
    :(de?`Für ${periodLabel} habe ich keine Werte.`:`I have no values for ${periodLabel}.`);
  return de
    ?`Erkläre mir kurz, was ${name} aussagt. ${facts} Wie ist mein Verlauf einzuordnen, was beeinflusst den Wert und was kann ich konkret tun, um ihn zu verbessern? Nutze auch meine anderen Gesundheits- und Trainingsdaten, wenn sie helfen.`
    :`Briefly explain what ${name} tells me. ${facts} How should I read my trend, what influences the value and what can I do concretely to improve it? Use my other health and training data where it helps.`;
}

/** Overall health summary for the coach (all chosen metrics at once). */
export function overviewPrompt(items:{def:MetricDef;s:Summary}[],lang:Lang,periodLabel:string){
  const de=lang==="de";
  const lines=items.filter(x=>x.s.count).map(({def,s})=>`${def.label[lang]}: ${display(def,s.avg,lang)}${s.trend&&s.trend!=="flat"?` (${changeText(def,s,lang)})`:""}`);
  return de
    ?`Fasse meine Gesundheit für ${periodLabel} zusammen: ${lines.join("; ")}. Was läuft gut, wo sehe ich Handlungsbedarf und was sind die zwei wirksamsten nächsten Schritte?`
    :`Summarize my health for ${periodLabel}: ${lines.join("; ")}. What is going well, where should I act and what are the two most effective next steps?`;
}

export const HEALTH_PERIODS = [
  {id:"7",days:7,de:"7 T",en:"7 d",longDe:"letzte 7 Tage",longEn:"last 7 days"},
  {id:"30",days:30,de:"30 T",en:"30 d",longDe:"letzte 30 Tage",longEn:"last 30 days"},
  {id:"90",days:90,de:"3 M",en:"3 m",longDe:"letzte 3 Monate",longEn:"last 3 months"},
  {id:"180",days:180,de:"6 M",en:"6 m",longDe:"letzte 6 Monate",longEn:"last 6 months"},
  {id:"365",days:365,de:"1 J",en:"1 y",longDe:"letzte 12 Monate",longEn:"last 12 months"},
  {id:"all",days:0,de:"Alle",en:"All",longDe:"gesamter Zeitraum",longEn:"all time"},
];

export const HEALTH_SECTIONS:{key:string;de:string;en:string;descDe:string;descEn:string}[] = [
  {key:"overview",de:"Kennzahlen",en:"Key figures",descDe:"Deine Werte mit Trend und Erklärung",descEn:"Your values with trend and explanation"},
  {key:"trends",de:"Verläufe",en:"Trends",descDe:"Diagramme deiner Werte",descEn:"Charts of your values"},
  {key:"development",de:"Training & Entwicklung",en:"Training & development",descDe:"VO₂max, Effizienz, Belastung, Erholung",descEn:"VO₂max, efficiency, load, recovery"},
  {key:"body",de:"Körperwerte",en:"Body",descDe:"Gewicht, Körperfett und mehr",descEn:"Weight, body fat and more"},
  {key:"coverage",de:"Datenabdeckung",en:"Data coverage",descDe:"Wie viele Tage Daten haben",descEn:"How many days have data"},
];

export type HealthPrefs = {order:string[];hidden:string[];metrics:string[];period:string};
export const DEFAULT_HEALTH:HealthPrefs = {order:HEALTH_SECTIONS.map(s=>s.key),hidden:["coverage"],metrics:["hrv","sleep","resting_hr","steps","body_battery_high","stress"],period:"30"};
export function normalizeHealth(v:Partial<HealthPrefs>|null|undefined):HealthPrefs{
  const keys=HEALTH_SECTIONS.map(s=>s.key),metrics=HEALTH_METRICS.map(m=>m.key);
  const known=(list:unknown,allowed:string[])=>Array.isArray(list)?Array.from(new Set(list.filter((k):k is string=>typeof k==="string"&&allowed.includes(k)))):[];
  const order=known(v?.order,keys);for(const k of keys)if(!order.includes(k))order.push(k);
  const chosen=known(v?.metrics,metrics);
  return {order,hidden:Array.isArray(v?.hidden)?known(v?.hidden,keys):[...DEFAULT_HEALTH.hidden],metrics:chosen.length?chosen:[...DEFAULT_HEALTH.metrics],period:HEALTH_PERIODS.some(p=>p.id===v?.period)?v!.period!:"30"};
}

/** Columns for a row of tiles: one row up to six, otherwise two balanced rows. */
export function tileColumns(count:number){return count<=6?Math.max(1,count):Math.ceil(count/2)}

/** Story slides for the animated health recap; only slides with data. */
export function recapSlides(current:Record<string,Summary>){
  const has=(k:string)=>(current[k]?.count??0)>0;
  const out:string[]=["intro"];
  if(has("sleep"))out.push("sleep");
  if(has("hrv")||has("resting_hr"))out.push("heart");
  if(has("steps"))out.push("steps");
  if(has("body_battery_high")||has("stress"))out.push("energy");
  out.push("finale");
  return out.length>2?out:[];
}

/** SVG path for a small trend line inside a w×h box. */
export function sparkPath(values:number[],w:number,h:number,pad=4){
  const v=values.filter(Number.isFinite);if(v.length<2)return "";
  const lo=Math.min(...v),hi=Math.max(...v),span=hi-lo||1;
  return v.map((x,i)=>`${i?"L":"M"}${(pad+i/(v.length-1)*(w-pad*2)).toFixed(1)} ${(h-pad-(x-lo)/span*(h-pad*2)).toFixed(1)}`).join("");
}
