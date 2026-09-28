"use client";

import {FormEvent,useEffect,useState} from "react";
import AppShell from "../../../components/AppShell";
import {api} from "../../../lib/api";
import {bi,useI18n} from "../../../lib/i18n";

type WeatherSettings={enabled:boolean;location_name:string;latitude:number|null;longitude:number|null;timezone:string;country_code:string;admin1:string;include_in_training_plans:boolean;include_in_coach:boolean;provider:string;api_key_required:boolean;forecast_days:number};
type Location={id?:number;name:string;latitude:number;longitude:number;timezone:string;country?:string;country_code?:string;admin1?:string};
type Forecast={available:boolean;location:string;current?:Record<string,any>;daily?:Record<string,any>[]};

const codeText=(code:number|undefined,de:boolean)=>{
  if(code==null)return de?"Unbekannt":"Unknown";
  if(code===0)return de?"Klar":"Clear";
  if([1,2].includes(code))return de?"Leicht bewölkt":"Partly cloudy";
  if(code===3)return de?"Bewölkt":"Overcast";
  if([45,48].includes(code))return de?"Nebel":"Fog";
  if([51,53,55,56,57].includes(code))return de?"Nieselregen":"Drizzle";
  if([61,63,65,66,67,80,81,82].includes(code))return de?"Regen":"Rain";
  if([71,73,75,77,85,86].includes(code))return de?"Schnee":"Snow";
  if([95,96,99].includes(code))return de?"Gewitter":"Thunderstorm";
  return de?"Wechselhaft":"Mixed";
};

