export const API=process.env.NEXT_PUBLIC_API_BASE_URL??"/api/v1";
export async function api<T=unknown>(path:string,init:RequestInit={}):Promise<T>{
  const response=await fetch(`${API}${path}`,{...init,credentials:"include",headers:{"Content-Type":"application/json",...(init.headers??{})}});
  if(!response.ok){if(response.status===401&&typeof window!=="undefined"&&path!=="/auth/login")window.dispatchEvent(new Event("pengucoach-session-expired"));const body=await response.json().catch(()=>({}));throw new Error(body.detail??`HTTP ${response.status}`)}
  const data=await response.json();
  if(init.method&&!["GET","HEAD"].includes(init.method.toUpperCase())&&typeof window!=="undefined")window.dispatchEvent(new CustomEvent("pengucoach-data-changed",{detail:{path}}));
  return data;
}
