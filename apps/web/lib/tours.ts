// Tour planner helpers (alpha.87). Pure functions, tested in tests/tours.test.cjs.

export type Coord=[number,number,number|null]; // lon, lat, elevation
export type SportKey="road_bike"|"gravel"|"mtb"|"trekking"|"running"|"trail_running"|"hiking";
export type Variant={id:string;coordinates:Coord[];distance_m:number;ascent_m:number;descent_m:number;duration_s:number;doubled:number;
  paved_share:number;unpaved_share:number;surface:Record<string,number>;ways:Record<string,number>;warnings:string[];deviation:number|null;
  min_elevation_m:number|null;max_elevation_m:number|null;profile:string;bearing?:number;alternative?:number;has_elevation:boolean};

export const SPORTS:{key:SportKey;de:string;en:string;hint:{de:string;en:string}}[]=[
  {key:"road_bike",de:"Rennrad",en:"Road bike",hint:{de:"Asphalt, flüssig fahrbar",en:"Asphalt, smooth riding"}},
  {key:"gravel",de:"Gravel",en:"Gravel",hint:{de:"Schotter und ruhige Wege",en:"Gravel and quiet roads"}},
  {key:"mtb",de:"MTB",en:"MTB",hint:{de:"Trails und Waldwege",en:"Trails and forest tracks"}},
  {key:"trekking",de:"Radtour",en:"Bike tour",hint:{de:"Radwege, gemischter Belag",en:"Cycle paths, mixed surface"}},
  {key:"running",de:"Laufen",en:"Running",hint:{de:"Befestigte Wege, gern ohne Verkehr",en:"Paved paths, traffic-free where possible"}},
  {key:"trail_running",de:"Trailrun",en:"Trail run",hint:{de:"Pfade und Feldwege, weg von Straßen",en:"Trails and tracks away from roads"}},
  {key:"hiking",de:"Wandern",en:"Hiking",hint:{de:"Wanderwege, Dauer nach DIN 33466",en:"Hiking paths, duration by DIN 33466"}},
];
export const WISHES:{key:"low_traffic"|"flat"|"nature";de:string;en:string}[]=[
  {key:"low_traffic",de:"Wenig Verkehr",en:"Low traffic"},
  {key:"flat",de:"Wenig Höhenmeter",en:"Less climbing"},
  {key:"nature",de:"Wald & Wasser",en:"Forest & water"},
];
export const DIRECTIONS:{value:number|null;de:string;en:string}[]=[
  {value:null,de:"Egal",en:"Any"},{value:0,de:"Norden",en:"North"},{value:90,de:"Osten",en:"East"},{value:180,de:"Süden",en:"South"},{value:270,de:"Westen",en:"West"},
];
export const VARIANT_COLORS=["#2d806b","#3064b2","#c0602c"];

const RAD=Math.PI/180;
export function metres(a:{lat:number;lon:number},b:{lat:number;lon:number}){
  const dLat=(b.lat-a.lat)*RAD,dLon=(b.lon-a.lon)*RAD,h=Math.sin(dLat/2)**2+Math.cos(a.lat*RAD)*Math.cos(b.lat*RAD)*Math.sin(dLon/2)**2;
  return 2*6371000*Math.asin(Math.min(1,Math.sqrt(h)));
}

/** Cumulative distance (km) and elevation along the tour, for the profile and the 3D view. */
export function profile(coords:Coord[]){
  const km:number[]=[],ele:(number|null)[]=[];let total=0;
  coords.forEach((c,i)=>{if(i>0)total+=metres({lat:coords[i-1][1],lon:coords[i-1][0]},{lat:c[1],lon:c[0]});km.push(total/1000);ele.push(c[2]==null||!Number.isFinite(c[2])?null:c[2])});
  return {km,ele,total};
}

