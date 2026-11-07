"use client";
// alpha.87: planning map – click to set start/destination, draggable markers, the
// suggested variants (the chosen one on top) and a marker that follows the profile.
// alpha.89: a click near a line picks that variant; numbered labels on the map;
// edit mode with draggable waypoints, drag-the-line to add a point, tap to remove.
import {useEffect,useRef,useState} from "react";
import type * as Leaflet from "leaflet";
import {nearestIndex,segmentOf,VARIANT_COLORS,type EditRoute,type Variant,type Waypoint} from "../lib/tours";

export type LatLon={lat:number;lon:number};
export type Editor={route:EditRoute|null;waypoints:Waypoint[];busy:boolean;loop:boolean;fresh?:boolean;
  onMove:(i:number,p:Waypoint)=>void;onInsert:(segment:number,p:Waypoint)=>void;onRemove:(i:number)=>void};

export default function TourMap({start,end,mode,variants,selected,hover,pick,onPick,onSelect,de,saved,editor}:{start:LatLon|null;end:LatLon|null;mode:"round"|"a_to_b";
  variants:Variant[];selected:string|null;hover:number|null;pick:"start"|"end"|null;onPick:(which:"start"|"end",p:LatLon)=>void;onSelect:(id:string)=>void;de:boolean;saved?:Variant|null;editor?:Editor|null}){
  const box=useRef<HTMLDivElement>(null),map=useRef<Leaflet.Map|null>(null),lib=useRef<typeof Leaflet|null>(null);
  const lines=useRef<Leaflet.LayerGroup|null>(null),edits=useRef<Leaflet.LayerGroup|null>(null),pins=useRef<{start?:Leaflet.Marker;end?:Leaflet.Marker}>({}),dot=useRef<Leaflet.CircleMarker|null>(null);
  const [ready,setReady]=useState(false),[tileError,setTileError]=useState(false);
  const shown=saved?[saved]:variants;
  const state=useRef({onPick,onSelect,pick,mode,shown,editor});state.current={onPick,onSelect,pick,mode,shown,editor};

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
      edits.current=L.layerGroup().addTo(view);
      view.on("click",(e:Leaflet.LeafletMouseEvent)=>{
        const h=state.current,p:Waypoint=[e.latlng.lat,e.latlng.lng];
        // Edit mode: a tap anywhere pulls the nearest piece of the route through that spot.
        if(h.editor?.route&&!h.editor.busy){const i=nearestIndex(h.editor.route.coordinates,p[0],p[1]);h.editor.onInsert(segmentOf(h.editor.route.segments,i),p);return}
        if(h.editor)return;
        // With suggestions on the map a click picks the nearest one; the start only moves on purpose.
        if(h.shown.length&&!h.pick){
          const target=view.latLngToContainerPoint(e.latlng);let best:string|null=null,d=48*48;
          for(const v of h.shown){const step=Math.max(1,Math.floor(v.coordinates.length/1500));for(let i=0;i<v.coordinates.length;i+=step){const c=v.coordinates[i];const q=view.latLngToContainerPoint([c[1],c[0]]);const e2=(q.x-target.x)**2+(q.y-target.y)**2;if(e2<d){d=e2;best=v.id}}}
          if(best)h.onSelect(best);
          return;
        }
        // Without an explicit choice the first click sets the start, the next the destination (A→B).
        const which=h.pick??(h.mode==="a_to_b"&&pins.current.start?"end":"start");
        h.onPick(which,{lat:p[0],lon:p[1]});
      });
      observer=new ResizeObserver(()=>view.invalidateSize());observer.observe(box.current);
      setReady(true);
    });
    return()=>{disposed=true;observer?.disconnect();map.current?.remove();map.current=null;pins.current={};dot.current=null};
    // eslint-disable-next-line react-hooks/exhaustive-deps
  },[]);

  // Start and destination pins (hidden while editing – the editor has its own points).
  useEffect(()=>{
    const L=lib.current,view=map.current;if(!ready||!L||!view)return;
    const place=(key:"start"|"end",p:LatLon|null,label:string,cls:string)=>{
      const current=pins.current[key];
      if(!p||editor){current?.remove();delete pins.current[key];return}
      const icon=L.divIcon({className:`tour-pin ${cls}`,html:`<span><b>${label}</b></span>`,iconSize:[30,30],iconAnchor:[15,30]});
      if(current){current.setLatLng([p.lat,p.lon]);current.setIcon(icon);return}
      const m=L.marker([p.lat,p.lon],{icon,draggable:true,keyboard:true,zIndexOffset:500,title:key==="start"?(de?"Start – ziehen zum Verschieben":"Start – drag to move"):(de?"Ziel – ziehen zum Verschieben":"Destination – drag to move")}).addTo(view);
      m.on("dragend",()=>{const ll=m.getLatLng();state.current.onPick(key,{lat:ll.lat,lon:ll.lng})});
      pins.current[key]=m;
    };
    place("start",start,mode==="round"?"⟳":"A","start");
    place("end",mode==="a_to_b"?end:null,"B","end");
    if(start&&!variants.length&&!saved)view.setView([start.lat,start.lon],Math.max(view.getZoom(),12),{animate:true});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  },[ready,start?.lat,start?.lon,end?.lat,end?.lon,mode,de,!!editor]);

  // Variants: others thin underneath, the chosen one thick on top, each with its number.
  const key=shown.map(v=>v.id+v.coordinates.length).join("|");
  useEffect(()=>{
    const L=lib.current,view=map.current,group=lines.current;if(!ready||!L||!view||!group)return;
    group.clearLayers();
    if(editor)return;
    const order=[...shown].sort((a,b)=>(a.id===selected?1:0)-(b.id===selected?1:0));
    for(const v of order){
      const i=Math.max(0,variants.findIndex(x=>x.id===v.id)),color=VARIANT_COLORS[i%VARIANT_COLORS.length],active=saved||v.id===selected;
      const path=v.coordinates.map(c=>[c[1],c[0]] as [number,number]);
      if(active)L.polyline(path,{color:"#fff",weight:9,opacity:.95,interactive:false}).addTo(group);
      L.polyline(path,{color,weight:active?5:4,opacity:active?1:.6,dashArray:active?undefined:"6 7",interactive:false}).addTo(group);
      if(!saved&&path.length>4){
        const at=path[Math.floor(path.length*(0.3+0.12*i))];
        L.marker(at,{interactive:false,icon:L.divIcon({className:`tour-variant-label ${active?"active":""}`,html:`<span style="background:${color}">${i+1}</span>`,iconSize:[26,26],iconAnchor:[13,13]})}).addTo(group);
      }
    }
    if(shown.length){
      const all=shown.flatMap(v=>v.coordinates.map(c=>[c[1],c[0]] as [number,number]));
      view.fitBounds(L.latLngBounds(all),{padding:[30,30],maxZoom:15});
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  },[ready,key,selected,!!editor]);

  // Editor: the route being edited, its waypoints and dead-end warnings.
  const routeKey=editor?.route?`${editor.route.coordinates.length}:${editor.route.distance_m}:${editor.waypoints.map(w=>w.join(",")).join("|")}`:"";
  useEffect(()=>{
    const L=lib.current,view=map.current,group=edits.current;if(!ready||!L||!view||!group)return;
    group.clearLayers();
    if(!editor?.route)return;
    const route=editor.route,path=route.coordinates.map(c=>[c[1],c[0]] as [number,number]);
    L.polyline(path,{color:"#fff",weight:10,opacity:.95,interactive:false}).addTo(group);
    L.polyline(path,{color:VARIANT_COLORS[0],weight:5,opacity:1,interactive:false,className:"tour-edit-line"}).addTo(group);
    // Wide invisible line: press and drag pulls a new point out of the route; a tap adds one there.
    const hit=L.polyline(path,{color:"#000",weight:26,opacity:0,className:"tour-edit-hit"}).addTo(group);
    let ghost:Leaflet.Marker|null=null,dragging=false,segment=0;
    const icon=(cls:string,label="")=>L.divIcon({className:`tour-wp ${cls}`,html:`<span>${label}</span>`,iconSize:[22,22],iconAnchor:[11,11]});
    let pulled=false;
    hit.on("mousedown",(e:Leaflet.LeafletMouseEvent)=>{
      const original=e.originalEvent as PointerEvent|MouseEvent;
      // Fingers pan the map; on touch screens a tap on the line adds a point instead.
      if(editor.busy||("pointerType" in original&&original.pointerType==="touch")||(typeof TouchEvent!=="undefined"&&original instanceof TouchEvent))return;
      L.DomEvent.stopPropagation(e);L.DomEvent.preventDefault(original);
      const i=nearestIndex(route.coordinates,e.latlng.lat,e.latlng.lng);segment=segmentOf(route.segments,i);
      const from=view.latLngToContainerPoint(e.latlng);
      view.dragging.disable();dragging=true;pulled=false;
      const move=(m:Leaflet.LeafletMouseEvent)=>{
        if(!ghost&&view.latLngToContainerPoint(m.latlng).distanceTo(from)>6)ghost=L.marker(m.latlng,{icon:icon("ghost"),interactive:false}).addTo(group);
        ghost?.setLatLng(m.latlng);
      };
      const up=(m:Leaflet.LeafletMouseEvent)=>{
        view.off("mousemove",move);view.off("mouseup",up);view.dragging.enable();dragging=false;
        if(ghost){ghost.remove();ghost=null;pulled=true;state.current.editor?.onInsert(segment,[m.latlng.lat,m.latlng.lng])}
      };
      view.on("mousemove",move);view.on("mouseup",up);
    });
    hit.on("click",(e:Leaflet.LeafletMouseEvent)=>{L.DomEvent.stopPropagation(e);if(pulled){pulled=false;return}if(editor.busy)return;const i=nearestIndex(route.coordinates,e.latlng.lat,e.latlng.lng);state.current.editor?.onInsert(segmentOf(route.segments,i),[e.latlng.lat,e.latlng.lng])});
    const last=editor.waypoints.length-1;
    editor.waypoints.forEach((w,i)=>{
      if(editor.loop&&i===last)return;
      const endPoint=i===0||i===last,spur=route.spurs?.some(s=>s.index===i);
      const m=L.marker([w[0],w[1]],{draggable:!editor.busy,zIndexOffset:endPoint?800:600,keyboard:true,
        icon:icon(`${i===0?"start":i===last?"end":"via"} ${spur?"spur":""}`,i===0?(editor.loop?"⟳":"A"):i===last?"B":""),
        title:endPoint?(de?"Ziehen zum Verschieben":"Drag to move"):(de?"Ziehen zum Verschieben, antippen zum Entfernen":"Drag to move, tap to remove")}).addTo(group);
      m.on("dragend",()=>{const ll=m.getLatLng();state.current.editor?.onMove(i,[ll.lat,ll.lng])});
      if(!endPoint)m.on("click",(e:Leaflet.LeafletMouseEvent)=>{L.DomEvent.stopPropagation(e);state.current.editor?.onRemove(i)});
      if(spur)m.bindTooltip(de?"Stichweg: hin und auf demselben Weg zurück":"Dead end: there and back on the same way",{direction:"top",offset:[0,-10]});
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  },[ready,routeKey,editor?.busy]);

  // Marker following the elevation profile.
  const active=editor?.route??saved??variants.find(x=>x.id===selected);
  useEffect(()=>{
    const L=lib.current,view=map.current;if(!ready||!L||!view)return;
    const c=hover!=null&&active?active.coordinates[Math.max(0,Math.min(active.coordinates.length-1,hover))]:null;
    if(!c){dot.current?.remove();dot.current=null;return}
    if(!dot.current)dot.current=L.circleMarker([c[1],c[0]],{radius:7,color:"#fff",weight:3,fillColor:"#17201d",fillOpacity:1,interactive:false}).addTo(view);
    else dot.current.setLatLng([c[1],c[0]]);
  },[ready,hover,active]);

  return <div className={`tour-map-shell ${pick?"picking":""} ${editor?"editing":""}`}>
    <div ref={box} className="tour-map" role="application" aria-label={editor?(de?"Bearbeiten: Linie ziehen fügt einen Punkt hinzu, Punkte verschieben, antippen entfernt":"Editing: drag the line to add a point, move points, tap to remove"):(de?"Karte: Klick setzt Start oder Ziel bzw. wählt eine Variante":"Map: click sets start or destination, or picks a variant")}/>
    {pick&&!editor&&<div className="tour-map-hint" role="status">{pick==="start"?(de?"Tippe auf die Karte, um den Start zu setzen":"Tap the map to set the start"):(de?"Tippe auf die Karte, um das Ziel zu setzen":"Tap the map to set the destination")}</div>}
    {editor&&(editor.fresh||editor.busy)&&<div className="tour-map-hint edit" role="status">{editor.busy?(de?"Route wird angepasst …":"Updating route …"):(de?"Linie ziehen = neuer Punkt · Punkt antippen = entfernen · Karte antippen = Route dorthin":"Drag line = new point · tap point = remove · tap map = route there")}</div>}
    {tileError&&<p className="map-status" role="status">{de?"Kartenkacheln konnten nicht geladen werden (Internet nötig).":"Map tiles could not be loaded (internet required)."}</p>}
  </div>;
}
