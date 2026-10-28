// Pure helpers for the activity showcase card. No DOM access: unit-tested in node.
import {finite,routeSegments,type Sample} from "./activityExplorer";

export type Lang = "de" | "en";
export type Kind = "run" | "walk" | "hike" | "ride" | "swim" | "strength" | "other";
export type FormatId = "portrait" | "story" | "landscape";
export type StyleId = "night" | "paper" | "poster";
export type ColorBy = "gradient" | "heart_rate" | "speed";
export type Box = {x:number;y:number;w:number;h:number};
export type Stat = {key:string;label:string;value:string;unit:string};
export type Zone = {low:number|null;high:number|null};

export const FORMATS: Record<FormatId,{w:number;h:number;de:string;en:string}> = {
  portrait:{w:1080,h:1350,de:"Hochformat 4:5",en:"Portrait 4:5"},
  story:{w:1080,h:1920,de:"Story 9:16",en:"Story 9:16"},
  landscape:{w:1600,h:900,de:"Querformat 16:9",en:"Landscape 16:9"},
};

export type Palette = {bg:[string,string];text:string;muted:string;accent:string;route:[string,string];track:string;panel:string;buckets:string[];glow:boolean};
export const STYLES: Record<StyleId,Palette&{de:string;en:string}> = {
  night:{de:"Nacht",en:"Night",bg:["#07130f","#12382f"],text:"#f2f8f5",muted:"#9db8ae",accent:"#58f0c2",route:["#58f0c2","#7cc8ff"],track:"rgba(255,255,255,.10)",panel:"rgba(255,255,255,.06)",buckets:["#5ad1ff","#58f0c2","#d8f25a","#ffad4d","#ff5f6d"],glow:true},
  paper:{de:"Hell",en:"Light",bg:["#f7f4ec","#ece6d8"],text:"#1b231f",muted:"#6c766f",accent:"#2d806b",route:["#1d5446","#2d806b"],track:"rgba(27,35,31,.10)",panel:"rgba(27,35,31,.05)",buckets:["#3b7dd8","#2d9b7b","#b3a12a","#d9792b","#c8423f"],glow:false},
  poster:{de:"Poster",en:"Poster",bg:["#ff5a36","#d8331f"],text:"#fff8f2",muted:"#ffd9cc",accent:"#2a0d06",route:["#fff8f2","#ffe2d4"],track:"rgba(42,13,6,.18)",panel:"rgba(42,13,6,.12)",buckets:["#fff8f2","#ffe0b0","#ffc069","#4a1206","#2a0d06"],glow:false},
};

export function kindOf(sportType:unknown):Kind {
  const v = String(sportType ?? "").toLowerCase();
  if (/swim|schwimm/.test(v)) return "swim";
  if (/hik|wander|mountaineer/.test(v)) return "hike";
  if (/walk|gehen/.test(v)) return "walk";
  if (/run|lauf|jog|treadmill/.test(v)) return "run";
  if (/cycl|bik|ride|rad/.test(v)) return "ride";
  if (/strength|weight|kraft|gym/.test(v)) return "strength";
  return "other";
}

const KIND_LABEL: Record<Kind,[string,string]> = {run:["Lauf","Run"],walk:["Spaziergang","Walk"],hike:["Wanderung","Hike"],ride:["Radfahrt","Ride"],swim:["Schwimmen","Swim"],strength:["Krafttraining","Strength"],other:["Training","Workout"]};
export const kindLabel = (kind:Kind,lang:Lang) => KIND_LABEL[kind][lang === "de" ? 0 : 1];

export function decimal(value:number,digits:number,lang:Lang){
  return value.toLocaleString(lang === "de" ? "de-DE" : "en-GB",{minimumFractionDigits:digits,maximumFractionDigits:digits});
}
export function clock(seconds:number){
  const s=Math.max(0,Math.round(seconds)),h=Math.floor(s/3600),m=Math.floor(s%3600/60),r=s%60;
  return h?`${h}:${String(m).padStart(2,"0")}:${String(r).padStart(2,"0")}`:`${m}:${String(r).padStart(2,"0")}`;
}
export function paceText(secondsPerUnit:number){
  let total=Math.round(secondsPerUnit),m=Math.floor(total/60),s=total%60;
  if(s===60){m++;s=0}
  return `${m}:${String(s).padStart(2,"0")}`;
}

