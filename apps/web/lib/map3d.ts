// 3D route map helpers (alpha.86). Pure functions, tested in tests/map3d.test.cjs.
import {extent,finite,type Metric,type RoutePoint,type Sample} from "./activityExplorer";

export const ROUTE_COLORS=["#3064b2","#327fc2","#369ccc","#42aec0","#60b79c","#9db974","#cfba5b","#e8ac49","#ed8a3e","#e15f37","#c9443d"];
export const GAP_COLOR="#919b99";

/** Free, key-less tile sources. The browser loads them directly, like the 2D map. */
export const TILES={
  osm:{tiles:["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],maxzoom:19,attribution:'© <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a>'},
  topo:{tiles:["https://a.tile.opentopomap.org/{z}/{x}/{y}.png","https://b.tile.opentopomap.org/{z}/{x}/{y}.png","https://c.tile.opentopomap.org/{z}/{x}/{y}.png"],maxzoom:17,attribution:'© <a href="https://opentopomap.org" target="_blank" rel="noopener">OpenTopoMap</a> (CC-BY-SA) · © OpenStreetMap'},
  // Mapzen/Tilezen terrain tiles on AWS Open Data, terrarium encoding, no key.
  dem:{tiles:["https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"],maxzoom:15,attribution:'Höhen: <a href="https://registry.opendata.aws/terrain-tiles/" target="_blank" rel="noopener">Terrain Tiles (AWS)</a>'},
} as const;

export type Coloured={type:"FeatureCollection";features:{type:"Feature";properties:{color:string;gap:boolean};geometry:{type:"LineString";coordinates:[number,number][]}}[]};

/** Route as coloured line pieces: consecutive segments of the same colour band are merged,
 * so a 10 000-point recording becomes a few hundred features instead of 10 000. */
export function colouredRoute(segments:RoutePoint[][], data:Sample[], metric:Metric|null, accent:string):Coloured{
  const features:Coloured["features"]=[];
  const [lo,hi]=metric?extent(data,metric.key):[0,1];
  for(const segment of segments){
    if(segment.length<2)continue;
    if(!metric){features.push({type:"Feature",properties:{color:accent,gap:false},geometry:{type:"LineString",coordinates:segment.map(p=>[p.lon,p.lat])}});continue}
    let current:[number,number][]=[],band=-2;
    const flush=()=>{if(current.length>1)features.push({type:"Feature",properties:{color:band===ROUTE_COLORS.length?GAP_COLOR:ROUTE_COLORS[band],gap:band===ROUTE_COLORS.length},geometry:{type:"LineString",coordinates:current}})};
    for(let i=1;i<segment.length;i++){
      const a=segment[i-1],b=segment[i],x=finite(a.sample[metric.key]),y=finite(b.sample[metric.key]);
      const value=x!=null&&y!=null?(x+y)/2:null;
      const next=value==null?ROUTE_COLORS.length:Math.max(0,Math.min(ROUTE_COLORS.length-1,Math.floor((value-lo)/(hi-lo)*ROUTE_COLORS.length)));
      if(next!==band){flush();current=[[a.lon,a.lat]];band=next}
      current.push([b.lon,b.lat]);
    }
    flush();
  }
  return {type:"FeatureCollection",features};
}

const RAD=Math.PI/180;
export function metres(a:{lat:number;lon:number},b:{lat:number;lon:number}){
  const dLat=(b.lat-a.lat)*RAD,dLon=(b.lon-a.lon)*RAD,h=Math.sin(dLat/2)**2+Math.cos(a.lat*RAD)*Math.cos(b.lat*RAD)*Math.sin(dLon/2)**2;
  return 2*6371000*Math.asin(Math.min(1,Math.sqrt(h)));
}
export function heading(a:{lat:number;lon:number},b:{lat:number;lon:number}){
  const y=Math.sin((b.lon-a.lon)*RAD)*Math.cos(b.lat*RAD),x=Math.cos(a.lat*RAD)*Math.sin(b.lat*RAD)-Math.sin(a.lat*RAD)*Math.cos(b.lat*RAD)*Math.cos((b.lon-a.lon)*RAD);
  return (Math.atan2(y,x)/RAD+360)%360;
}

/** Cumulative metres along all route points (gaps between segments are not counted). */
export function along(segments:RoutePoint[][]){
  const points:RoutePoint[]=[],distance:number[]=[];let total=0;
  for(const segment of segments)segment.forEach((p,i)=>{if(i>0)total+=metres(segment[i-1],p);points.push(p);distance.push(total)});
  return {points,distance,total};
}

/** Position at a distance along the route, interpolated between fixes, with the nearest sample index. */
export function positionAt(route:ReturnType<typeof along>, metresAlong:number){
  const {points,distance}=route;
  if(!points.length)return null;
  const target=Math.max(0,Math.min(route.total,metresAlong));
  let lo=0,hi=distance.length-1;
  while(lo<hi){const mid=(lo+hi)>>1;if(distance[mid]<target)lo=mid+1;else hi=mid}
  const b=points[lo],a=points[Math.max(0,lo-1)],span=distance[lo]-distance[Math.max(0,lo-1)];
  const t=span>0?(target-distance[Math.max(0,lo-1)])/span:0;
  return {lat:a.lat+(b.lat-a.lat)*t,lon:a.lon+(b.lon-a.lon)*t,index:t<.5?a.index:b.index};
}

/** Camera heading for the flyover: look ~400 m ahead so turns are smooth, not twitchy. */
export function lookAhead(route:ReturnType<typeof along>, metresAlong:number, ahead=400){
  const here=positionAt(route,metresAlong),there=positionAt(route,Math.min(route.total,metresAlong+ahead));
  if(!here||!there)return 0;
  if(metres(here,there)<5){const back=positionAt(route,Math.max(0,metresAlong-ahead));return back?heading(back,here):0}
  return heading(here,there);
}

/** Turn towards a new heading by the shortest way, limited per frame. */
export function turnTowards(current:number,target:number,maxStep:number){
  const delta=((target-current+540)%360)-180;
  return (current+Math.max(-maxStep,Math.min(maxStep,delta))+360)%360;
}

/** Nearest route point to a screen position along the drawn segments (not only fixes). */
export function nearestOnScreen(segments:RoutePoint[][], project:(lon:number,lat:number)=>{x:number;y:number}, x:number, y:number, radius:number){
  let best=-1,distance=radius*radius;
  for(const segment of segments){
    let previous=project(segment[0].lon,segment[0].lat);
    if(segment.length===1){const d=(previous.x-x)**2+(previous.y-y)**2;if(d<distance){distance=d;best=segment[0].index}continue}
    for(let i=1;i<segment.length;i++){
      const current=project(segment[i].lon,segment[i].lat);
      const dx=current.x-previous.x,dy=current.y-previous.y,len=dx*dx+dy*dy;
      const t=len?Math.max(0,Math.min(1,((x-previous.x)*dx+(y-previous.y)*dy)/len)):0;
      const d=(previous.x+t*dx-x)**2+(previous.y+t*dy-y)**2;
      if(d<distance){distance=d;best=t<.5?segment[i-1].index:segment[i].index}
      previous=current;
    }
  }
  return best;
}

/** Overall direction of a route (start → its farthest point), used to tilt the first 3D view along the tour. */
export function mainHeading(points:RoutePoint[]){
  if(points.length<2)return 0;
  const start=points[0];let far=points[1],best=0;
  for(const p of points){const d=metres(start,p);if(d>best){best=d;far=p}}
  return heading(start,far);
}
