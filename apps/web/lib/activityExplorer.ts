export type Sample = Record<string, unknown>;
export type Metric = {key:string;de:string;en:string;unit:string;color:string;digits:number};
export type AxisMode = "time" | "distance";
export type RoutePoint = {index:number;lat:number;lon:number;sample:Sample};
export type MapSettings = {map_enabled:boolean;preferred_provider:"google"|"apple";google_configured:boolean;apple_configured:boolean};

export const METRICS: Metric[] = [
  {key:"heart_rate",de:"Herzfrequenz",en:"Heart rate",unit:"bpm",color:"#d94b4b",digits:0},
  {key:"speed_kmh",de:"Geschwindigkeit",en:"Speed",unit:"km/h",color:"#3578c8",digits:1},
  {key:"pace_s_per_km",de:"Pace",en:"Pace",unit:"min/km",color:"#588bcb",digits:0},
  {key:"altitude_m",de:"Höhe",en:"Elevation",unit:"m",color:"#9b7a3b",digits:0},
  {key:"power",de:"Leistung",en:"Power",unit:"W",color:"#7b61c9",digits:0},
  {key:"cadence",de:"Kadenz",en:"Cadence",unit:"/min",color:"#2d8f7b",digits:0},
  {key:"grade_pct",de:"Steigung (berechnet)",en:"Grade (calculated)",unit:"%",color:"#d77a2f",digits:1},
  {key:"temperature",de:"Temperatur",en:"Temperature",unit:"°C",color:"#6a7b87",digits:1},
  {key:"respiration_rate",de:"Atemfrequenz",en:"Respiration rate",unit:"/min",color:"#438e9b",digits:0},
  {key:"vertical_oscillation",de:"Vertikale Bewegung",en:"Vertical oscillation",unit:"mm",color:"#a65e91",digits:1},
  {key:"stance_time",de:"Bodenkontaktzeit",en:"Ground contact time",unit:"ms",color:"#7972aa",digits:0},
  {key:"vertical_ratio",de:"Vertikales Verhältnis",en:"Vertical ratio",unit:"%",color:"#b48167",digits:1},
  {key:"step_length",de:"Schrittlänge",en:"Step length",unit:"mm",color:"#55936e",digits:0},
];

export function finite(value:unknown):number|null {
  if (value == null || typeof value === "boolean" || (typeof value !== "number" && typeof value !== "string")) return null;
  if (typeof value === "string" && !value.trim()) return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

export function timeLabel(value:unknown):string {
  const number = finite(value);
  if (number == null) return "—";
  const total = Math.max(0, Math.round(number));
  const hours = Math.floor(total / 3600), minutes = Math.floor((total % 3600) / 60), seconds = total % 60;
  return hours ? `${hours}:${String(minutes).padStart(2,"0")}:${String(seconds).padStart(2,"0")}` : `${minutes}:${String(seconds).padStart(2,"0")}`;
}

export function metricLabel(metric:Metric, value:unknown):string {
  const number = finite(value);
  if (number == null) return "—";
  if (metric.key === "pace_s_per_km") {
    const total = Math.round(number);
    return `${Math.floor(total/60)}:${String(total%60).padStart(2,"0")} ${metric.unit}`;
  }
  return `${number.toFixed(metric.digits)} ${metric.unit}`;
}

// Time and distance use their recorded values, including uneven sampling and
// pauses. Incomplete/non-monotonic axes fall back to explicitly labelled points.
export function makeAxis(data:Sample[], mode:AxisMode) {
  const values = data.map(row => finite(row[mode === "time" ? "elapsed_s" : "distance_km"]));
  const valid = values.length > 1 && values.every((v,i) => v != null && (i === 0 || v >= values[i-1]!)) && values.at(-1)! > values[0]!;
  const resolved = valid ? values as number[] : data.map((_,i) => i);
  const start = resolved[0] ?? 0, span = Math.max(1e-9, (resolved.at(-1) ?? 1)-start);
  return {values:resolved, kind:valid ? mode : "points", positions:resolved.map(v => (v-start)/span)};
}

export function nearestIndex(positions:number[], fraction:number):number {
  if (!positions.length) return 0;
  const value = Math.max(0,Math.min(1,fraction));
  let lo = 0, hi = positions.length-1;
  while (lo < hi) {const middle = Math.floor((lo+hi)/2); if (positions[middle] < value) lo = middle+1; else hi = middle;}
  return lo > 0 && value-positions[lo-1] < positions[lo]-value ? lo-1 : lo;
}

export function routeSegments(data:Sample[]):RoutePoint[][] {
  const segments:RoutePoint[][] = [];
  let current:RoutePoint[] = [];
  data.forEach((sample,index) => {
    const lat=finite(sample.position_lat), lon=finite(sample.position_long);
    if (lat == null || lon == null || Math.abs(lat)>90 || Math.abs(lon)>180) {
      if (current.length) segments.push(current);
      current=[]; return;
    }
    const previous = current.at(-1);
    const elapsed = finite(sample.elapsed_s), before = previous ? finite(previous.sample.elapsed_s) : null;
    if (previous && ((elapsed != null && before != null && elapsed-before>120) || sample.track_segment !== previous.sample.track_segment)) {
      segments.push(current); current=[];
    }
    current.push({index,lat,lon,sample});
  });
  if (current.length) segments.push(current);
  return segments;
}

export function extent(data:Sample[], key:string):[number,number] {
  const values=data.map(row=>finite(row[key])).filter((v):v is number=>v!=null);
  if (!values.length) return [0,1];
  let lo=Math.min(...values), hi=Math.max(...values);
  if (lo===hi) {lo-=1;hi+=1;}
  const padding=(hi-lo)*.08;
  return [lo-padding,hi+padding];
}

export function linePath(data:Sample[], metric:Metric, positions:number[], width:number, height:number, padding:number):string {
  const [lo,hi]=extent(data,metric.key);
  let started=false, path="";
  data.forEach((row,i)=>{
    const value=finite(row[metric.key]);
    if (value==null) {started=false;return;}
    const x=padding+(positions[i]??0)*(width-padding*2), y=padding+(hi-value)/(hi-lo)*(height-padding*2);
    path+=`${started?" L":"M"}${x.toFixed(2)} ${y.toFixed(2)}`; started=true;
  });
  return path;
}

export function bearing(points:RoutePoint[], index:number):number {
  const i=points.findIndex(p=>p.index===index), a=points[Math.max(0,i-1)], b=points[Math.min(points.length-1,i+1)];
  if (!a || !b || a===b) return 0;
  const radians=Math.PI/180, delta=(b.lon-a.lon)*radians;
  const y=Math.sin(delta)*Math.cos(b.lat*radians);
  const x=Math.cos(a.lat*radians)*Math.sin(b.lat*radians)-Math.sin(a.lat*radians)*Math.cos(b.lat*radians)*Math.cos(delta);
  return (Math.atan2(y,x)/radians+360)%360;
}
