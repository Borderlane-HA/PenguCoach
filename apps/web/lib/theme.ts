export type CustomTheme={mode:"light"|"dark";background:string;surface:string;accent:string};
export type Appearance={theme:string;custom_theme?:CustomTheme;has_avatar:boolean;has_app_icon:boolean;avatar_version?:number;app_icon_version?:number};
export const DEFAULT_CUSTOM:CustomTheme={mode:"light",background:"#f2f7f5",surface:"#ffffff",accent:"#287b6e"};
const rgb=(hex:string)=>[1,3,5].map(i=>parseInt(hex.slice(i,i+2),16));
const hex=(values:number[])=>"#"+values.map(v=>Math.round(v).toString(16).padStart(2,"0")).join("");
export const mix=(a:string,b:string,weight:number)=>hex(rgb(a).map((v,i)=>v*(1-weight)+rgb(b)[i]*weight));
const luminance=(color:string)=>rgb(color).map(v=>v/255).map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4).reduce((sum,v,i)=>sum+v*[.2126,.7152,.0722][i],0);
export function contrast(a:string,b:string){const x=luminance(a),y=luminance(b);return(Math.max(x,y)+.05)/(Math.min(x,y)+.05)}
function readable(color:string,backgrounds:string[],towards:string,min=4.5){for(let n=0;n<=100;n++){const candidate=mix(color,towards,n/100);if(backgrounds.every(bg=>contrast(candidate,bg)>=min))return candidate}return towards}
export function customThemeVars(raw:CustomTheme){
 const input={...DEFAULT_CUSTOM,...raw},dark=input.mode==="dark",ink=dark?"#eff4fa":"#17232d",base=dark?"#080d14":"#ffffff";
 for(const key of ["background","surface","accent"] as const)if(!/^#[0-9a-f]{6}$/i.test(input[key]))input[key]=DEFAULT_CUSTOM[key];
 const background=readable(input.background,[ink],base,8),panel=readable(input.surface,[ink],base,8),panel2=mix(panel,background,.45),surfaces=[background,panel,panel2];
 const seed=readable(input.accent,surfaces,ink,6),soft=mix(panel,seed,dark?.15:.09),pale=mix(panel,seed,.045);
 const allSurfaces=[...surfaces,soft,pale];
 const accent=readable(seed,allSurfaces,ink),muted=readable(mix(ink,panel,.32),allSurfaces,ink),tone=(value:string)=>readable(value,allSurfaces,ink);
 return {"--bg":background,"--bg-soft":background,"--panel":panel,"--panel2":panel2,"--panel3":soft,"--surface-2":panel2,
  "--text":ink,"--text-strong":ink,"--muted":muted,"--muted-2":muted,"--border":mix(panel,ink,.18),"--border-strong":mix(panel,ink,.32),
  "--accent":accent,"--accent-strong":accent,"--accent-soft":soft,"--accent-pale":pale,"--primary-ink":contrast(accent,"#ffffff")>=contrast(accent,"#000000")?"#ffffff":"#000000",
  "--danger":tone("#bd444e"),"--warn":tone("#98640d"),"--blue":tone("#397db8"),"--violet":tone("#8662b5"),"--orange":tone("#b56a26"),"--green":tone("#418151"),
  "--danger-soft":mix(panel,tone("#bd444e"),.10),"--warn-soft":mix(panel,tone("#98640d"),.10),"--blue-soft":mix(panel,tone("#397db8"),.10),"--violet-soft":mix(panel,tone("#8662b5"),.10),"--orange-soft":mix(panel,tone("#b56a26"),.10),
  "--fitness-lilac":tone("#8662b5"),"--fitness-peach":tone("#b56a26"),"--mint":accent,"--rose":tone("#b95079"),"--rose-soft":mix(panel,tone("#b95079"),.10),
  "--chart-a":accent,"--chart-b":tone("#397db8"),"--chart-c":tone("#b56a26"),"--chart-d":tone("#8662b5")};
}
const CUSTOM_KEYS=Object.keys(customThemeVars(DEFAULT_CUSTOM));
export function applyAppearance(value:Pick<Appearance,"theme"|"custom_theme">){
 const root=document.documentElement;
 CUSTOM_KEYS.forEach(key=>root.style.removeProperty(key));root.style.removeProperty("color-scheme");delete root.dataset.colorMode;
 const theme=value.theme||"light";
 if(theme==="custom"){
  const custom=value.custom_theme||DEFAULT_CUSTOM,vars=customThemeVars(custom);
  Object.entries(vars).forEach(([key,color])=>root.style.setProperty(key,color));root.style.colorScheme=custom.mode;root.dataset.colorMode=custom.mode;
  try{localStorage.setItem("pengucoach_custom_theme",JSON.stringify({mode:custom.mode,vars}))}catch{}
 }
 document.documentElement.dataset.theme=theme;
 try{localStorage.setItem("pengucoach_theme",theme)}catch{}
}
export const themeBoot=`(()=>{try{const t=localStorage.getItem("pengucoach_theme");if(t)document.documentElement.dataset.theme=t;if(t==="custom"){const c=JSON.parse(localStorage.getItem("pengucoach_custom_theme")||"null");if(c&&(c.mode==="light"||c.mode==="dark")){const root=document.documentElement;root.dataset.colorMode=c.mode;root.style.colorScheme=c.mode;const keys=${JSON.stringify(CUSTOM_KEYS)};for(const key of keys){const v=c.vars?.[key];if(typeof v==="string"&&/^#[0-9a-f]{6}$/i.test(v))root.style.setProperty(key,v)}}}}catch{}})();`;
