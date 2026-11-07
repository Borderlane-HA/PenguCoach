"use client";
// alpha.87 Tour planner: round trips or A→B per sport, routed by BRouter (no key),
// three variants with elevation profile, surface mix, 3D preview, GPX export and saved tours.
import {useEffect,useMemo,useRef,useState} from "react";
import dynamic from "next/dynamic";
import AppShell from "../../components/AppShell";
import TourMap,{type LatLon} from "../../components/TourMap";
import {api} from "../../lib/api";
import {useCachedQuery} from "../../lib/data-cache";
import {useI18n} from "../../lib/i18n";
import {METRICS} from "../../lib/activityExplorer";
import {DIRECTIONS,errorText,fileName,formatDuration,formatKm,gpx,profile,profilePath,SPORTS,suggestName,surfaceBar,toSamples,VARIANT_COLORS,WARNINGS,WISHES,type Coord,type SportKey,type Variant} from "../../lib/tours";

const ActivityRouteMap3D=dynamic(()=>import("../../components/ActivityRouteMap3D"),{ssr:false,loading:()=><div className="tour-map-shell"><div className="tour-map map3d-loading-box">…</div></div>});
type O=Record<string,any>;
type Place={name:string;latitude:number;longitude:number;admin1?:string;country?:string};
const STORE="pengucoach_tour_form";
const read=()=>{try{return JSON.parse(localStorage.getItem(STORE)||"{}")}catch{return {}}};

function download(name:string,text:string){
  const url=URL.createObjectURL(new Blob([text],{type:"application/gpx+xml"}));
  const a=document.createElement("a");a.href=url;a.download=name;document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),2000);
}

function PlaceSearch({de,label,onPick}:{de:boolean;label:string;onPick:(p:LatLon,name:string)=>void}){
  const [q,setQ]=useState(""),[rows,setRows]=useState<Place[]>([]),[busy,setBusy]=useState(false),[error,setError]=useState("");
  async function search(){if(q.trim().length<2)return;setBusy(true);setError("");try{const r=await api<{results:Place[]}>(`/tours/places?q=${encodeURIComponent(q.trim())}&language=${de?"de":"en"}`);setRows(r.results);if(!r.results.length)setError(de?"Kein Ort gefunden.":"No place found.")}catch{setError(de?"Ortssuche gerade nicht erreichbar.":"Place search is not reachable right now.")}finally{setBusy(false)}}
  return <div className="tour-search">
    <div className="tour-search-row"><input value={q} onChange={e=>setQ(e.target.value)} onKeyDown={e=>{if(e.key==="Enter"){e.preventDefault();void search()}}} placeholder={de?"Ort suchen, z. B. Eichstätt":"Search a place, e.g. Munich"} aria-label={label}/><button type="button" className="ghost compact" onClick={search} disabled={busy||q.trim().length<2}>{busy?"…":(de?"Suchen":"Search")}</button></div>
    {error&&<small className="muted">{error}</small>}
    {rows.length>0&&<ul className="tour-search-results">{rows.slice(0,6).map((r,i)=><li key={i}><button type="button" onClick={()=>{onPick({lat:r.latitude,lon:r.longitude},r.name);setRows([]);setQ(r.name)}}><strong>{r.name}</strong><small>{[r.admin1,r.country].filter(Boolean).join(", ")}</small></button></li>)}</ul>}
  </div>;
}

