// In-app help, German and English. Keep this file current with every release:
// a new feature or setting gets a topic here, with a link to where it is set.
export type Lang = "de" | "en";
type Text = {de:string;en:string};
export type HelpTopic = {q:Text;a:Text};
export type HelpLink = {href:string;label:Text;admin?:boolean};
export type HelpSection = {id:string;title:Text;intro:Text;topics:HelpTopic[];links:HelpLink[];admin?:boolean};

const t=(de:string,en:string):Text=>({de,en});

export const HELP_SECTIONS:HelpSection[] = [
  {id:"start",title:t("Erste Schritte","Getting started"),
   intro:t("PenguCoach sammelt deine Trainings- und Gesundheitsdaten an einem Ort, wertet sie aus und hilft dir mit einem persönlichen Coach beim Planen.","PenguCoach brings your training and health data together, analyses it and helps you plan with a personal coach."),
   topics:[
    {q:t("Was richte ich zuerst ein?","What do I set up first?"),a:t("Verbinde eine Datenquelle (Garmin oder SparkyFitness). Danach erscheinen Messwerte auf „Heute“ und Aktivitäten im Tagebuch. Ohne Verbindung kannst du FIT-, GPX- oder TCX-Dateien importieren.","Connect a data source (Garmin or SparkyFitness). Readings then appear on Today and activities in the journal. Without a connection you can import FIT, GPX or TCX files.")},
    {q:t("Wo sehe ich, ob alles verbunden ist?","Where do I see whether everything is connected?"),a:t("Oben rechts zeigt der Status-Punkt den Zustand. Fährst du mit der Maus darüber (oder tippst darauf), siehst du System, Verbindungen, letzte Synchronisierung und kannst die Ansicht aktualisieren.","The status dot at the top right shows the state. Hover over it (or tap it) to see the system, connections and last sync, and to refresh the view.")},
    {q:t("Wie wechsle ich die Sprache?","How do I change the language?"),a:t("Mit dem Schalter DE/EN oben rechts. Die Einstellung gilt für diesen Browser.","With the DE/EN switch at the top right. The setting applies to this browser.")},
   ],
   links:[{href:"/settings/garmin",label:t("Garmin verbinden","Connect Garmin")},{href:"/settings/sparkyfitness",label:t("SparkyFitness verbinden","Connect SparkyFitness")},{href:"/activities",label:t("Training importieren","Import activity")}]},

  {id:"today",title:t("Heute","Today"),
   intro:t("Deine Startseite: Tagesampel, Check-in, Messwerte und alles, was du heute brauchst – so angeordnet, wie du willst.","Your home page: daily readiness, check-in, readings and whatever you need today – arranged the way you like."),
   topics:[
    {q:t("Wie passe ich „Heute“ an?","How do I customize Today?"),a:t("Über „Anpassen“ oben rechts auf der Seite. Unter „Bereiche“ schaltest du Karten an oder aus und sortierst sie mit den Pfeilen. Unter „Messwerte“ wählst du die Werte. Unter „Ansicht“ stellst du Kompakt/Luftig und deine bevorzugte Trainingszeit ein.","Use “Customize” at the top right of the page. Under “Sections” switch cards on or off and reorder them with the arrows. Under “Readings” choose the values. Under “View” set compact/comfortable and your preferred training time.")},
    {q:t("Was zeigt die Tagesampel?","What does the daily readiness show?"),a:t("Eine Zahl von 0 bis 100 und eine Farbe: Grün heißt Training nach Plan, Gelb locker trainieren, Rot Erholung einplanen. Grundlage sind Schlaf, HRV, Ruhepuls, Stress, Body Battery, dein Check-in und dein Trainingsfeedback. „Warum?“ zeigt, welche Werte wie stark einfließen und wie gut die Datenbasis ist.","A number from 0 to 100 and a colour: green means train as planned, yellow keep it easy, red make time for recovery. It is based on sleep, HRV, resting heart rate, stress, Body Battery, your check-in and your training feedback. “Why?” shows how much each value counts and how good the data basis is.")},
    {q:t("Wozu der Check-in?","What is the check-in for?"),a:t("Energie, Muskelkater, Beschwerden und verfügbare Zeit ergänzen die Messwerte. Schon ein kurzer Check-in reicht, damit die Tagesampel eine Einschätzung geben kann. Abends kannst du im Tagesabschluss auf den Tag zurückblicken.","Energy, soreness, discomfort and available time complement the readings. A short check-in is enough for the readiness to give an assessment. In the evening the daily wrap-up lets you look back on the day.")},
    {q:t("Ein Wert fehlt oder ist ausgegraut","A reading is missing or greyed out"),a:t("Ausgegraute Werte liefert deine Verbindung nicht – zum Beispiel die Geräte-Bereitschaft beim Garmin API-Key. Fehlt ein Wert nur heute, hat die Uhr ihn noch nicht synchronisiert.","Greyed-out readings are not delivered by your connection – for example device readiness with the Garmin API key. If a value is missing only today, the watch has not synced it yet.")},
   ],
   links:[{href:"/today",label:t("Zu „Heute“","Open Today")},{href:"/settings/weather",label:t("Wetter für Trainingsfenster","Weather for training windows")}]},

  {id:"health",title:t("Gesundheit","Health"),
   intro:t("Deine Erholungs- und Körperwerte mit Trend, kurzer Erklärung und dem Coach an deiner Seite.","Your recovery and body values with trend, a short explanation and the coach at your side."),
   topics:[
    {q:t("Was bedeuten Kachel, Pfeil und Kurve?","What do tile, arrow and curve mean?"),a:t("Die große Zahl ist dein Durchschnitt im gewählten Zeitraum. Der Pfeil vergleicht die erste mit der zweiten Hälfte des Zeitraums: grün heißt besser, orange schlechter, „stabil“ heißt kaum Veränderung. Die kleine Kurve zeigt den Verlauf. Tage ohne Messung zählen nie als Null.","The big number is your average for the chosen period. The arrow compares the first and second half of the period: green means better, orange worse, “stable” means hardly any change. The small curve shows the trend. Days without a reading never count as zero.")},
    {q:t("Erklärungen per „i“","Explanations via “i”"),a:t("Das kleine „i“ neben einem Wert erklärt, was er bedeutet. Am Computer reicht es, mit der Maus darüberzufahren, auf Handy und Tablet tippst du darauf.","The small “i” next to a value explains what it means. On a computer just hover over it, on phone and tablet tap it.")},
    {q:t("Einen Wert mit dem Coach besprechen","Discuss a value with the coach"),a:t("Das Funken-Symbol auf einer Kachel öffnet einen neuen Coach-Chat mit deinen Zahlen und der Frage, was der Wert aussagt und wie du ihn verbessern kannst. Du kannst die Frage vor dem Absenden anpassen. „Einordnen“ oben fasst alle Werte zusammen.","The spark icon on a tile opens a new coach chat with your numbers and the question what the value means and how to improve it. You can edit the question before sending. “Assess” at the top summarises all values.")},
    {q:t("Rückblick","Recap"),a:t("„Rückblick“ spielt deine Entwicklung als kurze Animation ab – Schlaf, Herz, Schritte und Energie für Woche, Monat, drei Monate oder Jahr, jeweils im Vergleich zum Zeitraum davor.","“Recap” plays your progress as a short animation – sleep, heart, steps and energy for a week, month, three months or year, each compared with the period before.")},
    {q:t("Seite anpassen","Customize the page"),a:t("„Anpassen“ oben rechts: Bereiche ein- und ausblenden und sortieren, die Werte für Kacheln und Verläufe wählen und festlegen, mit welchem Zeitraum die Seite öffnet. Die Datenabdeckung ist standardmäßig ausgeblendet.","“Customize” at the top right: show, hide and sort sections, choose the values for tiles and trends and set the period the page opens with. Data coverage is hidden by default.")},
    {q:t("Körperwerte selbst eintragen","Enter body values yourself"),a:t("Unter Gesundheit → Körperwerte → „Eintragen“. Ein eigener Wert gilt, bis eine neuere Messung für denselben Wert kommt. Unter jedem Körperwert steht, woher er stammt.","Under Health → Body → “Add”. Your value applies until a newer measurement arrives for the same metric. Each body value shows where it comes from.")},
    {q:t("Etagen","Floors"),a:t("Gestiegene Etagen kommen von Garmin und SparkyFitness (Höhenmesser der Uhr). Auf der Schritte-Kachel steht der Tagesschnitt; als eigene Kachel wählst du „Etagen“ unter „Anpassen“ – auf Gesundheit und auf „Heute“.","Floors climbed come from Garmin and SparkyFitness (the watch's barometer). The steps tile shows the daily average; pick “Floors” as its own tile under “Customize” – on Health and on Today.")},
    {q:t("Verlauf der Körperwerte","Body value trend"),a:t("Unter dem Körperwerte-Bereich wählst du Gewicht, Körperfett, Muskelmasse, Körperwasser, Knochenmasse oder BMI. Gezeigt werden nur Tage mit Messung – wer sich nicht täglich wiegt, sieht trotzdem eine durchgehende Linie ohne Nullwerte.","Below the body section choose weight, body fat, muscle mass, body water, bone mass or BMI. Only days with a measurement are shown – if you do not weigh yourself daily, the line still runs through without zeros.")},
    {q:t("Mein Schrittziel","My step target"),a:t("Auf „Heute“ an der Schritte-Kachel (↗) stellst du dein tägliches Ziel ein, auf Wunsch mit automatischem Vorschlag.","On “Today”, set your daily target on the steps tile (↗), optionally with an automatic suggestion.")},
   ],
   links:[{href:"/health",label:t("Zu Gesundheit","Open Health")}]},

  {id:"activities",title:t("Aktivitäten","Activities"),
   intro:t("Dein Trainingstagebuch mit Karte, Diagrammen, Abschnitten, Showcase und Rückblick.","Your training journal with map, charts, splits, showcase and recap."),
   topics:[
    {q:t("Datei importieren (FIT, GPX, TCX)","Import a file (FIT, GPX, TCX)"),a:t("„Training importieren“ auf der Aktivitäten-Seite. Bei GPX/TCX berechnet PenguCoach Distanz, Tempo und Bewegungszeit aus den Punkten. Gibt es zur selben Zeit schon eine Aktivität, fragt PenguCoach nach, damit nichts doppelt zählt. Geplante Routen ohne Zeitstempel sind keine Aufzeichnung und werden abgelehnt.","“Import activity” on the activities page. For GPX/TCX PenguCoach calculates distance, pace and moving time from the points. If an activity at the same time already exists, PenguCoach asks first so nothing is counted twice. Planned routes without timestamps are not recordings and are rejected.")},
    {q:t("Showcase und Rückblick","Showcase and recap"),a:t("„Showcase“ in einer Aktivität erstellt ein Bild zum Teilen. „Rückblick“ in der Übersicht spielt eine animierte Zusammenfassung für Tag, Woche, Monat, Jahr oder alles ab.","“Showcase” inside an activity creates a shareable image. “Recap” in the overview plays an animated summary for a day, week, month, year or all time.")},
    {q:t("Karte und Diagramm einer Aktivität","Map and chart of an activity"),a:t("Fahr mit der Maus an der Strecke oder im Diagramm entlang: Marker und Werte (Zeit, Distanz, Puls, Tempo, Höhe …) folgen live, die Werte stehen direkt auf der Karte. Ein Klick oder der Regler unter dem Diagramm setzt eine feste Markierung, zu der die Ansicht zurückkehrt. Auf dem Handy tippst du auf Strecke, Diagramm oder Regler. Den „Analysebereich“ (z. B. nur die zweite Hälfte) findest du rechts neben Replay.","Move the mouse along the route or the chart: marker and values (time, distance, heart rate, pace, elevation …) follow live and are shown right on the map. A click or the slider below the chart sets a fixed marker the view returns to. On a phone, tap the route, chart or slider. The “Analysis range” (e.g. only the second half) is next to Replay.")},
    {q:t("Strecke vorbereiten und vergleichen","Prepare and compare a route"),a:t("„Diese Strecke vorbereiten“ zeigt Anstiege und schnelle Passagen der Aufnahme. „Vergleich starten“ sucht frühere Aufzeichnungen derselben Sportart auf derselben Strecke – mit FIT-Datei oder als GPS-Spur aus SparkyFitness. Liefert eine App keine brauchbare Distanz, berechnet PenguCoach sie aus den GPS-Punkten.","“Prepare this route” shows climbs and fast passages of the recording. “Start comparison” looks for earlier recordings of the same sport on the same route – with a FIT file or as a SparkyFitness GPS track. If an app delivers no usable distance, PenguCoach calculates it from the GPS points.")},
    {q:t("Die Strecke hat Lücken","The route has gaps"),a:t("Lücken entstehen nur noch bei echten GPS-Sprüngen. SparkyFitness speichert vereinfachte Spuren; lange gerade Stücke werden trotzdem durchgehend gezeichnet.","Gaps now only appear at real GPS jumps. SparkyFitness stores simplified tracks; long straight stretches are still drawn continuously.")},
   ],
   links:[{href:"/activities",label:t("Zu den Aktivitäten","Open activities")},{href:"/settings/maps",label:t("Karten & Straßenansicht","Maps & street view")}]},

  {id:"training",title:t("Training & Pläne","Training & plans"),
   intro:t("Trainingspläne erstellen, anpassen, mit dem Ist vergleichen und auf die Garmin-Uhr übertragen.","Create and adjust training plans, compare them with what you did and send them to your Garmin watch."),
   topics:[
    {q:t("Plan erstellen","Create a plan"),a:t("Unter Training → „Neuen Plan erstellen“. Der Coach berücksichtigt Ziel, verfügbare Tage und deine Daten.","Under Training → “Create new plan”. The coach takes your goal, available days and data into account.")},
    {q:t("Workouts auf die Uhr","Workouts to the watch"),a:t("Braucht den Garmin-Login – entweder als Verbindungsart oder als Zusatz-Login neben dem API-Key. Aktiviere den Export unter Einstellungen → Garmin → Training & Kalender.","Needs the Garmin login – either as connection method or as extra login next to the API key. Enable export under Settings → Garmin → Training & calendar.")},
   ],
   links:[{href:"/training",label:t("Zu Training","Open training")},{href:"/settings/garmin",label:t("Workout-Export einrichten","Set up workout export")}]},

  {id:"coach",title:t("AI Coach","AI Coach"),
   intro:t("Dein Coach kennt Ziele, Alltag und – nach deiner Freigabe – deine Daten.","Your coach knows your goals, routine and – with your permission – your data."),
   topics:[
    {q:t("Welche Daten sieht der Coach?","Which data does the coach see?"),a:t("Nur die Bereiche, die du unter „Meine Daten für die KI“ auswählst. Cloud-KI erhält Gesundheitsdaten nur, wenn du das unter Datenschutz erlaubst.","Only the areas you choose under “My data for the AI”. Cloud AI receives health data only if you allow it under Privacy.")},
    {q:t("Gedächtnis","Memory"),a:t("Unter „Dein Coach kennt dich“ legst du Ziele, Alltag und Dinge fest, die der Coach sich merken soll.","Under “Your coach knows you” you set goals, routine and things the coach should remember.")},
   ],
   links:[{href:"/coach",label:t("Zum Coach","Open coach")},{href:"/settings/privacy",label:t("Datenschutz & KI","Privacy & AI")}]},

  {id:"garmin",title:t("Garmin","Garmin"),
   intro:t("Zwei Wege: Garmin-Login (alle Funktionen) oder der offizielle Personal API Key (nur lesen). Beides lässt sich kombinieren.","Two ways: Garmin login (all features) or the official Personal API key (read-only). Both can be combined."),
   topics:[
    {q:t("Login oder API-Key?","Login or API key?"),a:t("Der Login kann alles inklusive Workout-Export, Garmin fragt aber ab und zu neu nach. Der API-Key ist offiziell und stabil, liefert aber keinen Trainingsstatus, keine Readiness und keine Leistungszonen. Mit „Beides“ kommen Daten über den Key und der Login wird nur für den Export benutzt.","The login can do everything including workout export, but Garmin asks again from time to time. The API key is official and stable but delivers no training status, readiness or power zones. With “both”, data comes through the key and the login is used only for export.")},
    {q:t("API-Key erstellen und erneuern","Create and renew the API key"),a:t("Die Schritt-für-Schritt-Anleitung steht direkt im Verbindungsformular. Der Key läuft nach der gewählten Laufzeit ab; 14 Tage vorher erinnert dich die Garmin-Seite. „Key erneuern“ ersetzt ihn ohne Datenverlust.","The step-by-step guide is right in the connection form. The key expires after its lifetime; the Garmin page reminds you 14 days ahead. “Renew key” replaces it without losing data.")},
    {q:t("Historie nachladen","Load history"),a:t("Unter „Historie & Ersteinrichtung“: erst alle Aktivitäten, dann Tagesdaten. Der optimierte Modus ist deutlich schneller; die letzten 90 Tage werden immer vollständig geladen.","Under “History & initial setup”: activities first, then daily data. Optimized mode is much faster; the latest 90 days are always loaded in full.")},
   ],
   links:[{href:"/settings/garmin",label:t("Garmin-Einstellungen","Garmin settings")}]},

  {id:"sparkyfitness",title:t("SparkyFitness","SparkyFitness"),
   intro:t("Lesende Verbindung zu deinem selbst gehosteten SparkyFitness mit Schlaf, Tageswerten, Körperdaten und Trainings inklusive GPS.","Read-only connection to your self-hosted SparkyFitness with sleep, daily values, body data and workouts including GPS."),
   topics:[
    {q:t("Verbinden","Connect"),a:t("Adresse deines SparkyFitness und einen API-Key aus SparkyFitness eintragen. PenguCoach prüft die Berechtigungen sofort.","Enter your SparkyFitness address and an API key from SparkyFitness. PenguCoach checks the permissions right away.")},
    {q:t("Doppelte Trainings?","Duplicate workouts?"),a:t("Dieselbe Einheit aus Garmin und SparkyFitness wird zusammengeführt statt doppelt gezählt.","The same session from Garmin and SparkyFitness is merged instead of counted twice.")},
   ],
   links:[{href:"/settings/sparkyfitness",label:t("SparkyFitness-Einstellungen","SparkyFitness settings")}]},

  {id:"appearance",title:t("Darstellung","Appearance"),
   intro:t("Themes, eigene Farben, App-Icon und Benutzerbild – nur für deinen Account.","Themes, custom colours, app icon and profile picture – for your account only."),
   topics:[
    {q:t("Theme wechseln","Change theme"),a:t("Unter Darstellung eine Kachel wählen, zum Beispiel Night Run, Daylight, Carbon oder Dusk. Im eigenen Theme wählst du Grundstimmung und drei Farben; Kontraste werden automatisch angepasst.","Pick a tile under Appearance, for example Night Run, Daylight, Carbon or Dusk. In the custom theme you choose a mode and three colours; contrast is adjusted automatically.")},
   ],
   links:[{href:"/settings/appearance",label:t("Darstellung öffnen","Open appearance")}]},

  {id:"settings",title:t("Wetter, Karten & Datenschutz","Weather, maps & privacy"),
   intro:t("Weitere persönliche Einstellungen.","More personal settings."),
   topics:[
    {q:t("Wetter","Weather"),a:t("Trainingsort festlegen und die Wetterintegration aktivieren. „Heute“ zeigt dann gute Zeitfenster innerhalb deiner bevorzugten Trainingszeit.","Set your training location and enable the weather integration. Today then shows good windows within your preferred training time.")},
    {q:t("Karten & Straßenansicht","Maps & street view"),a:t("Optional eigener Zugang für Google Street View oder Apple Look Around im Routen-Explorer.","Optional personal access for Google Street View or Apple Look Around in the route explorer.")},
    {q:t("Datenschutz","Privacy"),a:t("Lege fest, ob nur lokale KI genutzt wird oder ob Cloud-KI Gesundheits- und Trainingsdaten erhalten darf.","Decide whether only local AI is used or whether cloud AI may receive health and training data.")},
   ],
   links:[{href:"/settings/weather",label:t("Wetter","Weather")},{href:"/settings/maps",label:t("Karten","Maps")},{href:"/settings/privacy",label:t("Datenschutz","Privacy")}]},

  {id:"updates",title:t("Updates & Version","Updates & version"),
   intro:t("Unten in der Seitenleiste steht deine Version.","Your version is shown at the bottom of the sidebar."),
   topics:[
    {q:t("Nach Updates suchen","Check for updates"),a:t("Klick auf das Kreis-Symbol neben der Version: PenguCoach prüft und zeigt „Aktuell“ oder „Update verfügbar“. Erst ein Klick auf dieses Ergebnis öffnet den Update-Bereich mit den Release Notes.","Click the circle icon next to the version: PenguCoach checks and shows “Up to date” or “Update available”. Only clicking that result opens the update area with the release notes.")},
    {q:t("Hinweis „Update verfügbar“ oben","“Update available” banner at the top"),a:t("Gibt es eine neue Version, erscheint oben auf jeder Seite ein schmaler Hinweis – auch auf Handy und Tablet. Ein Tipp darauf zeigt, was neu ist; mit × blendest du ihn aus, bis die nächste Version erscheint.","When a new version exists, a slim notice appears at the top of every page – on phone and tablet too. Tap it to see what is new; × hides it until the next version arrives.")},
    {q:t("Wer installiert Updates?","Who installs updates?"),a:t("Administratoren unter Admin → System & Updates. Dort stehen auch Sicherungen, Wiederherstellung und „Über PenguCoach“ mit Lizenz.","Administrators under Admin → System & updates. Backups, recovery and “About PenguCoach” with the licence are there too.")},
   ],
   links:[{href:"/settings/updates",label:t("Versionen & Release Notes","Versions & release notes")},{href:"/admin/system#updates",label:t("System & Updates","System & updates"),admin:true}]},

  {id:"admin",title:t("Administration","Administration"),admin:true,
   intro:t("Nur für Administratoren: System, KI-Anbieter und Benutzer.","Administrators only: system, AI providers and users."),
   topics:[
    {q:t("Update installieren","Install an update"),a:t("System & Updates → Updates. PenguCoach zeigt installierte und Zielversion, prüft Voraussetzungen, legt eine Sicherung an und baut die neue Version, während die alte noch läuft. Scheitert etwas, wird automatisch zurückgerollt.","System & updates → Updates. PenguCoach shows installed and target version, checks requirements, creates a backup and builds the new version while the old one keeps running. If something fails, it rolls back automatically.")},
    {q:t("Sicherungen","Backups"),a:t("System & Updates → Sicherungen: verschlüsselt, mit Datenbank, Einstellungen und Daten. Wiederherstellen unter „Wiederherstellung“.","System & updates → Backups: encrypted, with database, settings and data. Restore under “Recovery”.")},
    {q:t("KI-Anbieter und Benutzer","AI providers and users"),a:t("AI Studio verwaltet Anbieter, Modelle und Prompts. Unter Benutzer legst du Konten an und vergibst Rollen.","AI Studio manages providers, models and prompts. Under Users you create accounts and assign roles.")},
   ],
   links:[{href:"/admin/system",label:t("System & Updates","System & updates"),admin:true},{href:"/admin/ai",label:t("AI Studio","AI Studio"),admin:true},{href:"/admin/users",label:t("Benutzer","Users"),admin:true}]},
];

export function helpText(text:Text,lang:Lang){return text[lang]}

/** Sections visible to the current user, optionally filtered by a search term. */
export function filterHelp(query:string,lang:Lang,admin:boolean){
  const q=query.trim().toLowerCase();
  return HELP_SECTIONS.filter(s=>admin||!s.admin).map(s=>{
    if(!q)return s;
    const inSection=[s.title,s.intro].some(x=>x[lang].toLowerCase().includes(q));
    const topics=s.topics.filter(x=>inSection||x.q[lang].toLowerCase().includes(q)||x.a[lang].toLowerCase().includes(q));
    return topics.length||inSection?{...s,topics:inSection?s.topics:topics}:null;
  }).filter((s):s is HelpSection=>!!s);
}
