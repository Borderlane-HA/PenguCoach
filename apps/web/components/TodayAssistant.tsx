"use client";
import {type RefObject} from "react";
import {bi,type Lang} from "../lib/i18n";

export function AssistantIcon({kind,complete=false,energy}:{kind:"checkin"|"reflection";complete?:boolean;energy?:number}){
 return <span className={`assistant-state-icon ${complete?"complete":""}`} aria-hidden="true"><svg viewBox="0 0 40 40" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
  {kind==="checkin"?<><rect x="6" y="12" width="25" height="16" rx="4"/><path d="M34 17v6"/>{energy!=null?<rect x="9" y="15" width={Math.max(0,Math.min(5,energy))*3.8} height="10" rx="1.5" fill="currentColor" stroke="none"/>:<path d="M15 20h8M19 16v8"/>}</>:<><path d="M27 7a13 13 0 1 0 6 23A13 13 0 0 1 27 7Z"/><path d="m10 8 1 3 3 1-3 1-1 3-1-3-3-1 3-1Z"/></>}
 </svg>{complete&&<span className="assistant-icon-check">✓</span>}</span>;
}

export default function AssistantDialog({dialogRef,id,title,steps,step,lang,busy,onClose,children,footer}:{dialogRef:RefObject<HTMLDialogElement|null>;id:string;title:string;steps:string[];step:number;lang:Lang;busy:boolean;onClose:()=>void;children:React.ReactNode;footer:React.ReactNode}){
 return <dialog ref={dialogRef} id={id} className="today-assistant-dialog" aria-labelledby={`${id}-title`} onClose={onClose} onCancel={e=>{if(busy)e.preventDefault()}} onClick={e=>{
  if(e.target===e.currentTarget&&!busy){const r=e.currentTarget.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)dialogRef.current?.close()}
 }}><div className="assistant-dialog-heading"><div><span className="eyebrow">{bi(lang,`Schritt ${step+1} von ${steps.length}`,`Step ${step+1} of ${steps.length}`)}</span><h2 id={`${id}-title`}>{title}</h2></div><button type="button" className="ghost assistant-close" disabled={busy} aria-label={bi(lang,"Assistent schließen","Close assistant")} onClick={()=>dialogRef.current?.close()}>×</button></div>
 <ol className="assistant-progress" aria-label={bi(lang,"Schritte","Steps")}>{steps.map((label,i)=><li key={label} className={i===step?"current":i<step?"visited":""} aria-current={i===step?"step":undefined}><span aria-hidden="true">{i<step?"✓":i+1}</span><small>{label}</small></li>)}</ol>
 <div className="assistant-step" key={step}>{children}</div><div className="assistant-footer">{footer}</div></dialog>;
}
