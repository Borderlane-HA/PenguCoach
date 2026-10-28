# Gemeinsame Datenbasis

PenguCoach funktioniert mit Garmin, SparkyFitness, beiden Verbindungen oder manuellen Datei-/Körperdaten. Es gibt keine Voraussetzung, Garmin zu verbinden. Garmin-spezifische Zonen und Kalenderexporte werden nur angeboten bzw. an die KI übergeben, wenn sie vorhanden sind. Die direkte Withings-Verbindung ist entfernt; historische Messwerte bleiben erhalten.

## Welche Messung gilt?

- Gewicht, Größe und Körperzusammensetzung werden pro Kennzahl nach Messzeit ausgewählt. Eine neuere Messung ersetzt eine ältere, unabhängig davon, ob diese manuell, aus Garmin oder SparkyFitness stammt. Ein neu importierter alter Messwert ist keine neue Messung.
- Bei exakt gleicher Messzeit entscheidet eine stabile Reihenfolge: manuell, Garmin, SparkyFitness. Ein Datum ohne Uhrzeit entspricht dem Tagesbeginn. Neue manuelle Werte von heute bekommen den tatsächlichen Eingabezeitpunkt; alte manuelle 23:59:59-Platzhalter bleiben kompatibel. Zukünftige manuelle Tage werden abgelehnt.
- Profilgrößen ohne verlässlichen Änderungszeitpunkt sind als undatierter Fallback gespeichert und werden nicht bei jeder Synchronisierung künstlich zur neuesten Messung.
- BMI wird aus den aktuell wirksamen Werten für Gewicht und Größe berechnet und als PenguCoach-Berechnung markiert. Die Eingangsquellen bleiben im API-Snapshot nachvollziehbar.
- Bei Tageswerten gewinnt eine neuere verfügbare Beobachtungszeit. Korrekturen derselben Quelle werden übernommen. Wenn bei konkurrierenden Tagesaggregaten kein Zeitvergleich möglich ist, bleibt Garmin der stabile Gleichstandsentscheid; die Summen verschiedener Anbieter werden niemals addiert.
- Fehlende Werte überschreiben keine vorhandenen Werte. Fehlende Messwerte sind nicht null: eine ausdrücklich gemessene Null bei Schritten oder Trinkmenge bleibt dagegen gültig. Ungültige negative/nicht-endliche Messwerte werden verworfen.

## Heute und Gesundheit

Heute zeigt die Werte des aktuellen Tages in der Benutzer-Zeitzone und die letzten bekannten Körperwerte mit Quelle und Messzeit. Ein Schlaf- oder HRV-Datensatz reicht aus, auch wenn kein allgemeiner Tagesdatensatz existiert. Garmin-spezifische leere Body-Battery-/Readiness-Karten werden ausgeblendet. Die Körperkarten sind aktuelle Werte; die Gesundheitskarten im gewählten Zeitraum bleiben Durchschnittswerte aus tatsächlich vorhandenen Messungen. Es gibt keine Ergänzung fehlender Tage mit null.

VO₂max-Aktivitätswerte tragen ihre tatsächliche Quelle. Body Battery ist als Tageshoch beschriftet und verwendet Levels statt Lade-/Entladebeträgen. Nächtliche HRV wird nicht durch einen Wochenschnitt ersetzt.

## Aktivitäten und KI

Die Analyse verwendet die ausgewählte Einheit aus jeder Quelle. Der Zusatzkontext ist wählbar: nur Einheit, Trainingstag, drei oder sieben Tage. Historische Analysen erhalten keine späteren Körpermessungen. Tagesaggregate können Messungen nach der Aktivität enthalten und werden entsprechend im KI-Kontext erklärt. Ohne FIT-Datei stehen nur vorhandene Zusammenfassungen zur Verfügung; keine erfundenen Zeitreihen.

Garmin-/SparkyFitness-Sessions werden anhand Sport, Startzeit, Dauer und Distanz konservativ zugeordnet. Kommt Garmin später hinzu, wird ein eindeutiger SparkyFitness-Treffer unter derselben lokalen Aktivitäts-ID weitergeführt. Mehrdeutige Fälle bleiben getrennt; die Erkennung kann ohne gemeinsame Anbieter-ID keine hundertprozentige Dublettenfreiheit garantieren.

Coach und Training verwenden dieselbe Datenaufbereitung und aufklappbare Auswahl: Aktivitäten, Schlaf/HRV, Erholung/Stress, Alltagsbewegung, Trinkmenge, Körperwerte und Trainingszonen. Die Vorschau zeigt verfügbare Datensätze und Quellen, ohne ein KI-Modell aufzurufen. Abgewählte Kategorien werden aus dem neu aufgebauten Datenkontext entfernt. Bereits besprochene Informationen können Teil einer laufenden Unterhaltung sein; „Neu“ beginnt ohne bisherigen Gesprächsverlauf. Cloud-Freigaben bleiben unverändert verbindlich.

Coach nutzt standardmäßig sieben Tage und erkennt explizite Zeitangaben von 3/7/14/21/28 Tagen. Auch kurze Anschlussfragen erhalten Kontext. Kurze Alltagsfragen sollen eine konkrete kurze Empfehlung mit Begründung liefern; ein mehrtägiger Plan wird nur auf ausdrücklichen Wunsch erzeugt. Modellantworten bleiben vom gewählten Modell abhängig.

Trinkmenge ist dokumentierte Aufnahme, kein Nachweis des Flüssigkeitsbedarfs oder einer Dehydrierung. Tage ohne aufgezeichnetes Training werden nicht als sicher nachgewiesene Ruhetage interpretiert. Ohne Zonen werden keine individuellen Grenzwerte erfunden.

## Bedienung und Aktualisierung

Neun Themes stehen unter Darstellung bereit. Das mobile Menü oben öffnet Verbindungen und Einstellungen; die fünf Hauptbereiche bleiben unten erreichbar. Im Trainingskalender kann eine geöffnete Einheit auch per Tagesauswahl verschoben werden. Anpassungen sind Browser-Entwürfe, werden auf diesem Gerät gespeichert und verändern nicht den ursprünglichen KI-Plan.

Für ein Update von alpha.37 das `github-web-update` entpacken und dessen Inhalt in das Repository-Hauptverzeichnis hochladen. Danach den vorhandenen `pengucoach-update`-Ablauf ausführen (Docker: neu bauen, API-Migration ausführen lassen, Worker und Scheduler ebenfalls neu starten). Keine manuelle Dateilöschung ist erforderlich. Anschließend die verwendeten Quellen einmal synchronisieren, damit korrigierte importierte Werte neu eingelesen werden. Nur tatsächlich erneut synchronisierte historische Tage werden neu normalisiert.

## Prüfung und Grenzen

Automatisierte Backendtests prüfen reale Datenbankabfragen mit einer isolierten SQLite-Testdatenbank; die produktive Datenbank bleibt PostgreSQL. Die bestehende CI prüft die PostgreSQL-Migrationskette. Desktop- und mobile Chromium-Ansichten wurden mit simulierten API-Daten geprüft (1440 und 390 Pixel), einschließlich Datenauswahl, neun Themes, Menü und Kalender-Verschiebung. Ein echter iPhone/Safari-Test und Live-Synchronisation gegen persönliche Garmin-/SparkyFitness-Konten waren hier nicht möglich.
