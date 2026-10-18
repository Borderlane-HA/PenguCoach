"use client";
import {createContext,Fragment,useContext,useEffect,useRef,useState} from "react";
import {usePathname} from "next/navigation";
import {api} from "./api";
import {clearDataCache,invalidateDataCache,setCacheScope} from "./data-cache";
import {applyAppearance,Appearance} from "./theme";
import {bi,useI18n} from "./i18n";

export type Me={id:string;username:string;role:string;locale:string;safety_required:boolean;app_version:string;timezone?:string};
const Session=createContext<{me:Me|null;appearance:Appearance|null}>({me:null,appearance:null});
export const useSession=()=>useContext(Session);
export default function SessionProvider({children}:{children:React.ReactNode}){
 const {lang}=useI18n();
 const path=usePathname(),[me,setMe]=useState<Me|null>(null),[appearance,setAppearance]=useState<Appearance|null>(null);
 const loaded=useRef(false),authAt=useRef(0),identity=useRef(""),appearanceRequest=useRef(0);
 const protectedPage=path!=="/"&&path!=="/setup"&&path!=="/safety";
 useEffect(()=>{
  if(!protectedPage)return;
  let active=true,pending=false;
  const appearance=()=>{const request=++appearanceRequest.current;return api<Appearance>("/settings/appearance").then(v=>{if(active&&request===appearanceRequest.current){setAppearance(v);applyAppearance(v)}}).catch(()=>{})};
  const auth=async()=>{if(pending)return;pending=true;try{const user=await api<Me>("/auth/me",{cache:"no-store"});if(!active)return;if(user.safety_required){location.replace("/safety");return}const changed=identity.current!==user.id;identity.current=user.id;setCacheScope(user.id,user.timezone||"Europe/Berlin");setMe(user);authAt.current=Date.now();if(changed||!loaded.current){loaded.current=true;void appearance()}}catch{if(active){clearDataCache();setMe(null);location.replace("/")}}finally{pending=false}};
  if(!loaded.current)void auth();
  const focus=()=>{if(document.visibilityState==="visible"&&Date.now()-authAt.current>60000)void auth()};
  const changed=()=>invalidateDataCache();
  const expired=()=>{clearDataCache();setMe(null);location.replace("/")};
  window.addEventListener("focus",focus);window.addEventListener("pengucoach-appearance-changed",appearance);window.addEventListener("pengucoach-data-changed",changed);window.addEventListener("pengucoach-today-refresh",changed);window.addEventListener("pengucoach-feedback-updated",changed);window.addEventListener("pengucoach-session-expired",expired);
  return()=>{active=false;window.removeEventListener("focus",focus);window.removeEventListener("pengucoach-appearance-changed",appearance);window.removeEventListener("pengucoach-data-changed",changed);window.removeEventListener("pengucoach-today-refresh",changed);window.removeEventListener("pengucoach-feedback-updated",changed);window.removeEventListener("pengucoach-session-expired",expired)};
 },[protectedPage]);
 useEffect(()=>{if(!protectedPage){loaded.current=false;identity.current="";clearDataCache();setMe(null);setAppearance(null)}},[protectedPage]);
 return <Session.Provider value={{me,appearance}}>{protectedPage&&!me?<main className="auth-loading"><div className="loading-mark"><img src="/pengucoach-icon.svg" alt=""/></div><p>{bi(lang,"PenguCoach wird geladen…","Loading PenguCoach…")}</p></main>:<Fragment key={me?.id||"public"}>{children}</Fragment>}</Session.Provider>;
}