export default function WeatherSettingsPage(){
  const{lang}=useI18n();const de=lang!=="en";
  const[settings,setSettings]=useState<WeatherSettings|null>(null),[query,setQuery]=useState(""),[results,setResults]=useState<Location[]>([]),[forecast,setForecast]=useState<Forecast|null>(null),[msg,setMsg]=useState(""),[busy,setBusy]=useState(false),[searching,setSearching]=useState(false);

  async function refresh(){
    try{
      const value=await api<WeatherSettings>("/weather/settings");setSettings(value);
      if(value.enabled){try{setForecast(await api<Forecast>("/weather/forecast"))}catch{setForecast(null)}}
    }catch(e){setMsg(e instanceof Error?e.message:String(e))}
  }
  useEffect(()=>{void refresh()},[]);

  async function search(e:FormEvent){
    e.preventDefault();if(query.trim().length<2)return;setSearching(true);setMsg("");
    try{const data=await api<{results:Location[]}>(`/weather/locations?query=${encodeURIComponent(query.trim())}&language=${lang}`);setResults(data.results)}
    catch(e){setMsg(e instanceof Error?e.message:String(e))}finally{setSearching(false)}
  }
  function choose(location:Location){
    setSettings(v=>v?({...v,enabled:true,location_name:[location.name,location.admin1,location.country].filter(Boolean).join(", "),latitude:location.latitude,longitude:location.longitude,timezone:location.timezone||"auto",country_code:location.country_code||"",admin1:location.admin1||""}):v);setResults([]);setQuery(location.name);
  }
  async function save(){
    if(!settings)return;setBusy(true);setMsg("");
    try{
      const value=await api<WeatherSettings>("/weather/settings",{method:"PUT",body:JSON.stringify({enabled:settings.enabled,location_name:settings.location_name,latitude:settings.latitude,longitude:settings.longitude,timezone:settings.timezone||"auto",country_code:settings.country_code||"",admin1:settings.admin1||"",include_in_training_plans:settings.include_in_training_plans,include_in_coach:settings.include_in_coach})});setSettings(value);setMsg(bi(lang,"Wetter-Einstellungen gespeichert.","Weather settings saved."));
      if(value.enabled){try{setForecast(await api<Forecast>("/weather/forecast"))}catch{setForecast(null)}}else setForecast(null);
    }catch(e){setMsg(e instanceof Error?e.message:String(e))}finally{setBusy(false)}
  }
  const current=forecast?.current??{};
  return <AppShell title={bi(lang,"Wetter","Weather")}>
    <div className="page-head-modern"><div><span className="eyebrow">OPEN-METEO</span><h1>{bi(lang,"Wetter für deine Trainingsplanung","Weather for training planning")}</h1><p className="muted">{bi(lang,"PenguCoach kann kurzfristige Vorhersagen als weichen Planungsfaktor nutzen – etwa für Outdoor-Läufe, Radtraining, Hitze, Regen, Wind oder UV.","PenguCoach can use short-range forecasts as a soft planning factor for outdoor runs, cycling, heat, rain, wind or UV.")}</p></div></div>
    {msg&&<div className="ai-toast">{msg}</div>}
    <div className="weather-settings-grid">
      <section className="card"><div className="section-heading"><div><span className="eyebrow">LOCATION</span><h2>{bi(lang,"Trainingsort","Training location")}</h2></div>{settings?.enabled&&<span className="badge">{bi(lang,"Aktiv","Active")}</span>}</div>
        <form className="weather-search-row" onSubmit={search}><input value={query} onChange={e=>setQuery(e.target.value)} placeholder={bi(lang,"Ort oder PLZ suchen, z. B. Ingolstadt","Search city or postcode, e.g. Ingolstadt")}/><button disabled={searching||query.trim().length<2}>{searching?"…":bi(lang,"Suchen","Search")}</button></form>
        {results.length>0&&<div className="weather-results">{results.map((r,i)=><button type="button" className="weather-result" key={`${r.id??i}-${r.latitude}`} onClick={()=>choose(r)}><span><strong>{r.name}</strong><small>{[r.admin1,r.country].filter(Boolean).join(" · ")}</small></span><small>{r.latitude.toFixed(3)} · {r.longitude.toFixed(3)}</small></button>)}</div>}
        {settings?.location_name&&<div className="weather-current" style={{marginTop:14}}><strong>{current.temperature_2m!=null?`${Math.round(Number(current.temperature_2m))}°` : "☁"}</strong><div><strong>{settings.location_name}</strong><small>{current.weather_code!=null?codeText(Number(current.weather_code),de):bi(lang,"Ort gespeichert","Location saved")}{current.wind_speed_10m!=null?` · ${Math.round(Number(current.wind_speed_10m))} km/h ${bi(lang,"Wind","wind")}`:""}</small></div></div>}
        <div className="weather-plan-option" style={{marginTop:14}}><label className="checkline"><input type="checkbox" checked={Boolean(settings?.enabled)} onChange={e=>setSettings(v=>v?({...v,enabled:e.target.checked}):v)}/>{bi(lang,"Wetterintegration aktivieren","Enable weather integration")}</label><label className="checkline"><input type="checkbox" checked={Boolean(settings?.include_in_training_plans)} onChange={e=>setSettings(v=>v?({...v,include_in_training_plans:e.target.checked}):v)}/>{bi(lang,"Standardmäßig in Trainingsplänen berücksichtigen","Use in training plans by default")}</label><label className="checkline"><input type="checkbox" checked={Boolean(settings?.include_in_coach)} onChange={e=>setSettings(v=>v?({...v,include_in_coach:e.target.checked}):v)}/>{bi(lang,"Bei passenden Coach-Fragen berücksichtigen","Use for relevant Coach questions")}</label><small>{bi(lang,"Es werden nur die gespeicherten Koordinaten an Open-Meteo übertragen – keine Gesundheits- oder Trainingsdaten. Die Vorhersage wird nicht über ihr reales Forecast-Fenster hinaus extrapoliert.","Only the saved coordinates are sent to Open-Meteo — no health or training data. Forecasts are never extrapolated beyond their real forecast window.")}</small></div>
        <div className="form-actions" style={{marginTop:14}}><button type="button" onClick={save} disabled={busy||!settings}>{busy?"…":bi(lang,"Speichern","Save")}</button></div>
      </section>
      <section className="card"><div className="section-heading"><div><span className="eyebrow">FORECAST</span><h2>{bi(lang,"Nächste Tage","Next days")}</h2></div><span className="badge">{settings?.forecast_days??16}d</span></div>
        {forecast?.daily?.length?<div className="weather-days">{forecast.daily.slice(0,8).map((d:any)=><div className="weather-day" key={d.date}><strong>{new Date(`${d.date}T12:00:00`).toLocaleDateString(de?"de-DE":"en-GB",{weekday:"short",day:"2-digit",month:"2-digit"})}</strong><span>{codeText(Number(d.weather_code),de)}</span><span>{Math.round(Number(d.temperature_2m_min))}–{Math.round(Number(d.temperature_2m_max))} °C</span><small>{d.precipitation_probability_max!=null?`${d.precipitation_probability_max}% ${bi(lang,"Regen","rain")}`:""}{d.wind_speed_10m_max!=null?` · ${Math.round(Number(d.wind_speed_10m_max))} km/h`:""}</small></div>)}</div>:<div className="empty-state"><strong>{bi(lang,"Noch keine Vorhersage","No forecast yet")}</strong><span>{bi(lang,"Ort auswählen, Integration aktivieren und speichern.","Choose a location, enable the integration and save.")}</span></div>}
        <p className="muted" style={{marginTop:14,marginBottom:0}}>{bi(lang,"Datenquelle: ","Data source: ")}<a className="text-link" href="https://open-meteo.com/" target="_blank" rel="noreferrer">Open-Meteo</a>. {bi(lang,"Für private/nicht-kommerzielle Nutzung ist kein API-Key nötig.","No API key is required for private/non-commercial use.")}</p>
      </section>
    </div>
  </AppShell>
}
