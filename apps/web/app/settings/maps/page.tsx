"use client";

import {FormEvent,useEffect,useState} from "react";
import AppShell from "../../../components/AppShell";
import {api} from "../../../lib/api";
import {MapSettings} from "../../../lib/activityExplorer";
import {bi,useI18n} from "../../../lib/i18n";

function errorText(error:unknown,de:boolean){
  const code=error instanceof Error?error.message:"";
  if(code==="MAP_SECRET_STORAGE_UNAVAILABLE")return de?"Die verschlüsselte Speicherung ist nicht eingerichtet. Bitte den Administrator bitten, den PenguCoach-Verschlüsselungsschlüssel zu prüfen.":"Encrypted storage is not configured. Ask your administrator to check the PenguCoach encryption key.";
  if(code==="INVALID_MAP_CREDENTIAL")return de?"Der Zugang ist ungültig: Bitte ohne Leerzeichen und in der erlaubten Länge eingeben.":"Invalid credential: enter it without whitespace and within the allowed length.";
  return de?"Die Einstellungen konnten nicht geladen oder gespeichert werden. Bitte erneut versuchen.":"Could not load or save the settings. Please try again.";
}

export default function MapSettingsPage(){
  const {lang}=useI18n(), de=lang!=="en";
  const [settings,setSettings]=useState<MapSettings|null>(null),[google,setGoogle]=useState(""),[apple,setApple]=useState("");
  const [busy,setBusy]=useState(false),[message,setMessage]=useState(""),[failed,setFailed]=useState(false);
  async function load(){try{setSettings(await api<MapSettings>("/settings/maps",{cache:"no-store"}));setFailed(false)}catch(error){setMessage(errorText(error,de));setFailed(true)}}
  useEffect(()=>{void load()},[]);
  async function save(event:FormEvent){
    event.preventDefault();if(!settings||busy)return;
    setBusy(true);setMessage("");
    try{
      const payload={map_enabled:settings.map_enabled,preferred_provider:settings.preferred_provider,...(google.trim()?{google_api_key:google.trim()}:{}),...(apple.trim()?{apple_maps_token:apple.trim()}:{} )};
      setSettings(await api<MapSettings>("/settings/maps",{method:"PUT",body:JSON.stringify(payload)}));
      setGoogle("");setApple("");setFailed(false);setMessage(bi(lang,"Deine Karten-Einstellungen wurden gespeichert.","Your map settings have been saved."));
    }catch(error){setMessage(errorText(error,de));setFailed(true)}finally{setBusy(false)}
  }
  async function remove(provider:"google"|"apple"){
    if(busy)return;setBusy(true);setMessage("");
    try{
      const result=await api<MapSettings>(`/settings/maps/credentials/${provider}`,{method:"DELETE"});
      setSettings(current=>current?{...current,google_configured:result.google_configured,apple_configured:result.apple_configured}:result);
      if(provider==="google")setGoogle("");else setApple("");
      setFailed(false);setMessage(bi(lang,"Der persönliche Zugang wurde gelöscht.","Your personal credential has been deleted."));
    }catch(error){setMessage(errorText(error,de));setFailed(true)}finally{setBusy(false)}
  }
  return <AppShell title={bi(lang,"Karten & Straßenansicht","Maps & street view")}>
    <div className="page-head-modern"><div><span className="eyebrow">ACTIVITY EXPLORER</span><h1>{bi(lang,"Deine Strecke. Deine Perspektive.","Your route. Your perspective.")}</h1><p className="muted">{bi(lang,"Karte, Trainingsdiagramm und optionale Straßenansicht an derselben Stelle. Die Einstellungen und Zugänge gehören ausschließlich zu deinem Benutzerkonto.","Map, workout chart and optional street-level imagery at the same point. These settings and credentials belong only to your account.")}</p></div></div>
    {message&&<div className={failed?"ai-toast status-bad":"ai-toast"} role={failed?"alert":"status"}>{message}</div>}
    {!settings?<section className="card"><p>{bi(lang,"Einstellungen werden geladen…","Loading settings…")}</p><button type="button" className="ghost" onClick={load}>{bi(lang,"Erneut laden","Retry")}</button></section>:<form onSubmit={save} className="stack">
      <section className="card map-preferences"><div><span className="eyebrow">OPENSTREETMAP</span><h2>{bi(lang,"Streckenkarte","Route map")}</h2><p className="muted">{bi(lang,"Für die OpenStreetMap-Karte ist kein API-Schlüssel nötig. Beim Laden werden Kartenkacheln für den sichtbaren Bereich abgerufen; deine Messwerte bleiben in PenguCoach.","OpenStreetMap needs no API key. Map tiles for the visible area are requested when loading; your measurements stay in PenguCoach.")}</p><label className="checkline"><input type="checkbox" checked={settings.map_enabled} onChange={e=>setSettings({...settings,map_enabled:e.target.checked})}/>{bi(lang,"Streckenkarte in Aktivitäten anzeigen","Show route map in activities")}</label></div>
        <label>{bi(lang,"Bevorzugte Straßenansicht","Preferred street-level provider")}<select value={settings.preferred_provider} onChange={e=>setSettings({...settings,preferred_provider:e.target.value as "google"|"apple"})}><option value="google">Google Street View</option><option value="apple">Apple Look Around</option></select><small>{bi(lang,"Vor jeder Öffnung ist eine Bestätigung nötig. Der Anbieter kann dort gewechselt werden.","Each opening requires confirmation. You can switch the provider there.")}</small></label>
      </section>
      <div className="map-settings-grid">
        <section className="card map-provider-card"><div className="between"><span className="eyebrow">GOOGLE</span><span className="badge">{settings.google_configured?bi(lang,"Schlüssel hinterlegt","Key saved"):bi(lang,"Nicht eingerichtet","Not configured")}</span></div><h2>Street View</h2><p className="muted">{bi(lang,"Die interaktive Einbettung verwendet die Google Maps Embed API. Diese ist aktuell kostenlos; ein Google-Cloud-Projekt und ein API-Schlüssel sind erforderlich.","The interactive viewer uses Google Maps Embed API. It is currently free; a Google Cloud project and API key are required.")}</p>
          <label>{bi(lang,"Persönlicher API-Schlüssel","Personal API key")}<input type="password" autoComplete="new-password" maxLength={256} value={google} onChange={e=>setGoogle(e.target.value)} placeholder={settings.google_configured?bi(lang,"Leer lassen, um den Schlüssel zu behalten","Leave blank to keep the saved key"):"AIza…"}/></label>
          <small>{bi(lang,"Maps Embed API aktivieren und den Schlüssel auf diese PenguCoach-Website sowie diese API beschränken. Der Schlüssel wird nach Bestätigung im Browser für Google verwendet.","Enable Maps Embed API and restrict the key to this PenguCoach website and that API. After confirmation the browser uses the key for Google.")}</small>
          <div className="row"><a className="text-link" href="https://developers.google.com/maps/documentation/embed/get-api-key" target="_blank" rel="noopener noreferrer">{bi(lang,"Einrichtungsanleitung","Setup guide")} ↗</a>{settings.google_configured&&<button type="button" className="ghost compact" disabled={busy} onClick={()=>remove("google")}>{bi(lang,"Schlüssel löschen","Delete key")}</button>}</div>
        </section>
        <section className="card map-provider-card"><div className="between"><span className="eyebrow">APPLE</span><span className="badge">{settings.apple_configured?bi(lang,"Token hinterlegt","Token saved"):bi(lang,"Nicht eingerichtet","Not configured")}</span></div><h2>Look Around</h2><p className="muted">{bi(lang,"Apple Look Around verwendet MapKit JS und einen Maps-Token aus deinem Apple-Developer-Zugang. Die Verfügbarkeit hängt vom Ort und Browser ab; die Nutzung unterliegt Apples Kontingenten.","Apple Look Around uses MapKit JS and a Maps token from your Apple Developer account. Availability depends on location and browser, and Apple's usage quotas apply.")}</p>
          <label>{bi(lang,"Persönlicher Apple-Maps-Token","Personal Apple Maps token")}<input type="password" autoComplete="new-password" maxLength={8192} value={apple} onChange={e=>setApple(e.target.value)} placeholder={settings.apple_configured?bi(lang,"Leer lassen, um den Token zu behalten","Leave blank to keep the saved token"):"eyJ…"}/></label>
          <small>{bi(lang,"Einen für diese Website freigegebenen Web-Token hinterlegen, keinen privaten .p8-Signaturschlüssel. Abgelaufene Tokens hier ersetzen.","Enter a web token authorized for this website, not a private .p8 signing key. Replace expired tokens here.")}</small>
          <div className="row"><a className="text-link" href="https://developer.apple.com/documentation/mapkitjs/creating-a-maps-token" target="_blank" rel="noopener noreferrer">{bi(lang,"Token erstellen","Create token")} ↗</a>{settings.apple_configured&&<button type="button" className="ghost compact" disabled={busy} onClick={()=>remove("apple")}>{bi(lang,"Token löschen","Delete token")}</button>}</div>
        </section>
      </div>
      <section className="card subtle map-settings-footer"><p className="muted">{bi(lang,"Zugänge werden verschlüsselt gespeichert und nicht wieder im Eingabefeld angezeigt. Leere Felder behalten vorhandene Zugänge. Speichern lädt keine Straßenbilder; diese werden erst in einer Aktivität nach Bestätigung abgerufen.","Credentials are stored encrypted and are never displayed in the input fields again. Blank fields preserve saved credentials. Saving does not load street imagery; it is requested only after confirmation in an activity.")}</p><button type="submit" disabled={busy}>{busy?bi(lang,"Speichert…","Saving…"):bi(lang,"Einstellungen speichern","Save settings")}</button></section>
    </form>}
  </AppShell>;
}