/** A planned tour as activity-like samples so the existing 2D/3D route maps can show it. */
export function toSamples(coords:Coord[]){
  const {km,ele}=profile(coords);
  let previous:number|null=null,previousKm=0;
  return coords.map((c,i)=>{
    const e=ele[i];let grade:number|null=null;
    if(e!=null&&previous!=null&&km[i]-previousKm>0.05){grade=Math.round((e-previous)/((km[i]-previousKm)*1000)*1000)/10;previous=e;previousKm=km[i]}
    else if(previous==null&&e!=null){previous=e;previousKm=km[i]}
    return {position_lat:c[1],position_long:c[0],distance_km:Math.round(km[i]*1000)/1000,altitude_m:e,grade_pct:grade};
  });
}

/** SVG path of the elevation profile in a W×H box; null when there is no elevation. */
export function profilePath(coords:Coord[],W:number,H:number,pad=4){
  const {km,ele,total}=profile(coords);
  const values=ele.filter((e):e is number=>e!=null);
  if(values.length<2||total<=0)return null;
  let lo=Math.min(...values),hi=Math.max(...values);
  if(hi-lo<30){const mid=(hi+lo)/2;lo=mid-15;hi=mid+15}
  const x=(k:number)=>pad+(k/(total/1000))*(W-pad*2),y=(e:number)=>H-pad-(e-lo)/(hi-lo)*(H-pad*2);
  let line="";
  ele.forEach((e,i)=>{if(e==null)return;line+=`${line?"L":"M"}${x(km[i]).toFixed(1)},${y(e).toFixed(1)}`});
  return {line,area:`${line}L${x(km.at(-1)!).toFixed(1)},${H-pad}L${x(0).toFixed(1)},${H-pad}Z`,lo,hi,x,y,km};
}

const xml=(value:string)=>value.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;").replace(/'/g,"&apos;");

/** GPX 1.1 track – imports into Garmin Connect (Courses), Komoot, Strava, Wahoo, OsmAnd and most watches. */
export function gpx(name:string,coords:Coord[],type="cycling",description=""){
  const points=coords.map(c=>`      <trkpt lat="${c[1].toFixed(6)}" lon="${c[0].toFixed(6)}">${c[2]==null?"":`<ele>${(Math.round(c[2]*10)/10).toFixed(1)}</ele>`}</trkpt>`).join("\n");
  return `<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="PenguCoach" xmlns="http://www.topografix.com/GPX/1/1" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:schemaLocation="http://www.topografix.com/GPX/1/1 http://www.topografix.com/GPX/1/1/gpx.xsd">
  <metadata><name>${xml(name)}</name>${description?`<desc>${xml(description)}</desc>`:""}</metadata>
  <trk>
    <name>${xml(name)}</name>
    <type>${xml(type)}</type>
    <trkseg>
${points}
    </trkseg>
  </trk>
</gpx>
`;
}

export function fileName(name:string){
  const clean=name.normalize("NFKD").replace(/[̀-ͯ]/g,"").replace(/ß/g,"ss").replace(/[^A-Za-z0-9 _-]+/g,"").trim().replace(/\s+/g,"-").slice(0,60);
  return `${clean||"tour"}.gpx`;
}

export function formatKm(m:number){return m>=10000?`${(m/1000).toFixed(0)} km`:`${(m/1000).toFixed(1)} km`}
export function formatDuration(s:number){const total=Math.round(s/60),h=Math.floor(total/60),m=total%60;return h?`${h}:${String(m).padStart(2,"0")} h`:`${m} min`}

export function suggestName(sport:SportKey,km:number,round:boolean,place:string,de:boolean){
  const s=SPORTS.find(x=>x.key===sport)!;
  const kind=round?(de?"Runde":"loop"):(de?"Strecke":"route");
  return `${de?s.de:s.en} ${kind} ${Math.round(km)} km${place?` · ${place}`:""}`.slice(0,120);
}

