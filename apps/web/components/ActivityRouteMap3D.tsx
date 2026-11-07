"use client";
// alpha.86: 3D route map – real terrain, tilt/rotate, exaggeration, topo or street map,
// live marker synced with chart and slider, and a camera flyover along the tour.
// MapLibre GL is loaded only when 3D is switched on, so the normal page stays light.
import {useEffect,useMemo,useRef,useState} from "react";
import "maplibre-gl/dist/maplibre-gl.css";
import type * as MapLibre from "maplibre-gl";
import {routeSegments,type Metric,type Sample} from "../lib/activityExplorer";
import {along,colouredRoute,lookAhead,mainHeading,nearestOnScreen,positionAt,TILES,turnTowards} from "../lib/map3d";

type Base="topo"|"osm";
const WORKER=`/vendor/maplibre-gl-worker.mjs`;
const read=(key:string,fallback:string)=>{try{return localStorage.getItem(key)??fallback}catch{return fallback}};
const write=(key:string,value:string)=>{try{localStorage.setItem(key,value)}catch{}};

export default function ActivityRouteMap3D({data,index,colorMetric,onSelect,onHover,de,annotations=[],overlay,onUnavailable}:{data:Sample[];index:number|null;colorMetric:Metric|null;onSelect:(i:number)=>void;onHover?:(i:number|null)=>void;de:boolean;annotations?:Record<string,any>[];overlay?:React.ReactNode;onUnavailable:(reason:string)=>void}){
  const container=useRef<HTMLDivElement>(null),map=useRef<MapLibre.Map|null>(null),lib=useRef<typeof MapLibre|null>(null),marker=useRef<MapLibre.Marker|null>(null);
  const [ready,setReady]=useState(false),[tilesFailed,setTilesFailed]=useState(false);
  const [base,setBase]=useState<Base>(()=>read("pengucoach_map3d_base","topo")==="osm"?"osm":"topo");
  const [exaggeration,setExaggeration]=useState(()=>Math.max(1,Math.min(3,Number(read("pengucoach_map3d_exaggeration","1.5"))||1.5)));
  const [flying,setFlying]=useState(false),[flySpeed,setFlySpeed]=useState(60);
  const segments=useMemo(()=>routeSegments(data),[data]);
  const route=useMemo(()=>along(segments),[segments]);
  const handlers=useRef({onSelect,onHover});handlers.current={onSelect,onHover};
  const flyState=useRef<{frame:number;start:number;bearing:number;from:number}|null>(null);

  // Create the map once.
  useEffect(()=>{
    let disposed=false;
    (async()=>{
      try{
        const probe=document.createElement("canvas");
        if(!(probe.getContext("webgl2")||probe.getContext("webgl")))throw new Error("NO_WEBGL");
        const maplibre=await import("maplibre-gl");
        if(disposed||!container.current)return;
        lib.current=maplibre;
        try{maplibre.setWorkerUrl(WORKER)}catch{}
        const first=route.points[0],dark=document.documentElement.dataset.colorMode==="dark";
        const view=new maplibre.Map({
          container:container.current,attributionControl:{compact:true},maxPitch:80,pixelRatio:Math.min(2,window.devicePixelRatio||1),
          center:first?[first.lon,first.lat]:[10,50],zoom:12,pitch:55,bearing:0,
          style:{version:8,sources:{
            base:{type:"raster",tiles:[...TILES[base].tiles],tileSize:256,maxzoom:TILES[base].maxzoom,attribution:TILES[base].attribution},
            terrain:{type:"raster-dem",tiles:[...TILES.dem.tiles],tileSize:256,maxzoom:TILES.dem.maxzoom,encoding:"terrarium",attribution:TILES.dem.attribution},
            shade:{type:"raster-dem",tiles:[...TILES.dem.tiles],tileSize:256,maxzoom:TILES.dem.maxzoom,encoding:"terrarium"},
          },layers:[
            {id:"base",type:"raster",source:"base",paint:{"raster-saturation":-.15,"raster-contrast":.05,"raster-brightness-max":dark?.82:1}},
            {id:"hillshade",type:"hillshade",source:"shade",paint:{"hillshade-exaggeration":.45,"hillshade-shadow-color":"#1d2a33","hillshade-highlight-color":"#ffffff"}},
          ],terrain:{source:"terrain",exaggeration},
          sky:{"sky-color":"#7fb6e6","horizon-color":"#dcecf7","fog-color":"#e8f1f6","sky-horizon-blend":.6,"horizon-fog-blend":.6,"fog-ground-blend":.4,"atmosphere-blend":["interpolate",["linear"],["zoom"],0,1,12,.2]} as any},
        });
        map.current=view;
        view.addControl(new maplibre.NavigationControl({visualizePitch:true,showCompass:true}),"top-left");
        view.addControl(new maplibre.FullscreenControl(),"top-left");
        view.addControl(new maplibre.ScaleControl({unit:"metric"}),"bottom-left");
        let failures=0;
        view.on("error",(event:any)=>{if(String(event?.error?.message??"").match(/tile|Failed to fetch|NetworkError|404|AJAXError/i)&&++failures>3&&!disposed)setTilesFailed(true)});
        view.on("load",()=>{if(disposed)return;setReady(true);
          // Attribution stays one tap away on phones instead of covering the map.
          if((container.current?.clientWidth??800)<720)container.current?.querySelector(".maplibregl-ctrl-attrib")?.classList.remove("maplibregl-compact-show");
        });
      }catch(error){if(!disposed)onUnavailable(String((error as Error)?.message??error))}
    })();
    return()=>{disposed=true;if(flyState.current)cancelAnimationFrame(flyState.current.frame);marker.current?.remove();map.current?.remove();map.current=null;setReady(false)};
    // eslint-disable-next-line react-hooks/exhaustive-deps
  },[]);

  // Base map switch.
  useEffect(()=>{const view=map.current;if(!ready||!view)return;const source=view.getSource("base") as any;
    write("pengucoach_map3d_base",base);
    if(source?.setTiles){source.setTiles([...TILES[base].tiles])}
  },[base,ready]);

  // Terrain exaggeration.
  useEffect(()=>{const view=map.current;if(!ready||!view)return;write("pengucoach_map3d_exaggeration",String(exaggeration));view.setTerrain({source:"terrain",exaggeration})},[exaggeration,ready]);

  // Route, start/finish, climbs; hover and click along the line.
  useEffect(()=>{
    const view=map.current,maplibre=lib.current;
    if(!ready||!view||!maplibre||!route.points.length)return;
    const accent=getComputedStyle(container.current!).getPropertyValue("--accent").trim()||"#2d806b";
    const lines=colouredRoute(segments,data,colorMetric,accent);
    const set=(id:string,value:any)=>{const s=view.getSource(id) as any;if(s)s.setData(value);else view.addSource(id,{type:"geojson",data:value})};
    const notes=annotations.filter(a=>Number.isFinite(a.lon)&&Number.isFinite(a.lat)&&Math.abs(a.lat)<=90&&Math.abs(a.lon)<=180);
    set("route",lines);
    const fast=notes.filter(n=>n.kind==="speed"&&Number.isInteger(n.start_index)&&Number.isInteger(n.end_index)).map(n=>({type:"Feature",properties:{},geometry:{type:"LineString",coordinates:route.points.filter(p=>p.index>=n.start_index&&p.index<=n.end_index).map(p=>[p.lon,p.lat])}})).filter(f=>f.geometry.coordinates.length>1);
    set("fast",{type:"FeatureCollection",features:fast});
    set("marks",{type:"FeatureCollection",features:[
      {type:"Feature",properties:{kind:"start",label:de?"Start":"Start"},geometry:{type:"Point",coordinates:[route.points[0].lon,route.points[0].lat]}},
      {type:"Feature",properties:{kind:"finish",label:de?"Ziel":"Finish"},geometry:{type:"Point",coordinates:[route.points.at(-1)!.lon,route.points.at(-1)!.lat]}},
      ...notes.map((n,i)=>({type:"Feature",properties:{kind:["speed","hill","plan"].includes(n.kind)?n.kind:"note",label:String(n.label??""),note:i},geometry:{type:"Point",coordinates:[n.lon,n.lat]}})),
    ]});
    if(!view.getLayer("route-glow")){
      view.addLayer({id:"route-glow",type:"line",source:"route",layout:{"line-join":"round","line-cap":"round"},paint:{"line-color":["get","color"],"line-width":14,"line-opacity":.28,"line-blur":6}});
      view.addLayer({id:"route-casing",type:"line",source:"route",layout:{"line-join":"round","line-cap":"round"},paint:{"line-color":"#ffffff","line-width":7,"line-opacity":.9}});
      view.addLayer({id:"route-line",type:"line",source:"route",layout:{"line-join":"round","line-cap":"round"},paint:{"line-color":["get","color"],"line-width":4.5,"line-dasharray":["case",["get","gap"],["literal",[1,1.5]],["literal",[1,0]]] as any}});
      view.addLayer({id:"fast",type:"line",source:"fast",layout:{"line-join":"round","line-cap":"round"},paint:{"line-color":"#8257c9","line-width":7,"line-opacity":.75}},"route-line");
      view.addLayer({id:"marks",type:"circle",source:"marks",paint:{"circle-radius":["match",["get","kind"],"hill",5,7],"circle-color":["match",["get","kind"],"start","#2d806b","finish","#d94b4b","speed","#8257c9","hill","#bb6c22","plan","#3064b2",accent],"circle-stroke-color":"#fff","circle-stroke-width":2.5,"circle-pitch-alignment":"map"}});
    }
    const project=(lon:number,lat:number)=>view.project([lon,lat]);
    let frame=0,pointer:{x:number;y:number}|null=null,dragging=false;
    const move=(e:MapLibre.MapMouseEvent)=>{if(flyState.current)return;pointer=e.point;if(frame||dragging)return;frame=requestAnimationFrame(()=>{frame=0;if(!pointer)return;const best=nearestOnScreen(segments,project,pointer.x,pointer.y,44);handlers.current.onHover?.(best>=0?best:null);view.getCanvas().style.cursor=best>=0?"pointer":""})};
    const leave=()=>{pointer=null;if(frame)cancelAnimationFrame(frame);frame=0;if(!flyState.current)handlers.current.onHover?.(null)};
    const popup=new maplibre.Popup({closeButton:false,closeOnClick:false,offset:12,className:"map3d-popup"});
    const markEnter=(e:any)=>{const f=e.features?.[0];if(!f)return;const text=document.createElement("span");text.textContent=String(f.properties.label??"");popup.setLngLat(f.geometry.coordinates).setDOMContent(text).addTo(view)};
    const markLeave=()=>popup.remove();
    view.on("mouseenter","marks",markEnter);view.on("mouseleave","marks",markLeave);
    const click=(e:MapLibre.MapMouseEvent)=>{
      const hit=view.queryRenderedFeatures(e.point,{layers:["marks"]})[0];
      const note=hit&&hit.properties?.note!=null?notes[Number(hit.properties.note)]:null;
      if(note&&Number.isInteger(note.start_index)&&data[note.start_index]){stopFly();handlers.current.onSelect(note.start_index);return}
      const best=nearestOnScreen(segments,project,e.point.x,e.point.y,44);if(best>=0){stopFly();handlers.current.onSelect(best)}};
    const dragStart=()=>{dragging=true},dragEnd=()=>{dragging=false};
    view.on("mousemove",move);view.on("mouseout",leave);view.on("click",click);view.on("dragstart",dragStart);view.on("dragend",dragEnd);
    return()=>{popup.remove();view.off("mouseenter","marks",markEnter);view.off("mouseleave","marks",markLeave);view.off("mousemove",move);view.off("mouseout",leave);view.off("click",click);view.off("dragstart",dragStart);view.off("dragend",dragEnd);if(frame)cancelAnimationFrame(frame)};
    // eslint-disable-next-line react-hooks/exhaustive-deps
  },[ready,segments,colorMetric,annotations,de]);

  // First view: the whole tour, tilted along its main direction.
  const framed=useRef(false);
  function frameRoute(animate=true){
    const view=map.current,maplibre=lib.current;if(!view||!maplibre||!route.points.length)return;
    const bounds=new maplibre.LngLatBounds();for(const p of route.points)bounds.extend([p.lon,p.lat]);
    const bearing=mainHeading(route.points),narrow=(container.current?.clientWidth??800)<720;
    const camera=view.cameraForBounds(bounds,{padding:narrow?{top:40,bottom:30,left:30,right:30}:{top:60,bottom:90,left:60,right:60},pitch:58,bearing,maxZoom:15.5});
    if(!camera){view.fitBounds(bounds,{pitch:58,bearing,duration:0});return}
    // A tilted view leaves room at the horizon; move a little closer so the tour fills the frame.
    const target={...camera,zoom:Math.min(15.5,(camera.zoom??12)+.35),pitch:58,bearing};
    if(animate)view.flyTo({...target,duration:1400,essential:true});else view.jumpTo(target);
  }
  useEffect(()=>{if(ready&&!framed.current&&route.points.length){framed.current=true;frameRoute(false)}},[ready,route]);// eslint-disable-line react-hooks/exhaustive-deps

  // Live marker for the selected or hovered point.
  useEffect(()=>{
    const view=map.current,maplibre=lib.current;if(!ready||!view||!maplibre)return;
    if(index==null||!route.points.length){marker.current?.remove();marker.current=null;return}
    let lo=0,hi=route.points.length-1;while(lo<hi){const mid=(lo+hi)>>1;if(route.points[mid].index<index)lo=mid+1;else hi=mid}
    const p=lo>0&&index-route.points[lo-1].index<route.points[lo].index-index?route.points[lo-1]:route.points[lo];
    if(!marker.current){const el=document.createElement("div");el.className="map3d-marker";el.innerHTML="<i></i>";marker.current=new maplibre.Marker({element:el,pitchAlignment:"viewport",rotationAlignment:"viewport"}).setLngLat([p.lon,p.lat]).addTo(view)}
    else marker.current.setLngLat([p.lon,p.lat]);
  },[index,ready,route]);

  function stopFly(){if(flyState.current){cancelAnimationFrame(flyState.current.frame);flyState.current=null}setFlying(false)}
  function startFly(){
    const view=map.current;if(!view||route.total<=0)return;
    stopFly();setFlying(true);
    const seconds=flySpeed,startAt=performance.now();
    const state={frame:0,start:startAt,bearing:view.getBearing(),from:0};flyState.current=state;
    const zoom=route.total>40000?13.2:route.total>15000?13.8:14.6;let lastEmit=0;
    const step=(now:number)=>{
      if(flyState.current!==state)return;
      const progress=Math.min(1,(now-startAt)/(seconds*1000)),dist=progress*route.total;
      const here=positionAt(route,dist);if(!here){stopFly();return}
      state.bearing=turnTowards(state.bearing,lookAhead(route,dist,Math.max(250,route.total/40)),2.2);
      view.jumpTo({center:[here.lon,here.lat],bearing:state.bearing,pitch:62,zoom});
      // The camera moves every frame; chart and readouts follow ~8× per second so the page stays fluid.
      if(now-lastEmit>120||progress>=1){lastEmit=now;handlers.current.onHover?.(here.index)}
      marker.current?.setLngLat([here.lon,here.lat]);
      if(progress>=1){handlers.current.onHover?.(null);handlers.current.onSelect(here.index);stopFly();return}
      state.frame=requestAnimationFrame(step);
    };
    view.easeTo({center:[route.points[0].lon,route.points[0].lat],zoom,pitch:62,bearing:lookAhead(route,0,400),duration:1100});
    window.setTimeout(()=>{if(flyState.current===state){state.bearing=view.getBearing();state.frame=requestAnimationFrame(step)}},1150);
  }
  // Interacting with the map stops the flyover; leaving the page cancels it.
  useEffect(()=>{const view=map.current;if(!ready||!view)return;const stop=(e:any)=>{if(e?.originalEvent)stopFly()};view.on("dragstart",stop);view.on("wheel",stop);view.on("touchstart",stop);return()=>{view.off("dragstart",stop);view.off("wheel",stop);view.off("touchstart",stop)}},[ready]);// eslint-disable-line react-hooks/exhaustive-deps

  return <div className="activity-map-shell map3d-shell">
    <div ref={container} className="activity-route-map map3d" role="region" aria-label={de?"3D-Karte der Strecke. Ziehen verschiebt, rechte Maustaste oder zwei Finger drehen und neigen.":"3D route map. Drag to pan, right mouse button or two fingers to rotate and tilt."}/>
    {overlay}
    <div className="map3d-tools" role="group" aria-label={de?"3D-Ansicht":"3D view"}>
      <div className="map3d-seg" role="radiogroup" aria-label={de?"Kartenart":"Map style"}>
        {(["topo","osm"] as Base[]).map(b=><button key={b} type="button" role="radio" aria-checked={base===b} className={base===b?"active":""} onClick={()=>setBase(b)}>{b==="topo"?(de?"Gelände":"Terrain"):(de?"Straßen":"Streets")}</button>)}
      </div>
      <label className="map3d-range" title={de?"Überhöhung der Berge":"Terrain exaggeration"}><span>{de?"Höhe":"Relief"} {exaggeration.toFixed(1)}×</span><input type="range" min="1" max="3" step="0.1" value={exaggeration} onChange={e=>setExaggeration(Number(e.target.value))} aria-label={de?"Überhöhung":"Exaggeration"}/></label>
      <div className="map3d-fly">
        <button type="button" className={flying?"active":""} onClick={()=>flying?stopFly():startFly()} disabled={!ready||route.total<=0}>{flying?(de?"■ Stopp":"■ Stop"):(de?"▶ Flyover":"▶ Flyover")}</button>
        <select value={flySpeed} onChange={e=>setFlySpeed(Number(e.target.value))} aria-label={de?"Dauer des Flyovers":"Flyover duration"}>{[30,60,120,240].map(s=><option key={s} value={s}>{s<60?`${s} s`:`${s/60} min`}</option>)}</select>
      </div>
      <button type="button" className="map3d-reset" onClick={()=>{stopFly();frameRoute()}} disabled={!ready}>{de?"Ganze Tour":"Whole tour"}</button>
    </div>
    {!ready&&<div className="map3d-loading" aria-live="polite">{de?"3D-Gelände wird geladen …":"Loading 3D terrain …"}</div>}
    {tilesFailed&&<p className="map-status" role="status">{de?"Gelände- oder Kartenkacheln konnten nicht vollständig geladen werden (Internet nötig). Die Strecke bleibt sichtbar.":"Some terrain or map tiles could not load (internet required). The route stays visible."}</p>}
  </div>;
}
