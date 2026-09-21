export const API=process.env.NEXT_PUBLIC_API_BASE_URL??"/api/v1";
export async function api<T=unknown>(path:string,init:RequestInit={}):Promise<T>{
  const response=await fetch(`${API}${path}`,{...init,credentials:"include",headers:{"Content-Type":"application/json",...(init.headers??{})}});
  if(!response.ok){const body=await response.json().catch(()=>({}));throw new Error(body.detail??`HTTP ${response.status}`)}
  return response.json();
}