export const WARNINGS:Record<string,{de:string;en:string}>={
  LENGTH_OFF:{de:"Länge weicht deutlich vom Wunsch ab – das Wegenetz gibt hier nicht mehr her.",en:"Length differs clearly from the wish – the path network here allows no better fit."},
  OUT_AND_BACK:{de:"Ein Teil wird hin und zurück gefahren.",en:"Part of it is ridden out and back."},
  UNPAVED_FOR_ROAD_BIKE:{de:"Enthält unbefestigte Abschnitte – mit dem Rennrad prüfen.",en:"Contains unpaved sections – check with a road bike."},
  MANY_ROADS:{de:"Viel Straße für diese Sportart.",en:"A lot of road for this sport."},
  FERRY:{de:"Enthält eine Fähre.",en:"Includes a ferry."},
};

export const ERRORS:Record<string,{de:string;en:string}>={
  POINT_NOT_ON_NETWORK:{de:"Am Start- oder Zielpunkt gibt es keinen passenden Weg. Setze den Punkt näher an eine Straße oder einen Weg.",en:"There is no suitable path at the start or end point. Move it closer to a road or path."},
  POINT_ISOLATED:{de:"Der Punkt liegt auf einem abgeschnittenen Wegstück (z. B. Privatgelände). Bitte verschieben.",en:"The point is on a cut-off piece of path (e.g. private grounds). Please move it."},
  AREA_NOT_COVERED:{de:"Der Routing-Server hat für diese Gegend keine Kartendaten.",en:"The routing server has no map data for this area."},
  PROFILE_UNKNOWN:{de:"Der Routing-Server kennt das Profil dieser Sportart nicht.",en:"The routing server does not know this sport's profile."},
  ROUTING_TOO_LONG:{de:"Die Berechnung dauerte zu lange. Versuch eine kürzere Tour.",en:"Routing took too long. Try a shorter tour."},
  ROUTING_TIMEOUT:{de:"Der Routing-Server antwortet nicht rechtzeitig. Gleich noch einmal versuchen.",en:"The routing server did not answer in time. Try again shortly."},
  ROUTER_UNREACHABLE:{de:"Der Routing-Server ist nicht erreichbar. PenguCoach braucht dafür Internet (brouter.de) oder einen eigenen BRouter im Netz.",en:"The routing server cannot be reached. PenguCoach needs internet (brouter.de) or your own BRouter on the network."},
  SERVER_BUSY:{de:"Der Routing-Server ist gerade ausgelastet. Bitte in einer Minute erneut versuchen.",en:"The routing server is busy. Please try again in a minute."},
  DISTANCE_OUT_OF_RANGE:{de:"Diese Länge passt nicht zur Sportart.",en:"This length does not fit the sport."},
  END_REQUIRED:{de:"Bitte ein Ziel wählen.",en:"Please choose a destination."},
  START_EQUALS_END:{de:"Start und Ziel liegen fast am selben Ort – wähle dafür „Rundkurs“.",en:"Start and destination are almost the same place – choose “Loop” instead."},
  BROUTER_URL_INVALID:{de:"Die Adresse ist ungültig. Beispiel: http://192.168.1.50:17777",en:"The address is invalid. Example: http://192.168.1.50:17777"},
  ROUTING_FAILED:{de:"Für diese Vorgaben wurde keine Tour gefunden.",en:"No tour was found for these settings."},
};
export function errorText(code:string,de:boolean){const e=ERRORS[code];return e?(de?e.de:e.en):(de?`Tour konnte nicht geplant werden (${code}).`:`Could not plan the tour (${code}).`)}

/** Surface bar segments in a fixed order. */
export function surfaceBar(surface:Record<string,number>){
  const order:[string,string,{de:string;en:string}][]=[
    ["paved","#3d4a55",{de:"Asphalt/befestigt",en:"Paved"}],["paved_probably","#7b8792",{de:"vermutlich befestigt",en:"probably paved"}],
    ["unpaved_probably","#c9a46a",{de:"vermutlich unbefestigt",en:"probably unpaved"}],["unpaved","#9a6b2f",{de:"unbefestigt",en:"unpaved"}],["unknown","#c7cdd1",{de:"unbekannt",en:"unknown"}]];
  return order.filter(([k])=>(surface[k]??0)>0).map(([key,color,label])=>({key,color,label,share:surface[key]}));
}
