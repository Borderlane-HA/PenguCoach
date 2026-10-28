// Pure helpers for the activity recap ("Rückblick"). No DOM access: unit-tested in node.
export type Lang = "de" | "en";
export type Period = "today" | "week" | "month" | "year" | "all";
export type O = Record<string, any>;
export type Box = {x:number;y:number;w:number;h:number};

export const PERIODS: {id:Period;de:string;en:string}[] = [
  {id:"today",de:"Heute",en:"Today"},{id:"week",de:"Woche",en:"Week"},{id:"month",de:"Monat",en:"Month"},
  {id:"year",de:"Jahr",en:"Year"},{id:"all",de:"Gesamt",en:"All time"},
];

const MONTHS_DE=["Januar","Februar","März","April","Mai","Juni","Juli","August","September","Oktober","November","Dezember"];
const MONTHS_EN=["January","February","March","April","May","June","July","August","September","October","November","December"];

export function periodTitle(period:Period,start:string|null|undefined,lang:Lang){
  const de=lang==="de",d=start?new Date(`${start}T12:00:00`):new Date();
  if(period==="today")return de?"Dein Tag":"Your day";
  if(period==="week")return de?"Deine Woche":"Your week";
  if(period==="month")return de?`Dein ${MONTHS_DE[d.getMonth()]}`:`Your ${MONTHS_EN[d.getMonth()]}`;
  if(period==="year")return de?`Dein Jahr ${d.getFullYear()}`:`Your ${d.getFullYear()}`;
  return de?"Deine ganze Geschichte":"Your whole story";
}

export function format(value:number,digits:number,lang:Lang){
  return value.toLocaleString(lang==="de"?"de-DE":"en-GB",{minimumFractionDigits:digits,maximumFractionDigits:digits});
}
export function compact(value:number,lang:Lang){
  // Large totals stay readable on a phone: 12.345 km, 1,2 Mio. kcal
  if(value>=1e6)return `${format(value/1e6,1,lang)} ${lang==="de"?"Mio.":"M"}`;
  return format(value,value>=100?0:1,lang);
}

type Fact={text:string;ratio:number};
const MOUNTAINS=[{de:"Eiffelturm",en:"Eiffel Tower",m:330},{de:"Zugspitze",en:"Zugspitze",m:2962},{de:"Mont Blanc",en:"Mont Blanc",m:4806},{de:"Mount Everest",en:"Mount Everest",m:8849}];

/** Playful comparisons. The ratio drives the small progress animations. */
export function distanceFact(km:number,lang:Lang):Fact|null{
  const de=lang==="de";if(!(km>0))return null;
  if(km>=2000){const r=km/40075;return {text:de?`${format(r*100,1,lang)} % einmal um die Erde`:`${format(r*100,1,lang)} % of the way around the Earth`,ratio:r}}
  if(km>=585){const r=km/585;return {text:de?`${format(r,1,lang)} × von München nach Berlin`:`${format(r,1,lang)} × Munich to Berlin`,ratio:Math.min(1,r/10)}}
  const r=km/42.195;return {text:de?`${format(r,1,lang)} Marathon${r>=1.05?"s":""}`:`${format(r,1,lang)} marathon${r>=1.05?"s":""}`,ratio:Math.min(1,r)};
}
export function elevationFact(m:number,lang:Lang):(Fact&{mountain:string;height:number})|null{
  const de=lang==="de";if(!(m>0))return null;
  const fitting=[...MOUNTAINS].reverse().find(x=>m>=x.m)??MOUNTAINS[0];
  const r=m/fitting.m,name=de?fitting.de:fitting.en;
  return {text:r>=1?`${format(r,1,lang)} × ${de?"die Höhe vom":"the height of the"} ${name}`:`${format(r*100,0,lang)} % ${de?"vom":"of the"} ${name}`,ratio:r,mountain:name,height:fitting.m};
}
export function timeFact(seconds:number,lang:Lang):Fact|null{
  if(!(seconds>0))return null;const r=seconds/5400;
  return {text:lang==="de"?`so lang wie ${format(r,1,lang)} Tatort-Folgen`:`as long as ${format(seconds/7200,1,lang)} feature films`,ratio:Math.min(1,r/20)};
}
export function energyFact(kcal:number,lang:Lang):Fact|null{
  if(!(kcal>0))return null;const r=kcal/850;
  return {text:lang==="de"?`≈ ${format(r,1,lang)} Pizzen Margherita`:`≈ ${format(r,1,lang)} pizzas`,ratio:Math.min(1,r/20)};
}

const SPORTS:Record<string,[string,string]>={run:["Laufen","Running"],ride:["Radfahren","Cycling"],swim:["Schwimmen","Swimming"],walk:["Gehen","Walking"],hike:["Wandern","Hiking"],strength:["Kraft","Strength"],other:["Sonstiges","Other"]};
export const sportName=(key:string,lang:Lang)=>(SPORTS[key]??SPORTS.other)[lang==="de"?0:1];

