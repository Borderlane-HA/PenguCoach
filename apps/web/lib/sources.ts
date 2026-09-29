export function sourceLabel(source?:string,lang="de"){
  const names:Record<string,string>={garmin:"Garmin",sparkyfitness:"SparkyFitness",manual:lang==="de"?"Manuell":"Manual",manual_body:lang==="de"?"Manuell":"Manual",manual_upload:lang==="de"?"Dateiimport":"File import",pengucoach:lang==="de"?"PenguCoach · berechnet":"PenguCoach · calculated",pengucoach_estimate:lang==="de"?"PenguCoach · geschätzt":"PenguCoach · estimated",withings:lang==="de"?"Withings · Archiv":"Withings · archive",unknown:lang==="de"?"Quelle unbekannt":"Unknown source"};
  return source?source.split("+").map(x=>names[x]??x).join(" + "):"—";
}
export function measuredLabel(value?:string,lang="de"){
  if(value?.startsWith("1970-01-01"))return lang==="de"?"Profilangabe · Datum unbekannt":"Profile · date unknown";
  return value?new Date(value).toLocaleString(lang==="de"?"de-DE":"en-GB",{dateStyle:"short",timeStyle:"short"}):"";
}
export function localDate(){const d=new Date();return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,"0")}-${String(d.getDate()).padStart(2,"0")}`}
