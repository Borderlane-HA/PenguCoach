"use client";
import ClientLink from "next/link";


import {useEffect,useMemo,useRef,useState} from "react";
import {api} from "../lib/api";
import {bearing,MapSettings,RoutePoint} from "../lib/activityExplorer";

type Provider="google"|"apple";

export default function ActivityPanorama({settings,point,points,de,onGoogleActive}:{settings:MapSettings|null;point:RoutePoint|null;points:RoutePoint[];de:boolean;onGoogleActive:(active:boolean)=>void}) {
  const [provider,setProvider]=useState<Provider>(settings?.preferred_provider??"google");
  const [open,setOpen]=useState(false),[credential,setCredential]=useState<string|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState("");
  const [target,setTarget]=useState<RoutePoint|null>(null),[follow,setFollow]=useState(true);
  const [appleStatus,setAppleStatus]=useState("loading");
  const frame=useRef<HTMLIFrameElement>(null), cancelled=useRef(0);
  const configured=provider==="google"?settings?.google_configured:settings?.apple_configured;
  const heading=target?bearing(points,target.index):0;

  useEffect(()=>{if(settings&&!open)setProvider(settings.preferred_provider)},[settings,open]);
  useEffect(()=>{onGoogleActive(open&&credential!=null&&provider==="google");return()=>onGoogleActive(false)},[open,credential,provider,onGoogleActive]);
  useEffect(()=>{
    if(!open||!credential||!follow)return;
    const timer=setTimeout(()=>setTarget(point),650);
    return()=>clearTimeout(timer);
  },[open,credential,follow,point]);
  useEffect(()=>()=>{cancelled.current++},[]);

  const googleUrl=useMemo(()=>{
    if(provider!=="google"||!credential||!target)return undefined;
    const query=new URLSearchParams({key:credential,location:`${target.lat},${target.lon}`,heading:heading.toFixed(0),radius:"50",source:"outdoor",language:de?"de":"en"});
    return `https://www.google.com/maps/embed/v1/streetview?${query}`;
  },[credential,target,heading,de,provider]);

  const sendApple=()=>{
    if(provider!=="apple"||!credential||!target)return;
    frame.current?.contentWindow?.postMessage({type:"pengucoach-look-around",token:credential,latitude:target.lat,longitude:target.lon},location.origin);
  };
  useEffect(()=>{if(provider==="apple"&&credential&&target){setAppleStatus("loading");sendApple()}},[provider,credential,target]);
  useEffect(()=>{
    const receive=(event:MessageEvent)=>{
      if(event.origin!==location.origin||event.source!==frame.current?.contentWindow)return;
      if(event.data?.type==="pengucoach-look-around-ready")sendApple();
      if(event.data?.type==="pengucoach-look-around-status")setAppleStatus(String(event.data.status));
    };
    window.addEventListener("message",receive);return()=>window.removeEventListener("message",receive);
  },[provider,credential,target]);

  function close(){cancelled.current++;setOpen(false);setCredential(null);setTarget(null);setBusy(false);setError("");}
  async function confirm(){
    if(!point||!configured||busy)return;
    const attempt=++cancelled.current; setBusy(true);setError("");
    try{
      const result=await api<{credential:string}>("/settings/maps/panorama-access",{method:"POST",cache:"no-store",body:JSON.stringify({provider,confirmed:true})});
      if(attempt!==cancelled.current)return;
      setTarget(point);setCredential(result.credential);
    }catch {if(attempt===cancelled.current)setError(de?"Zugang konnte nicht geladen werden. Bitte die persönlichen Karten-Einstellungen prüfen.":"Could not load access. Check your personal map settings.");}
    finally{if(attempt===cancelled.current)setBusy(false);}
  }

  return <section className="activity-panorama">
    <div className="between"><div><strong>{de?"Straßenansicht":"Street-level view"}</strong><small className="panorama-subtitle">{de?"Die Umgebung zur ausgewählten Trainingsstelle ansehen":"See the surroundings of the selected training point"}</small></div>
      {!open&&<button type="button" className="ghost compact" disabled={!point||!settings} onClick={()=>{setError("");setOpen(true)}}>{de?"Straßenansicht öffnen":"Open street-level view"}</button>}
      {open&&<button type="button" className="ghost compact" onClick={close}>{de?"Schließen":"Close"}</button>}
    </div>
    {open&&!credential&&<div className="panorama-consent">
      <label>{de?"Anbieter":"Provider"}<select value={provider} disabled={busy} onChange={e=>{setProvider(e.target.value as Provider);setError("")}}><option value="google">Google Street View</option><option value="apple">Apple Look Around</option></select></label>
      <p>{de?"Erst nach deiner Bestätigung wird eine Verbindung zum gewählten Anbieter aufgebaut. Dabei erhält er die ausgewählten Koordinaten sowie übliche Verbindungsdaten. Puls, Watt und andere Messwerte werden nicht übertragen.":"Only after your confirmation will a connection to the selected provider be made. It receives the selected coordinates and normal connection data. Heart rate, power and other measurements are not sent."}</p>
      {!configured&&<p className="status-warn">{de?"Für diesen Anbieter ist noch kein persönlicher Zugang hinterlegt.":"You have not configured personal access for this provider."} <ClientLink prefetch={false} className="text-link" href="/settings/maps">{de?"Karten-Einstellungen":"Map settings"}</ClientLink></p>}
      <div className="row"><button type="button" onClick={confirm} disabled={!configured||!point||busy}>{busy?(de?"Wird geöffnet…":"Opening…"):(de?"Bestätigen und laden":"Confirm and load")}</button><button type="button" className="ghost" onClick={close}>{de?"Abbrechen":"Cancel"}</button></div>
    </div>}
    {error&&<p role="alert" className="status-bad">{error}</p>}
    {open&&credential&&<>
      <div className="panorama-controls"><span className="badge">{provider==="google"?"Google Street View":"Apple Look Around"}</span><label className="checkline"><input type="checkbox" checked={follow} onChange={e=>setFollow(e.target.checked)}/>{de?"Diagramm folgen":"Follow chart"}</label><button className="ghost compact" type="button" disabled={!point} onClick={()=>setTarget(point)}>{de?"Diese Stelle laden":"Load this point"}</button></div>
      {!target?<div className="panorama-empty">{de?"Für diese Stelle fehlen GPS-Koordinaten.":"GPS coordinates are missing at this point."}</div>:provider==="google"?<iframe className="panorama-frame" title="Google Street View" src={googleUrl} referrerPolicy="strict-origin-when-cross-origin" allowFullScreen/>:<div className="apple-panorama-wrap">
        <iframe ref={frame} className="panorama-frame" title="Apple Look Around" src="/panorama/apple" onLoad={sendApple} referrerPolicy="strict-origin-when-cross-origin" allowFullScreen/>
        {appleStatus!=="loaded"&&<div className="panorama-empty" role="status">{appleStatus==="loading"?(de?"Look Around wird geladen…":"Loading Look Around…"):appleStatus==="unavailable"?(de?"Hier ist keine Look-Around-Aufnahme verfügbar.":"No Look Around imagery is available here."):appleStatus==="browser-error"?(de?"Dieser Browser unterstützt Look Around nicht.":"This browser does not support Look Around."):(de?"Look Around konnte nicht geladen werden. Token und erlaubte Website prüfen.":"Look Around could not load. Check the token and allowed website.")}</div>}
      </div>}
      <small className="panorama-note">{de?"Aufnahmen des Anbieters, nicht vom Zeitpunkt deines Trainings. Die nächste verfügbare Aufnahme kann neben deiner tatsächlichen Position liegen. Ohne Abdeckung zeigt Google einen Hinweis im Fenster.":"Provider imagery, not from the time of your workout. The nearest available image may be beside your actual position. Google displays a notice in the viewer where imagery is unavailable."}</small>
    </>}
  </section>;
}
