import "./globals.css";
import "leaflet/dist/leaflet.css";
import type {Metadata,Viewport} from "next";
import {I18nProvider} from "../lib/i18n";
import SessionProvider from "../lib/session";
import {themeBoot} from "../lib/theme";

export const metadata:Metadata={
  title:"PenguCoach",
  description:"Self-hosted AI Training & Health Coach",
  icons:{icon:"/pengucoach-icon.svg",shortcut:"/pengucoach-icon.svg"},
};

export const viewport:Viewport={width:"device-width",initialScale:1,viewportFit:"cover"};

export default function RootLayout({children}:{children:React.ReactNode}){
  return <html lang="de" suppressHydrationWarning><head><script dangerouslySetInnerHTML={{__html:themeBoot}}/></head><body><I18nProvider><SessionProvider>{children}</SessionProvider></I18nProvider></body></html>;
}
