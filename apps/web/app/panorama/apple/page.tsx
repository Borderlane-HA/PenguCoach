"use client";

import {useEffect,useRef} from "react";

type LookAroundView={destroy:()=>void;addEventListener:(type:string,listener:(event:any)=>void)=>void};
type Mapkit={LookAround:new(parent:HTMLElement,coordinate:{latitude:number;longitude:number},options:Record<string,unknown>)=>LookAroundView};
declare global {interface Window {mapkit?:Mapkit;pengucoachMapkitReady?:()=>void;}}

// Isolated iframe: each panorama owns its SDK/token lifetime. Nothing loads
// until the same-origin parent supplies the owner's credential after consent.
export default function ApplePanoramaPage(){
  const container=useRef<HTMLDivElement>(null);
  useEffect(()=>{
    let view:LookAroundView|null=null, token:string|null=null, script:HTMLScriptElement|null=null;
    let latest:{latitude:number;longitude:number}|null=null, ready=false, generation=0;
    let timeout:ReturnType<typeof setTimeout>|undefined;
    const status=(value:string)=>window.parent.postMessage({type:"pengucoach-look-around-status",status:value},location.origin);
    function show(){
      if(!ready||!latest||!container.current||!window.mapkit)return;
      const current=++generation;
      view?.destroy();view=null;container.current.replaceChildren();
      clearTimeout(timeout);status("loading");
      timeout=setTimeout(()=>{if(current===generation)status("service-error")},30000);
      try{
        view=new window.mapkit.LookAround(container.current,latest,{showsDialogControl:false,showsCloseControl:false,isNavigationEnabled:true,isZoomEnabled:true});
        view.addEventListener("load",()=>{if(current===generation){clearTimeout(timeout);status("loaded")}});
        view.addEventListener("error",event=>{
          if(current!==generation)return;
          clearTimeout(timeout);
          const type=event.detail?.type;
          status(type==="availability-error"?"unavailable":type==="browser-error"?"browser-error":"service-error");
        });
      }catch{clearTimeout(timeout);status("service-error");}
    }
    function receive(event:MessageEvent){
      if(event.source!==window.parent||event.origin!==location.origin||event.data?.type!=="pengucoach-look-around")return;
      const {latitude,longitude}=event.data;
      if(typeof latitude!=="number"||typeof longitude!=="number"||!Number.isFinite(latitude)||!Number.isFinite(longitude)||Math.abs(latitude)>90||Math.abs(longitude)>180)return;
      if(typeof event.data.token!=="string"||!event.data.token||event.data.token.length>8192)return;
      latest={latitude,longitude};
      if(token&&token!==event.data.token){status("service-error");return;}
      if(ready){show();return;}
      if(script)return;
      token=event.data.token;
      window.pengucoachMapkitReady=()=>{ready=true;show()};
      script=document.createElement("script");
      script.src="https://cdn.apple-mapkit.com/mk/x/mapkit.core.js";
      script.async=true;script.crossOrigin="anonymous";
      script.dataset.callback="pengucoachMapkitReady";
      script.dataset.token=token!;
      script.dataset.libraries="look-around,services";
      script.onerror=()=>status("service-error");
      timeout=setTimeout(()=>status("service-error"),30000);
      document.head.appendChild(script);
    }
    window.addEventListener("message",receive);
    window.parent.postMessage({type:"pengucoach-look-around-ready"},location.origin);
    return()=>{generation++;clearTimeout(timeout);window.removeEventListener("message",receive);view?.destroy();script?.remove();delete window.pengucoachMapkitReady;};
  },[]);
  return <div ref={container} style={{position:"fixed",inset:0,width:"100%",height:"100%",background:"var(--panel2)"}}/>;
}