function Profile({v,de,hover,onHover}:{v:Variant;de:boolean;hover:number|null;onHover:(i:number|null)=>void}){
  const W=900,H=150;
  const p=useMemo(()=>profilePath(v.coordinates,W,H,6),[v]);
  const {km}=useMemo(()=>profile(v.coordinates),[v]);
  if(!p)return <p className="muted tour-profile-empty">{de?"Für diese Tour liefert der Routing-Server keine Höhen.":"The routing server returned no elevation for this tour."}</p>;
  const index=(e:React.PointerEvent<SVGSVGElement>)=>{const r=e.currentTarget.getBoundingClientRect();const target=((e.clientX-r.left)/r.width*W-6)/(W-12)*km.at(-1)!;let lo=0,hi=km.length-1;while(lo<hi){const m=(lo+hi)>>1;if(km[m]<target)lo=m+1;else hi=m}return lo};
  const c=hover!=null?v.coordinates[hover]:null;
  return <div className="tour-profile">
    <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" role="img" aria-label={de?`Höhenprofil, ${Math.round(p.lo)} bis ${Math.round(p.hi)} m`:`Elevation profile, ${Math.round(p.lo)} to ${Math.round(p.hi)} m`}
      onPointerMove={e=>onHover(index(e))} onPointerDown={e=>onHover(index(e))} onPointerLeave={()=>onHover(null)}>
      <defs><linearGradient id="tour-profile-fill" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stopColor="var(--accent)" stopOpacity=".45"/><stop offset="1" stopColor="var(--accent)" stopOpacity=".04"/></linearGradient></defs>
      <path d={p.area} fill="url(#tour-profile-fill)"/><path d={p.line} fill="none" stroke="var(--accent)" strokeWidth="2.2" vectorEffect="non-scaling-stroke"/>
      {c&&c[2]!=null&&<><line x1={p.x(km[hover!])} x2={p.x(km[hover!])} y1="0" y2={H} stroke="var(--text)" strokeDasharray="4 4" vectorEffect="non-scaling-stroke" opacity=".6"/><circle cx={p.x(km[hover!])} cy={p.y(c[2])} r="5" fill="var(--panel)" stroke="var(--text)" strokeWidth="2" vectorEffect="non-scaling-stroke"/></>}
    </svg>
    <div className="tour-profile-scale"><span>{Math.round(p.hi)} m</span><span>{Math.round(p.lo)} m</span></div>
    <div className="tour-profile-readout" aria-live="polite">{c?<>{km[hover!].toFixed(1)} km{c[2]!=null&&<> · {Math.round(c[2])} m</>}</>:<>{de?"Über das Profil fahren zeigt die Stelle auf der Karte":"Move over the profile to see the spot on the map"}</>}</div>
  </div>;
}

function ExportHelp({open,onClose,de}:{open:boolean;onClose:()=>void;de:boolean}){
  const ref=useRef<HTMLDialogElement>(null);
  useEffect(()=>{const d=ref.current;if(!d)return;if(open&&!d.open)d.showModal();if(!open&&d.open)d.close()},[open]);
  return <dialog ref={ref} className="race-dialog" aria-labelledby="tour-export-title" onClose={onClose} onClick={e=>{if(e.target===e.currentTarget)onClose()}}>
      <div className="race-dialog-inner tour-export">
        <h2 id="tour-export-title">{de?"Tour auf Uhr, Garmin oder Komoot":"Tour to watch, Garmin or Komoot"}</h2>
        <ol>
          <li><strong>{de?"GPX herunterladen":"Download the GPX"}</strong> – {de?"Knopf beim Vorschlag oder bei der gespeicherten Tour. GPX ist das offene Austauschformat für Strecken, mit Linie und Höhen.":"button at the suggestion or the saved tour. GPX is the open exchange format for routes, with line and elevation."}</li>
          <li><strong>Garmin Connect</strong> – {de?"im Browser: Training & Planung → Strecken → „Strecke importieren“, die GPX-Datei wählen, Sportart prüfen, speichern. Danach „An Gerät senden“; die Uhr holt sie beim nächsten Sync.":"in the browser: Training & Planning → Courses → “Import”, choose the GPX file, check the sport, save. Then “Send to device”; the watch gets it with the next sync."}</li>
          <li><strong>{de?"Garmin Edge per Kabel":"Garmin Edge by cable"}</strong> – {de?"die GPX-Datei in den Ordner Garmin/NewFiles kopieren.":"copy the GPX file into the Garmin/NewFiles folder."}</li>
          <li><strong>Komoot</strong> – {de?"im Browser bei „Planen“ die GPX-Datei importieren; Komoot übernimmt die Linie als eigene Tour und kann sie an die Uhr oder das Navi schicken.":"import the GPX file in “Plan” in the browser; Komoot turns the line into your tour and can send it to your watch or bike computer."}</li>
          <li><strong>{de?"Andere Apps":"Other apps"}</strong> – {de?"Strava, Wahoo, Hammerhead, OsmAnd, Locus und die meisten Uhren lesen GPX ebenfalls.":"Strava, Wahoo, Hammerhead, OsmAnd, Locus and most watches read GPX as well."}</li>
        </ol>
        <p className="muted">{de?"Ein direktes Senden ist bewusst nicht eingebaut: Komoot hat dafür keine offene Schnittstelle, und das Strecken-Hochladen zu Garmin ist nicht offiziell freigegeben. Der Weg über GPX funktioniert dagegen zuverlässig.":"Direct sending is deliberately not built in: Komoot has no open interface for it, and uploading courses to Garmin is not officially available. The GPX route works reliably."}</p>
        <div className="row"><button type="button" onClick={onClose}>{de?"Verstanden":"Got it"}</button></div>
      </div>
  </dialog>;
}

