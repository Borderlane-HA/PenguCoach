"use client";

import {useEffect,useMemo,useRef,useState} from "react";
import type * as Leaflet from "leaflet";
import {extent,finite,Metric,routeSegments,Sample} from "../lib/activityExplorer";

const COLORS=["#3064b2","#327fc2","#369ccc","#42aec0","#60b79c","#9db974","#cfba5b","#e8ac49","#ed8a3e","#e15f37","#c9443d"];

export default function ActivityRouteMap({data,index,colorMetric,onSelect,de,annotations=[]}:{data:Sample[];index:number|null;colorMetric:Metric|null;onSelect:(i:number)=>void;de:boolean;annotations?:Record<string,any>[]}) {
  const container=useRef<HTMLDivElement>(null), map=useRef<Leaflet.Map|null>(null), library=useRef<typeof Leaflet|null>(null);
  const layers=useRef<Leaflet.LayerGroup|null>(null), marker=useRef<Leaflet.CircleMarker|null>(null);
  const handler=useRef(onSelect); handler.current=onSelect;
  const [ready,setReady]=useState(false),[error,setError]=useState(false);
  const segments=useMemo(()=>routeSegments(data),[data]);
  const points=useMemo(()=>segments.flat(),[segments]);

  useEffect(()=>{
    let disposed=false;
    import("leaflet").then(L=>{
      if(disposed||!container.current)return;
      library.current=L;
      const view=L.map(container.current,{scrollWheelZoom:false,preferCanvas:true,zoomControl:true,maxZoom:19});
      map.current=view;
      L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png",{
        maxZoom:19,attribution:'&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a> contributors',
        referrerPolicy:"strict-origin-when-cross-origin",
      }).on("tileerror",()=>{if(!disposed)setError(true)}).addTo(view);
      layers.current=L.layerGroup().addTo(view);
      setReady(true);
    }).catch(()=>{if(!disposed)setError(true)});
    return()=>{disposed=true;map.current?.remove();map.current=null;layers.current=null;marker.current=null;};
  },[]);

  useEffect(()=>{
    const L=library.current, view=map.current, group=layers.current;
    if(!ready||!L||!view||!group||!points.length)return;
    group.clearLayers(); marker.current?.remove(); marker.current=null;
    const nearest=(event:Leaflet.LeafletMouseEvent)=>{
      let best=-1, distance=32*32;
      for(const point of points){
        const pixel=view.latLngToContainerPoint([point.lat,point.lon]);
        const d=(pixel.x-event.containerPoint.x)**2+(pixel.y-event.containerPoint.y)**2;
        if(d<distance){best=point.index;distance=d;}
      }
      if(best>=0)handler.current(best);
    };
    const accent=getComputedStyle(container.current!).getPropertyValue("--accent").trim()||"#2d806b";
    const [lo,hi]=colorMetric?extent(data,colorMetric.key):[0,1];
    const buckets:Leaflet.LatLngTuple[][][]=Array.from({length:COLORS.length+1},()=>[]);
    const addLine=(coordinates:Leaflet.LatLngTuple[]|Leaflet.LatLngTuple[][], color:string,dashed=false)=>{
      L.polyline(coordinates,{color,weight:5,opacity:.9,dashArray:dashed?"5 6":undefined}).on("mousemove click",event=>nearest(event as Leaflet.LeafletMouseEvent)).addTo(group);
    };
    for(const segment of segments){
      if(!colorMetric){addLine(segment.map(p=>[p.lat,p.lon]),accent);continue;}
      for(let i=1;i<segment.length;i++){
        const a=segment[i-1], b=segment[i], first=finite(a.sample[colorMetric.key]), second=finite(b.sample[colorMetric.key]);
        const value=first!=null&&second!=null?(first+second)/2:null;
        const band=value==null?COLORS.length:Math.max(0,Math.min(COLORS.length-1,Math.floor((value-lo)/(hi-lo)*COLORS.length)));
        buckets[band].push([[a.lat,a.lon],[b.lat,b.lon]]);
      }
    }
    if(colorMetric)buckets.forEach((coordinates,i)=>{if(coordinates.length)addLine(coordinates,COLORS[i]??"#919b99",i===COLORS.length)});
    const first=points[0], last=points.at(-1)!;
    L.circleMarker([first.lat,first.lon],{radius:5,color:"#fff",weight:2,fillColor:"#2d806b",fillOpacity:1}).bindTooltip(de?"Start":"Start").addTo(group);
    L.circleMarker([last.lat,last.lon],{radius:5,color:"#fff",weight:2,fillColor:"#d94b4b",fillOpacity:1}).bindTooltip(de?"Ziel":"Finish").addTo(group);
    for(const point of annotations){
      const lat=finite(point.lat),lon=finite(point.lon);if(lat==null||lon==null||Math.abs(lat)>90||Math.abs(lon)>180)continue;
      if(point.kind==="speed"&&Number.isInteger(point.start_index)&&Number.isInteger(point.end_index)){
        const route=data.slice(point.start_index,point.end_index+1).map(r=>[finite(r.position_lat),finite(r.position_long)]).filter(p=>p[0]!=null&&p[1]!=null&&Math.abs(p[0]!)<=90&&Math.abs(p[1]!)<=180) as [number,number][];
        if(route.length>1)L.polyline(route,{color:"#8257c9",weight:6,opacity:.8,interactive:false}).addTo(group);
      }
      const text=document.createElement("span");text.textContent=point.label;
      L.circleMarker([lat,lon],{radius:6,bubblingMouseEvents:false,color:"#fff",weight:2,fillColor:point.kind==="speed"?"#8257c9":point.kind==="hill"?"#bb6c22":point.kind==="plan"?"#3064b2":accent,fillOpacity:1}).bindTooltip(text).on("click",()=>{
        if(Number.isInteger(point.start_index)&&data[point.start_index]){handler.current(point.start_index);return}
        let index=0,distance=Infinity;data.forEach((r,i)=>{const a=finite(r.position_lat),b=finite(r.position_long);if(a==null||b==null)return;const d=(a-lat)**2+(b-lon)**2;if(d<distance){distance=d;index=i}});handler.current(index);
      }).addTo(group);
    }
    view.on("click",nearest);
    view.fitBounds(L.latLngBounds(points.map(p=>[p.lat,p.lon])),{padding:[25,25],maxZoom:16,animate:false});
    const observer=new ResizeObserver(()=>view.invalidateSize());
    if(container.current)observer.observe(container.current);
    return()=>{view.off("click",nearest);observer.disconnect();};
  },[ready,segments,points,colorMetric,data,de,annotations]);

  useEffect(()=>{
    const L=library.current, view=map.current;
    if(!ready||!L||!view)return;
    const point=points.find(p=>p.index===index);
    if(!point){marker.current?.remove();marker.current=null;return;}
    if(!marker.current)marker.current=L.circleMarker([point.lat,point.lon],{radius:8,color:"#fff",weight:3,fillColor:"#172c42",fillOpacity:1,interactive:false}).addTo(view);
    else marker.current.setLatLng([point.lat,point.lon]);
    marker.current.bringToFront();
  },[ready,points,index,colorMetric,de,annotations]);

  return <div className="activity-map-shell">
    <div ref={container} className="activity-route-map" role="region" aria-label={de?"Karte der aufgezeichneten Strecke":"Recorded route map"}/>
    {!ready&&!error&&<div className="map-state">{de?"Karte wird geladen…":"Loading map…"}</div>}
    {error&&<p className="map-status" role="status">{de?"Kartenkacheln konnten nicht vollständig geladen werden. Die aufgezeichnete Strecke bleibt verfügbar, sobald die Kartenansicht bereit ist.":"Some map tiles could not load. The recorded route remains available once the map view is ready."}</p>}
    {colorMetric&&<div className="route-legend"><span>{de?"Niedrig":"Low"}</span><i style={{background:`linear-gradient(90deg,${COLORS.join(",")})`}}/><span>{de?"Hoch":"High"}</span><small>{de?"Grau gestrichelt: Messwert fehlt":"Gray dashes: missing measurement"}</small></div>}
  </div>;
}
