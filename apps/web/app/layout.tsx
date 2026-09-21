import "./globals.css";import type {Metadata} from "next";import {I18nProvider} from "../lib/i18n";
export const metadata:Metadata={title:"PenguCoach",description:"Self-hosted AI Training & Health Coach"};
export default function RootLayout({children}:{children:React.ReactNode}){return <html lang="de"><body><I18nProvider>{children}</I18nProvider></body></html>}
