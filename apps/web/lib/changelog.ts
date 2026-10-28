export type ChangelogSection={id:string;title:string;version:string|null;content:string};
export const CHANGELOG_SOURCE="https://github.com/Borderlane-HA/PenguCoach/blob/main/CHANGELOG.md";
const REPOSITORY_BASE="https://github.com/Borderlane-HA/PenguCoach/blob/main/";

export function changelogSections(markdown:string):ChangelogSection[]{
 const sections:ChangelogSection[]=[];let current:ChangelogSection|null=null,fenced=false;
 for(const line of markdown.replace(/\r\n?/g,"\n").split("\n")){
  if(/^\s*(```|~~~)/.test(line))fenced=!fenced;
  const heading=!fenced&&line.match(/^##\s+(.+?)(?:\s+#+)?\s*$/);
  if(heading){
   const title=heading[1],version=title.match(/\bv?\d+\.\d+\.\d+(?:[-.](?:alpha|beta|rc)[.-]?\d+(?:\.\d+)*)?/i)?.[0].replace(/^v/i,"")??null;
   current={id:`release-${sections.length}`,title,version,content:""};sections.push(current);
  }else if(current)current.content+=line+"\n";
 }
 return sections;
}

export function changelogLink(value:string):string|null{
 // React escapes note text; links additionally use a small protocol allowlist.
 if(!value||/[\u0000-\u0020\\]/.test(value))return null;
 try{const url=new URL(value,REPOSITORY_BASE);return ["https:","http:"].includes(url.protocol)&&!url.username&&!url.password?url.href:null}catch{return null}
}
