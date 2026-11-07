"use client";
// alpha.87: planning map – click to set start/destination, draggable markers, the
// suggested variants (the chosen one on top) and a marker that follows the profile.
import {useEffect,useRef,useState} from "react";
import type * as Leaflet from "leaflet";
import {VARIANT_COLORS,type Variant} from "../lib/tours";

export type LatLon={lat:number;lon:number};

export default function TourMap({start,end,mode,variants,selected,hover,pick,onPick,onSelect,de,saved}:{start:LatLon|null;end:LatLon|null;mode:"round"|"a_to_b";
  variants:Variant[];selected:string|null;hover:number|null;pick:"start"|"end"|null;onPick:(which:"start"|"end",p:LatLon)=>void;onSelect:(id:string)=>void;de:boolean;saved?:Variant|null}){
  const box=useRef<HTMLDivElement>(null),map=useRef<Leaflet.Map|null>(null),lib=useRef<typeof Leaflet|null>(null);
  const lines=useRef<Leaflet.LayerGroup|null>(null),pins=useRef<{start?:Leaflet.Marker;end?:Leaflet.Marker}>({}),dot=useRef<Leaflet.CircleMarker|null>(null);
  const [ready,setReady]=useState(false),[tileError,setTileError]=useState(false);
  const handlers=useRef({onPick,onSelect,pick,mode});handlers.current={onPick,onSelect,pick,mode};

  useEffect(()=>{
    let disposed=false,observer:ResizeObserver|null=null;
    import("leaflet").then(L=>{
      if(disposed||!box.current)return;
      lib.current=L;
      const view=L.map(box.current,{zoomControl:true,maxZoom:19,preferCanvas:false}).setView(start?[start.lat,start.lon]:[51.1,10.4],start?12:6);
      map.current=view;
      L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png",{maxZoom:19,attribution:'&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a> · Routing <a href="https://brouter.de" target="_blank" rel="noopener">BRouter</a>',referrerPolicy:"strict-origin-when-cross-origin"})
        .on("tileerror",()=>{if(!disposed)setTileError(true)}).addTo(view);
      lines.current=L.layerGroup().addTo(view);
      view.on("click",(e:Leaflet.LeafletMouseEvent)=>{
        const h=handlers.current;
        // Without an explicit choice the first click sets the start, the next the destination (A→B).
        const which=h.pick??(h.mode==="a_to_b"&&pins.current.start?"end":"start");
        h.onPick(which,{lat:e.latlng.lat,lon:e.latlng.lng});
      });
      observer=new ResizeObserver(()=>view.invalidateSize());observer.observe(box.current);
      setReady(true);
    });
    return()=>{disposed=true;observer?.disconnect();map.current?.remove();map.current=null;pins.current={};dot.current=null};
    // eslint-disable-next-line react-hooks/exhaustive-deps
  },[]);

  // Start and destination pins.
  useEffect(()=>{
    const L=lib.current,view=map.current;if(!ready||!L||!view)return;
    const place=(key:"start"|"end",p:LatLon|null,label:string,cls:string)=>{
      const current=pins.current[key];
      if(!p){current?.remove();delete pins.current[key];return}
      const icon=L.divIcon({className:`tour-pin ${cls}`,html:`<span><b>${label}</b></span>`,iconSize:[30,30],iconAnchor:[15,30]});
      if(current){current.setLatLng([p.lat,p.lon]);current.setIcon(icon);return}
      const m=L.marker([p.lat,p.lon],{icon,draggable:true,keyboard:true,title:key==="start"?(de?"Start – ziehen zum Verschieben":"Start – drag to move"):(de?"Ziel – ziehen zum Verschieben":"Destination – drag to move")}).addTo(view);
      m.on("dragend",()=>{const ll=m.getLatLng();handlers.current.onPick(key,{lat:ll.lat,lon:ll.lng})});
      pins.current[key]=m;
    };
    place("start",start,mode==="round"?"⟳":"A","start");
    place("end",mode==="a_to_b"?end:null,"B","end");
    if(start&&!variants.length&&!saved)view.setView([start.lat,start.lon],Math.max(view.getZoom(),12),{animate:true});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  },[ready,start?.lat,start?.lon,end?.lat,end?.lon,mode,de]);

  // Variants: others thin underneath, the chosen one thick on top.
  const shown=saved?[saved]:variants;
  const key=shown.map(v=>v.id+v.coordinates.length).join("|");
  useEffect(()=>{
    const L=lib.current,view=map.current,group=lines.current;if(!ready||!L||!view||!group)return;
    group.clearLayers();
    const order=[...shown].sort((a,b)=>(a.id===selected?1:0)-(b.id===selected?1:0));
    for(const v of order){
      const i=Math.max(0,variants.findIndex(x=>x.id===v.id)),color=VARIANT_COLORS[i%VARIANT_COLORS.length],active=saved||v.id===selected;
      const path=v.coordinates.map(c=>[c[1],c[0]] as [number,number]);
      if(active)L.polyline(path,{color:"#fff",weight:9,opacity:.95,interactive:false}).addTo(group);
      const line=L.polyline(path,{color,weight:active?5:4,opacity:active?1:.55,dashArray:active?undefined:"6 7"}).addTo(group);
      line.on("click",(e:Leaflet.LeafletMouseEvent)=>{L.DomEvent.stopPropagation(e);handlers.current.onSelect(v.id)});
      line.bindTooltip(`${de?"Variante":"Variant"} ${i+1}`,{sticky:true});
    }
    if(shown.length){
      const all=shown.flatMap(v=>v.coordinates.map(c=>[c[1],c[0]] as [number,number]));
      view.fitBounds(L.latLngBounds(all),{padding:[30,30],maxZoom:15});
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  },[ready,key,selected]);

  // Marker following the elevation profile.
  useEffect(()=>{
    const L=lib.current,view=map.current;if(!ready||!L||!view)return;
    const v=saved??variants.find(x=>x.id===selected);
    const c=hover!=null&&v?v.coordinates[Math.max(0,Math.min(v.coordinates.length-1,hover))]:null;
    if(!c){dot.current?.remove();dot.current=null;return}
    if(!dot.current)dot.current=L.circleMarker([c[1],c[0]],{radius:7,color:"#fff",weight:3,fillColor:"#17201d",fillOpacity:1,interactive:false}).addTo(view);
    else dot.current.setLatLng([c[1],c[0]]);
  },[ready,hover,selected,variants,saved]);

  return <div className={`tour-map-shell ${pick?"picking":""}`}>
    <div ref={box} className="tour-map" role="application" aria-label={de?"Karte: Klick setzt Start oder Ziel":"Map: click sets start or destination"}/>
    {pick&&<div className="tour-map-hint" role="status">{pick==="start"?(de?"Tippe auf die Karte, um den Start zu setzen":"Tap the map to set the start"):(de?"Tippe auf die Karte, um das Ziel zu setzen":"Tap the map to set the destination")}</div>}
    {tileError&&<p className="map-status" role="status">{de?"Kartenkacheln konnten nicht geladen werden (Internet nötig).":"Map tiles could not be loaded (internet required)."}</p>}
  </div>;
}
