"use client";

import {Fragment,ReactNode} from "react";

function inline(text:string):ReactNode[]{
  const parts=text.split(/(\*\*[^*]+\*\*)/g);
  return parts.map((part,i)=>part.startsWith("**")&&part.endsWith("**")?<strong key={i}>{part.slice(2,-2)}</strong>:<Fragment key={i}>{part}</Fragment>);
}

export default function AiReport({content}:{content:string}){
  return <div className="ai-report">{String(content??"").split(/\r?\n/).map((raw,i)=>{
    const line=raw.trim();
    if(!line)return <div className="ai-report-gap" key={i}/>;
    const h=line.match(/^(#{1,6})\s+(.+)$/);if(h){const level=Math.min(4,h[1].length);const cls=`ai-report-h${level}`;return <div className={cls} key={i}>{inline(h[2])}</div>}
    const bullet=line.match(/^[-*•]\s+(.+)$/);if(bullet)return <div className="ai-report-bullet" key={i}><span>•</span><div>{inline(bullet[1])}</div></div>;
    const numbered=line.match(/^(\d+[.)])\s+(.+)$/);if(numbered)return <div className="ai-report-bullet" key={i}><span>{numbered[1]}</span><div>{inline(numbered[2])}</div></div>;
    return <p key={i}>{inline(line)}</p>;
  })}</div>
}