export function hoursText(seconds:number,lang:Lang){
  const h=Math.floor(seconds/3600),m=Math.round(seconds%3600/60);
  return h?`${format(h,0,lang)} h ${String(m).padStart(2,"0")} min`:`${m} min`;
}
export function paceText(secondsPerKm:number){
  let total=Math.round(secondsPerKm),m=Math.floor(total/60),s=total%60;if(s===60){m++;s=0}
  return `${m}:${String(s).padStart(2,"0")} /km`;
}

/** Bounds of the area where most routes are; one far-away holiday does not shrink home routes to a dot. */
export function robustBounds(routes:{points:number[][]}[]){
  const lats:number[]=[],lons:number[]=[];
  for(const r of routes)for(const [lat,lon] of r.points){lats.push(lat);lons.push(lon)}
  if(lats.length<2)return null;
  lats.sort((a,b)=>a-b);lons.sort((a,b)=>a-b);
  const q=(arr:number[],p:number)=>arr[Math.min(arr.length-1,Math.max(0,Math.round(p*(arr.length-1))))];
  let b={minLat:q(lats,.05),maxLat:q(lats,.95),minLon:q(lons,.05),maxLon:q(lons,.95)};
  // Small areas (a single route) keep their full extent.
  if(b.maxLat-b.minLat<.02&&b.maxLon-b.minLon<.02)b={minLat:lats[0],maxLat:lats.at(-1)!,minLon:lons[0],maxLon:lons.at(-1)!};
  const padLat=(b.maxLat-b.minLat)*.08||.001,padLon=(b.maxLon-b.minLon)*.08||.001;
  return {minLat:b.minLat-padLat,maxLat:b.maxLat+padLat,minLon:b.minLon-padLon,maxLon:b.maxLon+padLon};
}

/** SVG paths of all routes in a shared frame; routes completely outside the frame are dropped. */
export function projectRoutes(routes:{id:string;points:number[][]}[],box:Box){
  const bounds=robustBounds(routes);if(!bounds)return [];
  const kx=Math.cos((bounds.minLat+bounds.maxLat)/2*Math.PI/180);
  const spanX=Math.max((bounds.maxLon-bounds.minLon)*kx,1e-9),spanY=Math.max(bounds.maxLat-bounds.minLat,1e-9);
  const scale=Math.min(box.w/spanX,box.h/spanY),ox=box.x+(box.w-spanX*scale)/2,oy=box.y+(box.h-spanY*scale)/2;
  const inside=(lat:number,lon:number)=>lat>=bounds.minLat&&lat<=bounds.maxLat&&lon>=bounds.minLon&&lon<=bounds.maxLon;
  return routes.filter(r=>r.points.some(([lat,lon])=>inside(lat,lon))).map(r=>({id:r.id,d:r.points.map(([lat,lon],i)=>`${i?"L":"M"}${(ox+(lon-bounds.minLon)*kx*scale).toFixed(1)} ${(oy+(bounds.maxLat-lat)*scale).toFixed(1)}`).join("")}));
}

/** Calendar cells for days (week, month, year) with an intensity level 0–4 from training time. */
export function calendar(series:O|undefined){
  const items:O[]=series?.items??[];
  const max=Math.max(0,...items.map(i=>Number(i.duration_s)||0));
  return items.map(i=>{const s=Number(i.duration_s)||0,c=Number(i.count)||0;return {key:String(i.key),count:c,duration_s:s,level:c===0?0:max<=0?1:Math.min(4,1+Math.floor(s/max*3.999))}});
}

/** Week rows (Monday first) for a GitHub-style year grid. */
export function weekGrid(cells:{key:string;level:number;count:number}[]){
  if(!cells.length)return [];
  const first=new Date(`${cells[0].key}T12:00:00`),offset=(first.getDay()+6)%7;
  const padded=[...Array(offset).fill(null),...cells];
  const weeks:(typeof cells[number]|null)[][]=[];
  for(let i=0;i<padded.length;i+=7)weeks.push(padded.slice(i,i+7));
  return weeks;
}

export type Slide="intro"|"distance"|"elevation"|"time"|"sports"|"highlights"|"map"|"calendar"|"compare"|"finale";
export function slides(data:O|null):Slide[]{
  if(!data||!data.totals?.count)return [];
  const t=data.totals,out:Slide[]=["intro"];
  if(t.distance_m>0)out.push("distance");
  if(t.elevation_m>0)out.push("elevation");
  if(t.duration_s>0||t.calories>0)out.push("time");
  if((data.sports??[]).length>1)out.push("sports");
  if(Object.keys(data.highlights??{}).length&&t.count>1)out.push("highlights");
  if((data.routes??[]).length)out.push("map");
  if(data.period!=="today"&&(data.series?.items??[]).length>1)out.push("calendar");
  if(data.previous&&data.previous.count>0&&Object.values(data.change??{}).some(v=>v!=null))out.push("compare");
  out.push("finale");
  return out;
}

export const easeOut=(t:number)=>1-Math.pow(1-Math.max(0,Math.min(1,t)),3);

export function fileName(period:Period,end:string|undefined){
  return `PenguCoach-Rueckblick-${period}-${(end??"").slice(0,10)||"heute"}.png`;
}
