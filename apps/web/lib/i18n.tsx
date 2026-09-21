"use client";
import {createContext,useContext,useEffect,useState} from "react";
type Lang="de"|"en";
const I18n=createContext<{lang:Lang;setLang:(v:Lang)=>void}>({lang:"de",setLang:()=>{}});
export function I18nProvider({children}:{children:React.ReactNode}){const[lang,setLangState]=useState<Lang>("de");useEffect(()=>{const stored=localStorage.getItem("pengucoach_lang");if(stored==="de"||stored==="en")setLangState(stored)},[]);const setLang=(v:Lang)=>{setLangState(v);localStorage.setItem("pengucoach_lang",v)};return <I18n.Provider value={{lang,setLang}}>{children}</I18n.Provider>}
export function useI18n(){return useContext(I18n)}
export function bi(lang:Lang,de:string,en:string){return lang==="de"?de:en}