/** Up to four headline figures that suit the sport; missing data is skipped, never shown as zero. */
export function headlineStats(activity:Sample,analysis:Sample|null,lang:Lang):Stat[] {
  const de = lang === "de", kind = kindOf(activity.sport_type), stats = (analysis?.stats ?? {}) as Sample;
  const extra = ((activity.activity_extra ?? activity.garmin_extra) ?? {}) as Sample;
  const distance = finite(activity.distance_m), duration = finite(activity.moving_seconds) ?? finite(activity.duration_seconds);
  const out: Stat[] = [];
  if (distance != null && distance > 0) out.push(kind === "swim" && distance < 10000
    ? {key:"distance",label:de?"Distanz":"Distance",value:decimal(distance,0,lang),unit:"m"}
    : {key:"distance",label:de?"Distanz":"Distance",value:decimal(distance/1000,distance>=100000?1:2,lang),unit:"km"});
  if (duration != null && duration > 0) out.push({key:"time",label:de?"Zeit":"Time",value:clock(duration),unit:""});
  let speed = finite(activity.avg_speed); if (speed != null) speed *= 3.6;
  if (speed == null) speed = finite((stats.speed_kmh as Sample | undefined)?.avg);
  if (speed == null && distance != null && duration) speed = distance / duration * 3.6;
  if (speed != null && speed > 0) {
    if (kind === "run" || kind === "walk" || kind === "hike") out.push({key:"pace",label:"Pace",value:paceText(3600/speed),unit:"/km"});
    else if (kind === "swim") out.push({key:"pace",label:"Pace",value:paceText(360/speed),unit:"/100 m"});
    else if (kind !== "strength") out.push({key:"speed",label:de?"Tempo":"Speed",value:decimal(speed,1,lang),unit:"km/h"});
  }
  const gain = finite(activity.elevation_gain) ?? finite(extra.elevation_gain_m) ?? finite((stats.elevation as Sample | undefined)?.gain_m);
  const hr = finite(activity.avg_hr) ?? finite(extra.avg_hr_bpm) ?? finite((stats.heart_rate as Sample | undefined)?.avg);
  const power = finite(activity.avg_power) ?? finite((stats.power_w as Sample | undefined)?.avg);
  const calories = finite(activity.calories);
  const candidates: Stat[] = [];
  if (gain != null && gain >= 15 && kind !== "swim" && kind !== "strength") candidates.push({key:"gain",label:de?"Höhenmeter":"Elevation",value:decimal(gain,0,lang),unit:"m"});
  if (kind === "ride" && power != null && power > 0) candidates.push({key:"power",label:de?"Leistung":"Power",value:decimal(power,0,lang),unit:"W"});
  if (hr != null && hr > 0) candidates.push({key:"hr",label:de?"Ø Puls":"Avg HR",value:decimal(hr,0,lang),unit:"bpm"});
  if (calories != null && calories > 0) candidates.push({key:"kcal",label:de?"Energie":"Energy",value:decimal(calories,0,lang),unit:"kcal"});
  for (const item of candidates) if (out.length < 4) out.push(item);
  return out.slice(0,4);
}

