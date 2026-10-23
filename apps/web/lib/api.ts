export const API=process.env.NEXT_PUBLIC_API_BASE_URL??"/api/v1";
export class ApiError extends Error{
  constructor(message:string,readonly status:number){super(message);this.name="ApiError"}
}
// The host maintenance service briefly pauses new changes while it updates or backs up.
export const MAINTENANCE_ACTIVE_MESSAGE={de:"Gerade läuft eine Systemwartung. Änderungen sind in wenigen Minuten wieder möglich.",en:"System maintenance is in progress. Changes are possible again in a few minutes."};
function maintenanceMessage(){try{return localStorage.getItem("pengucoach_lang")==="en"?MAINTENANCE_ACTIVE_MESSAGE.en:MAINTENANCE_ACTIVE_MESSAGE.de}catch{return MAINTENANCE_ACTIVE_MESSAGE.de}}
export async function api<T=unknown>(path:string,init:RequestInit={}):Promise<T>{
  const response=await fetch(`${API}${path}`,{...init,credentials:"include",headers:{"Content-Type":"application/json",...(init.headers??{})}});
  if(!response.ok){if(response.status===401&&typeof window!=="undefined"&&path!=="/auth/login")window.dispatchEvent(new Event("pengucoach-session-expired"));const body=await response.json().catch(()=>({}));if(response.status===503&&body.detail==="MAINTENANCE_ACTIVE")throw new ApiError(maintenanceMessage(),503);throw new ApiError(body.detail??`HTTP ${response.status}`,response.status)}
  const data=await response.json();
  if(init.method&&!["GET","HEAD"].includes(init.method.toUpperCase())&&typeof window!=="undefined")window.dispatchEvent(new CustomEvent("pengucoach-data-changed",{detail:{path}}));
  return data;
}
