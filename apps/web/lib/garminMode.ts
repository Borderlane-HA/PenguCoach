"use client";
// Shared, cached read of the Garmin connection method for greying out features.
import {useEffect,useState} from "react";
import {api} from "./api";
import type {GarminModeInfo} from "./garminAuth";

let cached:Promise<GarminModeInfo|null>|null=null,cachedAt=0;
export function loadGarminMode(force=false){
  if(!cached||force||Date.now()-cachedAt>60_000){cachedAt=Date.now();cached=api<GarminModeInfo>("/garmin/status").catch(()=>null)}
  return cached;
}
export function useGarminMode(){
  const [info,setInfo]=useState<GarminModeInfo|null>(null);
  useEffect(()=>{let alive=true;void loadGarminMode().then(v=>{if(alive)setInfo(v)});return()=>{alive=false}},[]);
  return info;
}