/** GPS points projected into a box, keeping the real aspect ratio (equirectangular, cos(lat) corrected). */
export function projectRoute(data:Sample[],box:Box){
  const segments = routeSegments(data).filter(s => s.length > 1);
  const points = segments.flat();
  if (points.length < 2) return null;
  const lat0 = points.reduce((a,p)=>a+p.lat,0)/points.length*Math.PI/180;
  const kx = Math.cos(lat0);
  let minX=Infinity,maxX=-Infinity,minY=Infinity,maxY=-Infinity;
  for (const p of points){const x=p.lon*kx,y=-p.lat;minX=Math.min(minX,x);maxX=Math.max(maxX,x);minY=Math.min(minY,y);maxY=Math.max(maxY,y)}
  const spanX=Math.max(maxX-minX,1e-9),spanY=Math.max(maxY-minY,1e-9);
  const scale=Math.min(box.w/spanX,box.h/spanY);
  const ox=box.x+(box.w-spanX*scale)/2,oy=box.y+(box.h-spanY*scale)/2;
  const projected = segments.map(segment => segment.map(p => ({x:ox+(p.lon*kx-minX)*scale,y:oy+(-p.lat-minY)*scale,sample:p.sample})));
  return {segments:projected,start:projected[0][0],end:projected.at(-1)!.at(-1)!};
}

