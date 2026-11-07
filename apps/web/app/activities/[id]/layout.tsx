// alpha.88: the static demo pre-renders one page per demo activity. Normal
// installations keep fully dynamic activity pages (nothing is pre-rendered).
import fs from "node:fs";
import path from "node:path";

export function generateStaticParams(){
  if(process.env.NEXT_PUBLIC_DEMO!=="1")return [];
  try{
    const file=path.join(process.cwd(),"demo","data","activities.json");
    return (JSON.parse(fs.readFileSync(file,"utf8")) as string[]).map(id=>({id}));
  }catch{return []}
}

export default function ActivityLayout({children}:{children:React.ReactNode}){return children}
