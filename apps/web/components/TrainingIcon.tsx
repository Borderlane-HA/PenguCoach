import type {CSSProperties} from "react";
export default function TrainingIcon({kind,size=24,style}:{kind:string;size?:number;style?:CSSProperties}){
 const paths:Record<string,React.ReactNode>={
  run:<><circle cx="15" cy="4" r="2"/><path d="m12 9 3-2 3 4 3 1M8 9l4-1-2 6 4 3-2 5M10 14l-3 4H3"/></>,
  cycling:<><circle cx="5" cy="17" r="4"/><circle cx="19" cy="17" r="4"/><path d="m5 17 5-9 5 9H5m5-9h5m-2-4h3l3 13"/></>,
  strength:<><path d="M6 5v14M3 8v8M18 5v14m3-11v8M6 12h12"/></>,
  swim:<><path d="m4 12 5-4 4 4h5M8 7l4-3 5 2M2 18q2-3 5 0t5 0 5 0 5 0"/><circle cx="18" cy="7" r="2"/></>,
  moon:<path d="M20 15.5A8 8 0 0 1 8.5 4 8 8 0 1 0 20 15.5Z"/>,
  target:<><circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1"/></>,
  spark:<><path d="m12 2 3 7 7 3-7 3-3 7-3-7-7-3 7-3Z"/></>,
  calendar:<><rect x="3" y="5" width="18" height="16" rx="3"/><path d="M7 3v4m10-4v4M3 11h18"/></>,
  settings:<><path d="M3 7h18M3 17h18"/><circle cx="8" cy="7" r="3" fill="var(--panel)"/><circle cx="16" cy="17" r="3" fill="var(--panel)"/></>,
  arrow:<path d="M4 12h16m-6-6 6 6-6 6"/>,
  left:<path d="m15 5-7 7 7 7"/>,right:<path d="m9 5 7 7-7 7"/>,
  check:<path d="m5 12 4 4 10-10"/>,plus:<path d="M12 5v14M5 12h14"/>,
  sun:<><circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1 1m12 12 1 1M5 19l1-1M18 6l1-1"/></>,
  chat:<path d="M21 11a9 9 0 0 1-9 9H4l-2 2 1-7A9 9 0 1 1 21 11Z"/>,
 };
 return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" style={style}>{paths[kind]??paths.run}</svg>;
}
