import "./globals.css";
import type {Metadata,Viewport} from "next";
import {I18nProvider} from "../lib/i18n";

export const metadata:Metadata={
  title:"PenguCoach",
  description:"Self-hosted AI Training & Health Coach",
  icons:{icon:"/pengucoach-icon.svg",shortcut:"/pengucoach-icon.svg"},
};

export const viewport:Viewport={width:"device-width",initialScale:1,viewportFit:"cover"};

export default function RootLayout({children}:{children:React.ReactNode}){
  return <html lang="de"><body><I18nProvider>{children}</I18nProvider></body></html>;
}
