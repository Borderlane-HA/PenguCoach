"use client";
// Small "i" with an explanation: hover or focus on desktop, tap on touch screens.
// The bubble is positioned against the viewport, so cards with hidden overflow never clip it.
import {useEffect,useId,useLayoutEffect,useRef,useState} from "react";

const WIDTH=280,GAP=8,EDGE=12;

export default function InfoTip({text,label}:{text:string;label:string}){
  const [open,setOpen]=useState(false),[pos,setPos]=useState<{left:number;top:number;arrow:number;above:boolean}|null>(null);
  const id=useId(),root=useRef<HTMLSpanElement>(null),button=useRef<HTMLButtonElement>(null),bubble=useRef<HTMLSpanElement>(null),timer=useRef<ReturnType<typeof setTimeout>|null>(null),openedAt=useRef(0);
  useEffect(()=>{
    if(!open)return;
    const outside=(e:PointerEvent)=>{if(root.current&&e.target instanceof Node&&!root.current.contains(e.target))setOpen(false)};
    const esc=(e:KeyboardEvent)=>{if(e.key==="Escape")setOpen(false)};
    const close=()=>setOpen(false);
    document.addEventListener("pointerdown",outside);document.addEventListener("keydown",esc);window.addEventListener("scroll",close,true);window.addEventListener("resize",close);
    return()=>{document.removeEventListener("pointerdown",outside);document.removeEventListener("keydown",esc);window.removeEventListener("scroll",close,true);window.removeEventListener("resize",close)};
  },[open]);
  useLayoutEffect(()=>{
    if(!open||!button.current){setPos(null);return}
    const r=button.current.getBoundingClientRect(),vw=window.innerWidth,vh=window.innerHeight;
    const width=Math.min(WIDTH,vw-EDGE*2),h=bubble.current?.offsetHeight??80,center=r.left+r.width/2;
    const left=Math.min(Math.max(EDGE,center-width/2),vw-width-EDGE);
    const above=r.bottom+GAP+h>vh-EDGE&&r.top-GAP-h>EDGE;
    setPos({left,top:above?r.top-GAP-h:r.bottom+GAP,arrow:Math.min(Math.max(14,center-left),width-14),above});
  },[open]);
  const show=()=>{if(timer.current)clearTimeout(timer.current);setOpen(v=>{if(!v)openedAt.current=Date.now();return true})};
  // A tap fires hover/focus and click together: the click must not close what the tap just opened.
  const toggle=()=>setOpen(v=>{if(v&&Date.now()-openedAt.current<400)return true;if(!v)openedAt.current=Date.now();return !v});
  const hide=()=>{timer.current=setTimeout(()=>setOpen(false),120)};
  return <span className="info-tip" ref={root} onMouseEnter={show} onMouseLeave={hide}>
    <button ref={button} type="button" className="info-tip-button" aria-label={label} aria-describedby={open?id:undefined} onClick={toggle} onFocus={show} onBlur={hide}>i</button>
    {open&&<span ref={bubble} role="tooltip" id={id} className={`info-tip-bubble ${pos?.above?"above":""}`} style={pos?{left:pos.left,top:pos.top,["--arrow" as string]:`${pos.arrow}px`}:{visibility:"hidden"}}>{text}</span>}
  </span>;
}
