"use client";
import {useCallback,useEffect,useSyncExternalStore} from "react";
import {api} from "./api";

type Snapshot<T>={data:T|undefined;error:string;loading:boolean;updatedAt:number};
type Entry={snapshot:Snapshot<any>;listeners:Set<()=>void>;promise:Promise<void>|null;generation:number;path:string};
const EMPTY:Snapshot<any>={data:undefined,error:"",loading:true,updatedAt:0};
const entries=new Map<string,Entry>();
let scope="";
let zone="Europe/Berlin",day="";
const currentDay=()=>new Intl.DateTimeFormat("sv-SE",{timeZone:zone,year:"numeric",month:"2-digit",day:"2-digit"}).format(new Date());
const scopeListeners=new Set<()=>void>();
const subscribeScope=(fn:()=>void)=>{scopeListeners.add(fn);return()=>{scopeListeners.delete(fn)}};
export function setCacheScope(value:string,timezone=zone){zone=timezone;try{currentDay()}catch{zone="UTC"}const today=currentDay();if(value!==scope||today!==day){entries.clear();scope=value;day=today;scopeListeners.forEach(fn=>fn())}}
export function clearDataCache(){entries.clear();scope="";scopeListeners.forEach(fn=>fn())}
function entry(path:string){const key=scope+":"+currentDay()+":"+path;let value=entries.get(key);if(!value){if(entries.size>=128)for(const [old,item] of entries){if(!item.listeners.size){entries.delete(old);break}}value={snapshot:EMPTY,listeners:new Set(),promise:null,generation:0,path};entries.set(key,value)}return value}
function emit(value:Entry,patch:Partial<Snapshot<any>>){value.snapshot={...value.snapshot,...patch};value.listeners.forEach(fn=>fn())}
async function request(value:Entry){
 if(value.promise)return value.promise;
 const generation=value.generation;
 emit(value,{loading:true,error:""});
 const promise=(async()=>{try{const data=await api(value.path);if(generation===value.generation)emit(value,{data,updatedAt:Date.now(),error:""})}catch(e){if(generation===value.generation)emit(value,{error:e instanceof Error?e.message:String(e)})}})();
 value.promise=promise;
 await promise;
 if(value.promise===promise){value.promise=null;if(generation!==value.generation&&value.listeners.size)void request(value);else emit(value,{loading:false})}
}
export function invalidateDataCache(){for(const value of entries.values()){value.generation++;emit(value,{updatedAt:0});if(value.listeners.size)void request(value)}}
export function cacheQueryResult<T>(path:string,data:T){if(!scope)return;const value=entry(path);value.generation++;emit(value,{data,updatedAt:Date.now(),error:"",loading:false})}
export function useCachedQuery<T>(path:string|null,ttl=30000){
 useSyncExternalStore(subscribeScope,()=>scope,()=>"");
 const value=path&&scope?entry(path):null;
 const subscribe=useCallback((fn:()=>void)=>{if(!value)return()=>{};value.listeners.add(fn);return()=>{value.listeners.delete(fn)}},[value]);
 const get=useCallback(()=>value?.snapshot??EMPTY,[value]);
 const state=useSyncExternalStore(subscribe,get,()=>EMPTY) as Snapshot<T>;
 const refresh=useCallback(()=>{if(value)return request(value);return Promise.resolve()},[value]);
 useEffect(()=>{if(!value)return;if(!value.snapshot.updatedAt||Date.now()-value.snapshot.updatedAt>=ttl)void request(value);const focus=()=>{if(document.visibilityState!=="visible")return;if(currentDay()!==day){setCacheScope(scope);return}if(Date.now()-value.snapshot.updatedAt>=ttl)void request(value)};window.addEventListener("focus",focus);document.addEventListener("visibilitychange",focus);const timer=setInterval(focus,120000);return()=>{window.removeEventListener("focus",focus);document.removeEventListener("visibilitychange",focus);clearInterval(timer)}},[value,ttl]);
 return {...state,refresh};
}
