"use client";
import {createContext,Fragment,useContext,useEffect,useRef,useState} from "react";
import {usePathname} from "next/navigation";
import {api,ApiError} from "./api";
import {clearDataCache,invalidateDataCache,setCacheScope} from "./data-cache";
import {applyAppearance,Appearance} from "./theme";
import {bi,useI18n} from "./i18n";

export type Me={id:string;username:string;role:string;locale:string;safety_required:boolean;app_version:string;timezone?:string};
const Session=createContext<{me:Me|null;appearance:Appearance|null}>({me:null,appearance:null});
export const useSession=()=>useContext(Session);
const AUTH_TIMEOUT=15000,RETRY_DELAY=5000,MAX_AUTO_RETRIES=12;
export default function SessionProvider({children}:{children:React.ReactNode}){
 const {lang}=useI18n();
 const path=usePathname(),[me,setMe]=useState<Me|null>(null),[appearance,setAppearance]=useState<Appearance|null>(null);
 const[unavailable,setUnavailable]=useState(false),[checking,setChecking]=useState(false),[paused,setPaused]=useState(false);
 const loaded=useRef(false),authAt=useRef(0),identity=useRef(""),appearanceRequest=useRef(0),retryAuth=useRef<()=>void>(()=>{});
 const protectedPage=path!=="/"&&path!=="/setup"&&path!=="/safety";
 useEffect(()=>{
  if(!protectedPage)return;
  let active=true,pending=false,retries=0,retryTimer:ReturnType<typeof setTimeout>|undefined,controller:AbortController|undefined;
  const clearRetry=()=>{if(retryTimer)clearTimeout(retryTimer);retryTimer=undefined};
  const appearance=()=>{const request=++appearanceRequest.current;return api<Appearance>("/settings/appearance").then(v=>{if(active&&request===appearanceRequest.current){setAppearance(v);applyAppearance(v)}}).catch(()=>{})};
  const auth=async()=>{
   if(!active||pending)return;
   clearRetry();pending=true;setChecking(true);controller=new AbortController();
   const deadline=setTimeout(()=>controller?.abort(),AUTH_TIMEOUT);
   try{
    const user=await api<Me>("/auth/me",{cache:"no-store",signal:controller.signal});
    if(!active)return;
    if(user.safety_required){location.replace("/safety");return}
    const changed=identity.current!==user.id;identity.current=user.id;
    setCacheScope(user.id,user.timezone||"Europe/Berlin");setMe(user);authAt.current=Date.now();
    setUnavailable(false);setPaused(false);retries=0;
    if(changed||!loaded.current){loaded.current=true;void appearance()}
   }catch(error){
    if(!active||error instanceof ApiError&&error.status===401)return;
    // A stopped API, proxy error or timeout says nothing about cookie validity.
    // Keep the last verified identity and its cache scope while reconnecting.
    setUnavailable(true);
    if(retries<MAX_AUTO_RETRIES){
     retries++;retryTimer=setTimeout(()=>{retryTimer=undefined;if(document.visibilityState==="visible")void auth()},RETRY_DELAY);
    }else setPaused(true);
   }finally{clearTimeout(deadline);pending=false;if(active)setChecking(false)}
  };
  const retry=()=>{if(!active)return;retries=0;setPaused(false);void auth()};
  retryAuth.current=retry;
  if(!loaded.current)void auth();
  const focus=()=>{if(document.visibilityState==="visible"&&Date.now()-authAt.current>60000)retry()};
  const changed=()=>invalidateDataCache();
  const expired=()=>{clearRetry();retries=MAX_AUTO_RETRIES;clearDataCache();setMe(null);location.replace("/")};
  window.addEventListener("focus",focus);window.addEventListener("online",retry);document.addEventListener("visibilitychange",focus);
  window.addEventListener("pengucoach-appearance-changed",appearance);window.addEventListener("pengucoach-data-changed",changed);window.addEventListener("pengucoach-today-refresh",changed);window.addEventListener("pengucoach-feedback-updated",changed);window.addEventListener("pengucoach-session-expired",expired);
  return()=>{
   active=false;clearRetry();controller?.abort();retryAuth.current=()=>{};
   window.removeEventListener("focus",focus);window.removeEventListener("online",retry);document.removeEventListener("visibilitychange",focus);
   window.removeEventListener("pengucoach-appearance-changed",appearance);window.removeEventListener("pengucoach-data-changed",changed);window.removeEventListener("pengucoach-today-refresh",changed);window.removeEventListener("pengucoach-feedback-updated",changed);window.removeEventListener("pengucoach-session-expired",expired);
  };
 },[protectedPage]);
 useEffect(()=>{if(!protectedPage){loaded.current=false;identity.current="";clearDataCache();setMe(null);setAppearance(null);setUnavailable(false);setChecking(false);setPaused(false)}},[protectedPage]);
 return <Session.Provider value={{me,appearance}}>{protectedPage&&!me?<main className="auth-loading"><div className="loading-mark"><img src="/pengucoach-icon.svg" alt=""/></div><p role="status">{unavailable?bi(lang,"PenguCoach ist momentan nicht erreichbar. Dein Anmeldestatus konnte noch nicht geprüft werden.","PenguCoach is temporarily unavailable. Your sign-in status could not be checked yet."):bi(lang,"PenguCoach wird geladen…","Loading PenguCoach…")}</p>{unavailable&&<><small>{paused?bi(lang,"Die automatische Prüfung ist pausiert. Du kannst sie jederzeit erneut starten.","Automatic checks are paused. You can restart them at any time."):bi(lang,"Die Verbindung wird automatisch erneut geprüft.","The connection is checked again automatically.")}</small><button type="button" className="ghost" disabled={checking} onClick={()=>retryAuth.current()}>{checking?bi(lang,"Prüfe …","Checking …"):bi(lang,"Erneut prüfen","Try again")}</button></>}</main>:<Fragment key={me?.id||"public"}>{children}</Fragment>}</Session.Provider>;
}
