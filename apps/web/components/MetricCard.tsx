import {ReactNode} from "react";
export default function MetricCard({label,value,note,tone,loading=false,error=false,children,action}:{label:string;value:ReactNode;note:ReactNode;tone:string;loading?:boolean;error?:boolean;children?:ReactNode;action?:ReactNode}){
 return <article className={`health-metric-card metric-card-modern tone-${tone} ${loading?"metric-loading":""}`} aria-busy={loading} data-metric={tone}>
  <div className="health-metric-top"><span className="metric-symbol" aria-hidden="true"><svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">{tone==="steps"?<><ellipse cx="8" cy="8" rx="3" ry="5" transform="rotate(-20 8 8)"/><path d="M8 15c-2 0-3 2-2 3s3 1 4-1M16 11c2 0 3 3 2 6s-3 5-5 4-2-3-1-5 2-5 4-5Z"/></>:tone==="heart"?<path d="M3 12h4l2-6 4 12 2-6h6"/>:tone==="sleep"?<path d="M20 14a8 8 0 0 1-10-10A8 8 0 1 0 20 14Z"/>:tone==="water"?<path d="M12 3c-3 4-7 8-7 12a7 7 0 0 0 14 0c0-4-4-8-7-12ZM9 16c0 1 1 2 2 2"/>:tone==="stress"?<><path d="M5 15a8 8 0 0 1 14 0M12 13l4-5"/><circle cx="12" cy="15" r="2"/></>:<><path d="M5 16V9M12 19V5M19 14V10"/><circle cx="5" cy="7" r="1"/><circle cx="19" cy="17" r="1"/></>}</svg></span><span className="metric-label">{label}</span>{action}</div>
  <div className="metric-value">{loading?<span className="metric-skeleton"/>:error?"—":value}</div>
  <div className="kpi-note">{loading?<span className="metric-skeleton short"/>:note}</div>{children}
 </article>;
}