export function pathOf(points:{x:number;y:number}[]){
  return points.map((p,i)=>`${i?"L":"M"}${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join("");
}

/** Quantile thresholds so colours spread over what this activity actually contains. */
export function bucketEdges(values:number[],buckets=5){
  const sorted=values.filter(v=>Number.isFinite(v)).sort((a,b)=>a-b);
  if(sorted.length<2)return [];
  return Array.from({length:buckets-1},(_,i)=>sorted[Math.floor((i+1)/buckets*(sorted.length-1))]);
}
export const bucketOf=(value:number,edges:number[])=>edges.filter(e=>value>e).length;

/** Consecutive route pieces sharing a colour bucket. Points without a value keep the previous colour. */
export function colouredRuns(segments:{x:number;y:number;sample:Sample}[][],key:"heart_rate"|"speed_kmh"){
  const values=segments.flat().map(p=>finite(p.sample[key])).filter((v):v is number=>v!=null&&v>0);
  const edges=bucketEdges(values);
  if(!edges.length)return [];
  const runs:{d:string;bucket:number}[]=[];
  for(const segment of segments){
    let current:{x:number;y:number}[]=[],bucket=-1;
    for(const p of segment){
      const value=finite(p.sample[key]);
      const next=value!=null&&value>0?bucketOf(value,edges):bucket<0?0:bucket;
      if(bucket>=0&&next!==bucket&&current.length){current.push(p);runs.push({d:pathOf(current),bucket});current=[]}
      bucket=next;current.push(p);
    }
    if(current.length>1)runs.push({d:pathOf(current),bucket});
  }
  return runs;
}

/** Elevation area along distance (or time when distance is missing). */
export function elevationProfile(data:Sample[],box:Box){
  const rows=data.map(r=>({x:finite(r.distance_km)??finite(r.elapsed_s),y:finite(r.altitude_m)})).filter((r):r is {x:number;y:number}=>r.x!=null&&r.y!=null);
  if(rows.length<10)return null;
  const minX=rows[0].x,maxX=rows.at(-1)!.x;if(!(maxX>minX))return null;
  let minY=Infinity,maxY=-Infinity;for(const r of rows){minY=Math.min(minY,r.y);maxY=Math.max(maxY,r.y)}
  const range=Math.max(maxY-minY,8);
  const step=Math.max(1,Math.floor(rows.length/400));
  const pts=rows.filter((_,i)=>i%step===0||i===rows.length-1).map(r=>({x:box.x+(r.x-minX)/(maxX-minX)*box.w,y:box.y+box.h-(r.y-minY)/range*box.h*.9}));
  const line=pathOf(pts);
  return {line,area:`${line}L${(box.x+box.w).toFixed(1)} ${box.y+box.h}L${box.x} ${box.y+box.h}Z`,min:minY,max:maxY};
}

/** A compact pulse/speed wave for activities without GPS. */
export function waveform(data:Sample[],key:"heart_rate"|"speed_kmh"|"power",box:Box){
  const rows=data.map(r=>finite(r[key])).filter((v):v is number=>v!=null&&v>0);
  if(rows.length<10)return null;
  const bins=120,size=rows.length/bins,values:number[]=[];
  for(let i=0;i<bins;i++){const part=rows.slice(Math.floor(i*size),Math.max(Math.floor((i+1)*size),Math.floor(i*size)+1));values.push(part.reduce((a,b)=>a+b,0)/part.length)}
  const min=Math.min(...values),max=Math.max(...values),range=Math.max(max-min,1);
  const width=box.w/bins;
  return values.map((v,i)=>{const h=Math.max(6,(v-min)/range*box.h);return {x:box.x+i*width+width*.2,y:box.y+(box.h-h)/2,w:width*.6,h}});
}

export function defaultZones(maxHr:number):Zone[]{
  return [.5,.6,.7,.8,.9].map((f,i,all)=>({low:Math.round(maxHr*f),high:i<4?Math.round(maxHr*all[i+1])-1:null}));
}

/** Pick the Garmin zone profile for this sport (falls back to the default profile). */
export function zonesFromProfiles(profiles:Sample[]|undefined,kind:Kind):Zone[]|null{
  if(!profiles?.length)return null;
  const wanted=kind==="ride"?"CYCLING":kind==="swim"?"SWIMMING":kind==="run"||kind==="walk"||kind==="hike"?"RUNNING":"DEFAULT";
  const profile=profiles.find(p=>p.sport===wanted)??profiles.find(p=>p.sport==="DEFAULT")??profiles[0];
  const zones=(profile?.zones as Sample[]|undefined)??[];
  const list=zones.map(z=>({low:finite(z.low_bpm),high:finite(z.high_bpm)})).filter(z=>z.low!=null||z.high!=null);
  return list.length>=3?list:null;
}

/** Seconds per zone from recorded samples; gaps longer than 30 s are not counted. */
export function zoneSeconds(data:Sample[],zones:Zone[]){
  const result=zones.map(()=>0);
  for(let i=0;i<data.length-1;i++){
    const hr=finite(data[i].heart_rate),a=finite(data[i].elapsed_s),b=finite(data[i+1].elapsed_s);
    if(hr==null||a==null||b==null)continue;
    const dt=b-a;if(dt<=0||dt>30)continue;
    let index=-1;
    zones.forEach((z,zi)=>{if((z.low==null||hr>=z.low)&&(z.high==null||hr<=z.high))index=zi});
    if(index<0&&zones[0].low!=null&&hr<zones[0].low)continue;
    if(index<0)index=zones.length-1;
    result[index]+=dt;
  }
  return result;
}

/** Best efforts of this activity that are also the personal best of the last year. */
export function personalRecords(activityId:string,activityEfforts:Sample[],personal:Sample[]){
  return activityEfforts.filter(effort=>personal.some(best=>best.activity_id===activityId&&best.metric===effort.metric&&best.seconds===effort.seconds&&Math.abs(Number(best.value)-Number(effort.value))<1e-6));
}

export function effortText(effort:Sample,kind:Kind,lang:Lang){
  const window=`${Math.round(Number(effort.seconds)/60)} min`;
  const value=Number(effort.value);
  const shown=effort.metric==="power"?`${decimal(value,0,lang)} W`:kind==="run"||kind==="walk"||kind==="hike"?`${paceText(3600/value)} /km`:`${decimal(value,1,lang)} km/h`;
  return `${window} · ${shown}`;
}

/** Shorten text for an approximate width; SVG text cannot wrap by itself. */
export function fitText(text:string,maxWidth:number,fontSize:number,measure?:(value:string)=>number){
  const width=measure??((value:string)=>value.length*fontSize*.56);
  if(width(text)<=maxWidth)return text;
  let low=1,high=text.length;
  while(low<high){const mid=Math.ceil((low+high)/2);if(width(text.slice(0,mid).trimEnd()+"…")<=maxWidth)low=mid;else high=mid-1}
  return text.slice(0,Math.max(1,low)).trimEnd()+"…";
}

export function fileName(activity:Sample,format:FormatId){
  const base=String(activity.name??activity.sport_type??"activity").normalize("NFKD").replace(/[^\w\s-]/g,"").trim().replace(/\s+/g,"-").slice(0,48)||"activity";
  const day=String(activity.started_at??activity.activity_date??"").slice(0,10);
  return `PenguCoach-${base}${day?"-"+day:""}-${format}.png`;
}
