"use client";
import {useEffect,useRef,useState} from "react";
export default function Deferred({children,label}:{children:React.ReactNode;label:string}){
 const node=useRef<HTMLDivElement>(null),[visible,setVisible]=useState(false);
 useEffect(()=>{if(!node.current)return;if(!("IntersectionObserver" in window)){setVisible(true);return}const observer=new IntersectionObserver(entries=>{if(entries.some(e=>e.isIntersecting)){setVisible(true);observer.disconnect()}},{rootMargin:"180px"});observer.observe(node.current);return()=>observer.disconnect()},[]);
 return <div ref={node} className="deferred-card">{visible?children:<section className="card loading-panel" aria-label={label}><span className="metric-skeleton"/><span className="metric-skeleton short"/></section>}</div>;
}