export default function ToursPage(){
  const {lang}=useI18n(),de=lang==="de";
  const options=useCachedQuery<O>("/tours/options",60000);
  const saved=useCachedQuery<{items:O[]}>("/tours",30000);
  const [sport,setSport]=useState<SportKey>("road_bike"),[mode,setMode]=useState<"round"|"a_to_b">("round");
  const [km,setKm]=useState(60),[direction,setDirection]=useState<number|null>(null),[wishes,setWishes]=useState<string[]>([]);
  const [start,setStart]=useState<LatLon|null>(null),[startName,setStartName]=useState(""),[end,setEnd]=useState<LatLon|null>(null),[endName,setEndName]=useState("");
  const [pick,setPick]=useState<"start"|"end"|null>(null),[variants,setVariants]=useState<Variant[]>([]),[selected,setSelected]=useState<string|null>(null);
  const [busy,setBusy]=useState(false),[error,setError]=useState(""),[seed,setSeed]=useState(0),[hover,setHover]=useState<number|null>(null);
  const [view,setView]=useState<"2d"|"3d">("2d"),[view3dError,setView3dError]=useState(""),[naming,setNaming]=useState<string|null>(null),[notice,setNotice]=useState("");
  const [shownSaved,setShownSaved]=useState<(Variant&{name:string;sport:SportKey})|null>(null),[confirmDelete,setConfirmDelete]=useState<string|null>(null),[exportHelp,setExportHelp]=useState(false);
  const [server,setServer]=useState(""),[serverResult,setServerResult]=useState<O|null>(null);
  const loaded=useRef(false);

  // Remember the form per browser; start at the training location the first time.
  useEffect(()=>{const f=read();if(f.sport&&SPORTS.some(s=>s.key===f.sport))setSport(f.sport);if(f.mode)setMode(f.mode);if(f.km)setKm(f.km);if(Array.isArray(f.wishes))setWishes(f.wishes);if(f.direction!==undefined)setDirection(f.direction);if(f.start){setStart(f.start);setStartName(f.startName||"")}if(f.end){setEnd(f.end);setEndName(f.endName||"")}loaded.current=true},[]);
  useEffect(()=>{if(!loaded.current)return;try{localStorage.setItem(STORE,JSON.stringify({sport,mode,km,wishes,direction,start,startName,end,endName}))}catch{}},[sport,mode,km,wishes,direction,start,startName,end,endName]);
  const home=options.data?.home as {lat:number;lon:number;name:string}|null|undefined;
  useEffect(()=>{if(home&&!start&&loaded.current&&!read().start){setStart({lat:home.lat,lon:home.lon});setStartName(home.name)}},[home]);// eslint-disable-line react-hooks/exhaustive-deps
  useEffect(()=>{if(options.data?.server)setServer(options.data.server.is_default?"":options.data.server.url)},[options.data?.server?.url]);// eslint-disable-line react-hooks/exhaustive-deps

  const sportInfo=(options.data?.sports as O[]|undefined)?.find(s=>s.key===sport);
  const range={min:sportInfo?.min_km??2,max:sportInfo?.max_km??250};
  function chooseSport(key:SportKey){setSport(key);const info=(options.data?.sports as O[]|undefined)?.find(s=>s.key===key);if(info&&(km<info.min_km||km>info.max_km||variants.length===0))setKm(info.default_km);setVariants([]);setSelected(null)}
  const current=shownSaved??variants.find(v=>v.id===selected)??null;
  const canPlan=!!start&&(mode==="round"||!!end)&&!busy;

  async function plan(nextSeed=seed){
    if(!start)return;setBusy(true);setError("");setNotice("");setShownSaved(null);setHover(null);
    try{
      const r=await api<{variants:Variant[]}>("/tours/plan",{method:"POST",body:JSON.stringify({sport,mode,start,end:mode==="a_to_b"?end:null,distance_km:mode==="round"?km:null,direction:mode==="round"?direction:null,preferences:wishes,variants:3,seed:nextSeed})});
      setVariants(r.variants);setSelected(r.variants[0]?.id??null);setSeed(nextSeed);
    }catch(e){setVariants([]);setSelected(null);setError(errorText(e instanceof Error?e.message:String(e),de))}finally{setBusy(false)}
  }
  function onPick(which:"start"|"end",p:LatLon){
    if(which==="start"){setStart(p);setStartName(de?"Punkt auf der Karte":"Point on the map")}else{setEnd(p);setEndName(de?"Punkt auf der Karte":"Point on the map")}
    setPick(null);setVariants([]);setSelected(null);setShownSaved(null);
  }
  function locate(){navigator.geolocation.getCurrentPosition(pos=>{onPick("start",{lat:pos.coords.latitude,lon:pos.coords.longitude});setStartName(de?"Mein Standort":"My location")},()=>setError(de?"Standort nicht verfügbar – bitte auf der Karte wählen.":"Location unavailable – please pick on the map."),{enableHighAccuracy:true,timeout:10000})}
  const gpxType=(s:SportKey)=>(options.data?.sports as O[]|undefined)?.find(x=>x.key===s)?.gpx_type??"cycling";
  function exportGpx(v:Variant,name:string,s:SportKey){download(fileName(name),gpx(name,v.coordinates as Coord[],gpxType(s),`PenguCoach · ${formatKm(v.distance_m)} · ↑ ${Math.round(v.ascent_m)} m`))}
  async function save(name:string){
    const v=variants.find(x=>x.id===selected);if(!v)return;
    try{await api("/tours",{method:"POST",body:JSON.stringify({name,sport,mode,coordinates:v.coordinates,summary:{...v,coordinates:undefined,start_name:startName,end_name:mode==="a_to_b"?endName:"",preferences:wishes}})});setNaming(null);setNotice(de?`„${name}“ gespeichert.`:`“${name}” saved.`);await saved.refresh()}
    catch(e){setError(errorText(e instanceof Error?e.message:String(e),de))}
  }
  async function showSaved(t:O){try{const full=await api<O>(`/tours/${t.id}`);setVariants([]);setSelected(null);setHover(null);setShownSaved({...(full.summary||{}),id:full.id,name:full.name,sport:full.sport,coordinates:full.coordinates,distance_m:full.distance_m,ascent_m:full.ascent_m,duration_s:full.duration_s,descent_m:full.summary?.descent_m??0,surface:full.summary?.surface??{},ways:full.summary?.ways??{},warnings:[],deviation:null} as any);window.scrollTo({top:0,behavior:"smooth"})}catch(e){setError(errorText(e instanceof Error?e.message:String(e),de))}}
  async function savedGpx(t:O){const full=await api<O>(`/tours/${t.id}`);download(fileName(full.name),gpx(full.name,full.coordinates,gpxType(full.sport)))}
  async function remove(id:string){await api(`/tours/${id}`,{method:"DELETE"});setConfirmDelete(null);if(shownSaved?.id===id)setShownSaved(null);await saved.refresh()}
  async function saveServer(){setServerResult(null);try{await api("/tours/server/settings",{method:"PUT",body:JSON.stringify({url:server})});await options.refresh();setServerResult({ok:true,saved:true})}catch(e){setServerResult({ok:false,code:e instanceof Error?e.message:String(e)})}}
  async function testServer(){setServerResult({testing:true});try{setServerResult(await api<O>("/tours/server/test",{method:"POST",body:JSON.stringify({url:server,near:start})}))}catch(e){setServerResult({ok:false,code:e instanceof Error?e.message:String(e)})}}

  const samples=useMemo(()=>current?toSamples(current.coordinates as Coord[]):[],[current]);
  const altitude=METRICS.find(m=>m.key==="altitude_m")??null;
  const secure=typeof window!=="undefined"&&window.isSecureContext&&"geolocation" in navigator;
  const readout=current&&hover!=null&&samples[hover]?<div className="chart-readout on-map"><div><span>{de?"Distanz":"Distance"}</span><strong>{Number(samples[hover].distance_km).toFixed(1)} km</strong></div>{samples[hover].altitude_m!=null&&<div><span>{de?"Höhe":"Elevation"}</span><strong>{Math.round(Number(samples[hover].altitude_m))} m</strong></div>}</div>:null;

  return <AppShell title={de?"Touren planen":"Plan tours"}>
    <div className="tour-page">
      <section className="tour-layout">
        <div className="tour-main">
          {view==="3d"&&current&&!view3dError
            ?<ActivityRouteMap3D data={samples} index={hover} colorMetric={altitude} onSelect={i=>setHover(i)} onHover={setHover} de={de} overlay={readout} onUnavailable={r=>setView3dError(r)}/>
            :<TourMap start={shownSaved?null:start} end={shownSaved?null:end} mode={mode} variants={variants} selected={selected} hover={hover} pick={pick} onPick={onPick} onSelect={id=>{setSelected(id);setHover(null)}} de={de} saved={shownSaved}/>}
          <div className="tour-map-bar">
            <div className="chart-segmented map-view-switch" role="radiogroup" aria-label={de?"Kartenansicht":"Map view"}>
              <button type="button" role="radio" aria-checked={view==="2d"||!current} className={view==="2d"||!current?"active":""} onClick={()=>setView("2d")}>{de?"Planen":"Plan"}</button>
              <button type="button" role="radio" aria-checked={view==="3d"&&!!current} className={view==="3d"&&current?"active":""} disabled={!current||view3dError==="NO_WEBGL"} onClick={()=>{setView3dError("");setView("3d")}}>3D</button>
            </div>
            {view3dError&&<small className="muted">{de?"3D ist in diesem Browser nicht verfügbar.":"3D is not available in this browser."}</small>}
            {!current&&<small className="muted">{mode==="round"?(de?"Tippe auf die Karte, um den Start zu setzen.":"Tap the map to set the start."):(de?"Erster Tipp setzt den Start, der zweite das Ziel. Punkte lassen sich ziehen.":"First tap sets the start, the second the destination. Pins can be dragged.")}</small>}
          </div>
          {current&&<Profile v={current} de={de} hover={hover} onHover={setHover}/>}
        </div>

        <aside className="tour-side">
          <div className="tour-block">
            <h2>{de?"Sportart":"Sport"}</h2>
            <div className="tour-sports" role="radiogroup" aria-label={de?"Sportart":"Sport"}>{SPORTS.map(s=><button type="button" role="radio" aria-checked={sport===s.key} key={s.key} className={sport===s.key?"active":""} onClick={()=>chooseSport(s.key)}><strong>{de?s.de:s.en}</strong><small>{de?s.hint.de:s.hint.en}</small></button>)}</div>
          </div>
          <div className="tour-block">
            <div className="chart-segmented tour-mode" role="radiogroup" aria-label={de?"Art der Tour":"Tour type"}>
              <button type="button" role="radio" aria-checked={mode==="round"} className={mode==="round"?"active":""} onClick={()=>{setMode("round");setVariants([]);setSelected(null)}}>{de?"Rundkurs":"Loop"}</button>
              <button type="button" role="radio" aria-checked={mode==="a_to_b"} className={mode==="a_to_b"?"active":""} onClick={()=>{setMode("a_to_b");setVariants([]);setSelected(null)}}>{de?"Von A nach B":"A to B"}</button>
            </div>
            <div className="tour-point">
              <div className="tour-point-head"><span className="tour-dot start">{mode==="round"?"⟳":"A"}</span><strong>{de?"Start":"Start"}</strong><span className="muted">{start?(startName||`${start.lat.toFixed(4)}, ${start.lon.toFixed(4)}`):(de?"noch nicht gesetzt":"not set yet")}</span></div>
              <div className="tour-point-actions">
                {home&&<button type="button" className="ghost compact" onClick={()=>{onPick("start",{lat:home.lat,lon:home.lon});setStartName(home.name||(de?"Trainingsort":"Training location"))}}>{de?"Trainingsort":"Training location"}</button>}
                {secure&&<button type="button" className="ghost compact" onClick={locate}>{de?"Mein Standort":"My location"}</button>}
                <button type="button" className={`ghost compact ${pick==="start"?"active":""}`} onClick={()=>setPick(pick==="start"?null:"start")}>{de?"Auf Karte wählen":"Pick on map"}</button>
              </div>
              <PlaceSearch de={de} label={de?"Start suchen":"Search start"} onPick={(p,n)=>{onPick("start",p);setStartName(n)}}/>
            </div>
            {mode==="a_to_b"&&<div className="tour-point">
              <div className="tour-point-head"><span className="tour-dot end">B</span><strong>{de?"Ziel":"Destination"}</strong><span className="muted">{end?(endName||`${end.lat.toFixed(4)}, ${end.lon.toFixed(4)}`):(de?"noch nicht gesetzt":"not set yet")}</span></div>
              <div className="tour-point-actions"><button type="button" className={`ghost compact ${pick==="end"?"active":""}`} onClick={()=>setPick(pick==="end"?null:"end")}>{de?"Auf Karte wählen":"Pick on map"}</button>{start&&end&&<button type="button" className="ghost compact" onClick={()=>{const s=start,sn=startName;setStart(end);setStartName(endName);setEnd(s);setEndName(sn);setVariants([])}}>{de?"Tauschen":"Swap"}</button>}</div>
              <PlaceSearch de={de} label={de?"Ziel suchen":"Search destination"} onPick={(p,n)=>{onPick("end",p);setEndName(n)}}/>
            </div>}
            {mode==="round"&&<>
              <label className="tour-range"><span>{de?"Länge":"Length"} <strong>{km} km</strong></span><input type="range" min={range.min} max={range.max} step={range.max>100?5:1} value={Math.max(range.min,Math.min(range.max,km))} onChange={e=>setKm(Number(e.target.value))}/></label>
              <div className="tour-directions" role="radiogroup" aria-label={de?"Richtung":"Direction"}><span>{de?"Richtung":"Direction"}</span>{DIRECTIONS.map(d=><button type="button" role="radio" aria-checked={direction===d.value} key={String(d.value)} className={direction===d.value?"active":""} onClick={()=>setDirection(d.value)}>{de?d.de:d.en}</button>)}</div>
            </>}
            <div className="tour-wishes">{WISHES.map(w=><label key={w.key} className="tour-check"><input type="checkbox" checked={wishes.includes(w.key)} onChange={e=>setWishes(x=>e.target.checked?[...x,w.key]:x.filter(k=>k!==w.key))}/>{de?w.de:w.en}</label>)}</div>
            <button type="button" className="tour-go" disabled={!canPlan} onClick={()=>plan(variants.length?seed:0)}>{busy?(de?"Touren werden berechnet …":"Planning tours …"):(de?"Touren vorschlagen":"Suggest tours")}</button>
            {!start&&<small className="muted">{de?"Zuerst einen Start wählen.":"Choose a start first."}</small>}
            {error&&<p className="tour-error" role="alert">{error}</p>}
            {notice&&<p className="tour-notice" role="status">{notice}</p>}
          </div>

          {variants.length>0&&<div className="tour-block">
            <div className="between"><h2>{de?"Vorschläge":"Suggestions"}</h2>{mode==="round"&&<button type="button" className="ghost compact" disabled={busy} onClick={()=>plan(seed+1)}>{de?"Andere Vorschläge":"Other suggestions"}</button>}</div>
            <div className="tour-variants">{variants.map((v,i)=>{const active=v.id===selected;return <div key={v.id} className={`tour-variant ${active?"active":""}`}>
              <button type="button" className="tour-variant-pick" aria-pressed={active} onClick={()=>{setSelected(v.id);setHover(null)}}>
                <span className="tour-variant-dot" style={{background:VARIANT_COLORS[i%3]}}/>
                <span className="tour-variant-title">{de?"Variante":"Variant"} {i+1}</span>
                <span className="tour-variant-stats"><b>{formatKm(v.distance_m)}</b><span>↑ {Math.round(v.ascent_m)} m</span><span>⏱ {formatDuration(v.duration_s)}</span></span>
              </button>
              <div className="tour-surface" aria-label={de?"Untergrund":"Surface"}>{surfaceBar(v.surface).map(s=><i key={s.key} style={{width:`${s.share*100}%`,background:s.color}} title={`${de?s.label.de:s.label.en} ${Math.round(s.share*100)} %`}/>)}</div>
              <small className="tour-surface-legend">{Math.round(v.paved_share*100)} % {de?"befestigt":"paved"} · {Math.round(v.unpaved_share*100)} % {de?"unbefestigt":"unpaved"}{v.doubled>0.05&&<> · {Math.round(v.doubled*100)} % {de?"doppelt":"twice"}</>}</small>
              {v.warnings.length>0&&<ul className="tour-warnings">{v.warnings.map(w=><li key={w}>{WARNINGS[w]?(de?WARNINGS[w].de:WARNINGS[w].en):w}</li>)}</ul>}
              {active&&<div className="tour-variant-actions">
                <button type="button" onClick={()=>exportGpx(v,suggestName(sport,v.distance_m/1000,mode==="round",startName,de),sport)}>{de?"GPX herunterladen":"Download GPX"}</button>
                <button type="button" className="ghost" onClick={()=>setNaming(suggestName(sport,v.distance_m/1000,mode==="round",startName,de))}>{de?"Speichern":"Save"}</button>
                <button type="button" className="ghost" onClick={()=>setExportHelp(true)}>{de?"Zu Garmin/Komoot":"To Garmin/Komoot"}</button>
              </div>}
              {active&&naming!=null&&<form className="tour-name" onSubmit={e=>{e.preventDefault();if(naming.trim())void save(naming.trim())}}><input value={naming} maxLength={120} onChange={e=>setNaming(e.target.value)} aria-label={de?"Name der Tour":"Tour name"} autoFocus/><button type="submit" disabled={!naming.trim()}>{de?"Speichern":"Save"}</button><button type="button" className="ghost" onClick={()=>setNaming(null)}>{de?"Abbrechen":"Cancel"}</button></form>}
            </div>})}</div>
            <small className="muted">{options.data?.sports?.find((s:O)=>s.key===sport)?.personal_speed?(de?"Dauer geschätzt aus deinen letzten Aktivitäten dieser Art.":"Duration estimated from your recent activities of this kind."):(de?"Dauer geschätzt mit einem Standardtempo – mit eigenen Aktivitäten wird sie persönlicher.":"Duration estimated with a standard pace – your own activities make it personal.")}</small>
          </div>}

          {shownSaved&&<div className="tour-block">
            <div className="between"><h2>{shownSaved.name}</h2><button type="button" className="ghost compact" onClick={()=>setShownSaved(null)}>{de?"Schließen":"Close"}</button></div>
            <p className="tour-variant-stats"><b>{formatKm(shownSaved.distance_m)}</b><span>↑ {Math.round(shownSaved.ascent_m)} m</span><span>⏱ {formatDuration(shownSaved.duration_s)}</span></p>
            <div className="tour-variant-actions"><button type="button" onClick={()=>exportGpx(shownSaved,shownSaved.name,shownSaved.sport)}>{de?"GPX herunterladen":"Download GPX"}</button><button type="button" className="ghost" onClick={()=>setExportHelp(true)}>{de?"Zu Garmin/Komoot":"To Garmin/Komoot"}</button></div>
          </div>}
        </aside>
      </section>

      <section className="card tour-saved">
        <div className="between"><h2>{de?"Gespeicherte Touren":"Saved tours"}</h2><span className="muted">{saved.data?.items.length??0}</span></div>
        {saved.data?.items.length?<ul>{saved.data.items.map(t=>{const pts=(t.preview as number[][])||[];const xs=pts.map(p=>p[0]),ys=pts.map(p=>p[1]);const [x0,x1,y0,y1]=[Math.min(...xs),Math.max(...xs),Math.min(...ys),Math.max(...ys)];const s=Math.max(x1-x0,(y1-y0)*1.5)||1;
          const d=pts.map((p,i)=>`${i?"L":"M"}${(4+(p[0]-x0)/s*40).toFixed(1)},${(44-(p[1]-y0)/s*1.5*40).toFixed(1)}`).join("");const sp=SPORTS.find(x=>x.key===t.sport);
          return <li key={t.id}>
            <svg viewBox="0 0 48 48" className="tour-thumb" aria-hidden="true"><path d={d} fill="none" stroke="var(--accent)" strokeWidth="2" strokeLinejoin="round"/></svg>
            <div className="tour-saved-text"><strong>{t.name}</strong><small>{sp?(de?sp.de:sp.en):t.sport} · {formatKm(t.distance_m)} · ↑ {Math.round(t.ascent_m)} m · {formatDuration(t.duration_s)}{t.created_at&&<> · {new Date(t.created_at).toLocaleDateString(de?"de-DE":"en-GB")}</>}</small></div>
            <div className="tour-saved-actions">
              <button type="button" className="ghost compact" onClick={()=>showSaved(t)}>{de?"Anzeigen":"Show"}</button>
              <button type="button" className="ghost compact" onClick={()=>savedGpx(t)}>GPX</button>
              {confirmDelete===t.id?<><button type="button" className="danger compact" onClick={()=>remove(t.id)}>{de?"Wirklich löschen":"Delete"}</button><button type="button" className="ghost compact" onClick={()=>setConfirmDelete(null)}>{de?"Nein":"No"}</button></>
                :<button type="button" className="ghost compact" onClick={()=>setConfirmDelete(t.id)}>{de?"Löschen":"Delete"}</button>}
            </div>
          </li>})}</ul>:<p className="muted">{de?"Noch keine Tour gespeichert. Wähle einen Vorschlag und tippe auf „Speichern“.":"No tour saved yet. Pick a suggestion and tap “Save”."}</p>}
      </section>

      <details className="card tour-server">
        <summary>{de?"Routing-Server":"Routing server"} <span className="muted">{options.data?.server?.is_default?"brouter.de":options.data?.server?.url}</span></summary>
        <p className="muted">{de?"Die Touren berechnet BRouter – Open Source, ohne Konto und ohne Schlüssel. Standard ist der öffentliche Server brouter.de; PenguCoach schickt ihm nur die Wegpunkte der Tour. Wer es ganz im eigenen Netz möchte, betreibt BRouter selbst (z. B. als Docker-Container oder LXC) und trägt hier die Adresse ein.":"Tours are routed by BRouter – open source, no account and no key. The default is the public server brouter.de; PenguCoach only sends it the tour's waypoints. To keep everything in your own network, run BRouter yourself (e.g. as a Docker container or LXC) and enter its address here."}</p>
        {options.data?.server?.editable?<div className="tour-server-form">
          <label>{de?"Adresse (leer = brouter.de)":"Address (empty = brouter.de)"}<input value={server} onChange={e=>setServer(e.target.value)} placeholder="http://192.168.1.50:17777"/></label>
          <div className="row"><button type="button" className="ghost" onClick={testServer}>{de?"Verbindung testen":"Test connection"}</button><button type="button" onClick={saveServer}>{de?"Speichern":"Save"}</button></div>
          {serverResult&&<p className={serverResult.ok?"tour-notice":serverResult.testing?"muted":"tour-error"} role="status">{serverResult.testing?(de?"Teste …":"Testing …"):serverResult.saved?(de?"Gespeichert.":"Saved."):serverResult.ok?(de?`Antwort von ${serverResult.engine}: Teststrecke ${formatKm(serverResult.distance_m)}${serverResult.has_elevation?", mit Höhen":", ohne Höhen"}.`:`Answer from ${serverResult.engine}: test route ${formatKm(serverResult.distance_m)}${serverResult.has_elevation?", with elevation":", without elevation"}.`):errorText(serverResult.code==="BROUTER_URL_INVALID"?"BROUTER_URL_INVALID":serverResult.code,de)}</p>}
        </div>:<p className="muted">{de?"Nur Administratoren können den Server ändern.":"Only administrators can change the server."}</p>}
      </details>
    </div>

    <ExportHelp open={exportHelp} onClose={()=>setExportHelp(false)} de={de}/>
  </AppShell>;
}
