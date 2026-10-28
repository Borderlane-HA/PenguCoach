"use client";
// Version, license and links. Shown in System & Updates (admins) and on the updates page (everyone).
import {bi,type Lang} from "../lib/i18n";

export default function AboutPenguCoach({lang,version}:{lang:Lang;version?:string}){
  return <div className="about-page" id="about">
    <section className="card license-summary"><div><span className="eyebrow">PENGUCOACH</span><h1>v{version}</h1><p className="muted">{bi(lang,"Self-hosted Training & Health Coach","Self-hosted Training & Health Coach")}</p></div>
      <div><h2>PolyForm Noncommercial License 1.0.0</h2><p>{bi(lang,"Ab Alpha.44 ist PenguCoach für nicht-kommerzielle Zwecke lizenziert. Verkauf, bezahltes Hosting oder eine kommerzielle Produktintegration benötigen eine separate Erlaubnis des Rechteinhabers.","Starting with Alpha.44, PenguCoach is licensed for noncommercial purposes. Selling it, paid hosting, or commercial product integration requires separate permission from the copyright holder.")}</p></div>
      <div className="license-permissions"><span className="allowed">✓ {bi(lang,"Private Nutzung","Personal use")}</span><span className="allowed">✓ {bi(lang,"Nicht-kommerzielle Änderungen & Weitergabe","Noncommercial modification & redistribution")}</span><span className="blocked">✕ {bi(lang,"Verkauf / kommerzielles Angebot","Sale / commercial offering")}</span><span className="blocked">✕ {bi(lang,"Bezahltes Hosting / SaaS","Paid hosting / SaaS")}</span></div>
      <p className="muted">{bi(lang,"Maßgeblich sind die offiziellen Lizenzbedingungen:","The official license terms govern:")} <a href="https://polyformproject.org/licenses/noncommercial/1.0.0" target="_blank" rel="noreferrer">polyformproject.org/licenses/noncommercial/1.0.0 ↗</a></p>
      <p className="muted">{bi(lang,"Hinweis: Frühere unter MIT veröffentlichte Versionen behalten die damals gewährten Rechte.","Note: Earlier versions released under MIT retain the rights granted with those releases.")}</p>
    </section>
  </div>;
}
