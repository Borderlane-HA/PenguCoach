// alpha.88: the public demo runs as static pages under a sub path
// (GitHub Pages: /PenguCoach). Normal installations have no base path.
export const BASE_PATH=process.env.NEXT_PUBLIC_BASE_PATH||"";
export const DEMO=process.env.NEXT_PUBLIC_DEMO==="1";
/** Prefix an absolute app path ("/today") with the base path; other values stay as they are. */
export function withBase(path:string){return path.startsWith("/")&&!path.startsWith("//")&&BASE_PATH&&!path.startsWith(BASE_PATH+"/")?BASE_PATH+path:path}
