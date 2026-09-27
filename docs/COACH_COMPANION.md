# Persönlicher Coach

## Einstieg

1. Unter **Coach → Dein Coach kennt dich** Ziel, optionales Zieldatum, Sportarten, Trainingstage, typische Dauer, Ausrüstung, Einschränkungen und Zwischenziele eintragen.
2. Unter **Heute** bei Bedarf Energie, Muskelkater, verfügbare Zeit und Beschwerden für den aktuellen Tag ergänzen.
3. Im Chat eine Frage stellen. Das aktuelle Gespräch wird nach erneutem Öffnen wieder geladen; **Verlauf** zeigt auch ältere Gespräche. **Neu** startet ein separates Gespräch.
4. Im Training mit **Mein Profil als Grundlage übernehmen** die Planvorgaben vorbelegen und vor der Generierung prüfen. Persönliche Angaben können pro Anfrage ausgeschlossen werden.
5. Den Kalender mit einem Montag als Startdatum speichern. Dieser Stand ist für den Coach und auf anderen Geräten verfügbar. Änderungen im Kalender bleiben bis **Kalender speichern** ein Entwurf.

## Gedächtnis und Gespräche

Das Profil und ausdrücklich bestätigte Merksätze sind dauerhaft, benutzerbezogen und bearbeiten/löschen lässt sich beides in der Oberfläche. Unter eigenen Chatnachrichten öffnet **Als Merksatz speichern** einen überprüfbaren Entwurf. Der Coach speichert keine vermuteten Eigenschaften automatisch und kann ohne Bedienaktion keine Kalenderänderungen durchführen.

Bis zu 30 Merksätze mit insgesamt 6.000 Zeichen sind möglich. Das aktive Modellkontextfenster begrenzt, wie viele Details tatsächlich in eine Anfrage passen. Profil, Merksätze und Gesprächsauszüge erhalten einen eigenen begrenzten Anteil am Kontext. Aktuelle ausdrückliche Korrekturen im Gespräch haben Vorrang.

Längere Gespräche werden durch **gekürzte Originalauszüge früherer Nutzernachrichten** ergänzt; dies ist eine deterministische Verdichtung, keine zusätzliche KI-Zusammenfassung. Die vollständigen Nachrichten bleiben im Verlauf. Sehr lange Verläufe lassen sich in Seiten von 200 Nachrichten nachladen. Beim Modell werden zusätzlich die letzten bis zu zwölf Nachrichten innerhalb des verfügbaren Eingabebudgets berücksichtigt.

Profil, Gespräche und Merksätze sind getrennte Daten. Wer Angaben vollständig entfernen möchte, löscht gegebenenfalls auch das Gespräch, in dem sie vorkommen. Beim Löschen eines Gesprächs werden dessen Nachrichten und ab Alpha.39 damit verknüpfte Coach-Ausführungen entfernt; ältere, nicht verknüpfte AI-Runs bleiben über die bisherige Verwaltung löschbar.

## Tagesbriefing und Wochenrückblick

Das Tagesbriefing funktioniert ohne Modellaufruf. Es zeigt erfasste Aktivität, die nächste gespeicherte Planeinheit und verfügbare Messwerte mit Quelle und Datum. Transparente Regeln berücksichtigen heutige Selbstauskunft, kurze erfasste Schlafdauer, mehrere aktive Tage und kürzlich als zu schwer bewertete Einheiten. Dies ist kein medizinischer Bereitschaftsscore. Fehlende Daten beweisen weder Inaktivität noch Erholung.

Der Check-in gilt nur für das Datum in der Benutzerzeitzone. Der Wochenvergleich stellt die letzten sieben Kalendertage einschließlich heute den sieben Tagen davor gegenüber. **Mit Coach einordnen** öffnet eine passende Frage mit explizitem 14-Tage-Kontext. Der Coach kann daraus eine individuelle Empfehlung und zielbezogene Zwischenziele entwickeln. Übernommene Zwischenziele werden im Profil gepflegt.

## Planabgleich und Änderungen

**Dein Plan im Alltag** vergleicht gespeicherte Planeinheiten mit Aktivitäten gleicher Sportart am gleichen lokalen Tag. Nur eindeutige Paarungen werden automatisch zugeordnet; Aktivitäten werden nicht mehreren Einheiten zugeordnet. Angezeigt werden geplante/tatsächliche Dauer, vorhandener Durchschnittspuls und subjektives Feedback. Aus der Dauer allein wird keine Intensität abgeleitet. Für Details die Aktivität öffnen.

Fehlende Einträge werden als „Keine passende Aktivität“ bezeichnet und können auch noch nicht synchronisierte Daten bedeuten. Vorschläge verschieben eine Einheit auf einen freien passenden Tag innerhalb des Plans oder ersetzen eine Einheit durch eine optionale lockere Alternative. Verfügbare Trainingstage werden berücksichtigt. Vorher/Nachher wird vor dem Speichern angezeigt. Ein veralteter Kalenderstand muss neu geladen werden. Bereits nach Garmin exportierte Einheiten sind geschützt.

Coach-Antworten können über **In Kalender übernehmen** als einzelne Einheit gespeichert werden. Datum, Sportart, Name und Dauer werden vorher vom Nutzer festgelegt. Der Text wird als Notiz übernommen. Es erfolgt kein automatischer Garmin-Export; für einen strukturierten Garmin-Export müssen gegebenenfalls zunächst Trainingsschritte im Kalender ergänzt werden.

## Datenschutz und Datenwahl

Die bestehende Freigabe für lokale/Cloud-KI gilt auch für persönliche Angaben. Der Schalter **Mein Profil** im Chat bzw. **Profil, Merksätze & Feedback einbeziehen** im Training gilt für die jeweilige Anfrage. Der Profilschalter deaktiviert persönlichen Kontext generell. Die bestehenden Kategorien begrenzen Trainings- und Erholungsdaten; persönliche Angaben bleiben eine separat auswählbare Kategorie. Feedback und Planabgleich folgen dem gewählten Zeitraum. Zukünftige Einheiten sind ausdrücklich als Planung gekennzeichnet.

## Chat und Ausgabegrenzen

Sprechblasen wachsen mit ihrem Inhalt. Lokale sichtbare Antwortteile erscheinen während der Generierung. Ollama-Anfragen senden `think: false`, damit unterstützte Modelle das Ausgabelimit nicht vor einer sichtbaren Antwort durch Denken verbrauchen. Benutzerdefinierte Modell-Templates können das Verhalten beeinflussen.

Die Abschlusserkennung hat Vorrang: `stop`/`end_turn` gilt als regulärer Abschluss, auch wenn die gemeldete Tokenzahl das Limit erreicht. `length`/`max_tokens` wird als tatsächlicher Abbruch markiert; falls kein Abschlussgrund vorliegt, dient die Tokenzahl als Rückfallprüfung. Leere oder unvollständige Streams werden als Fehler behandelt und nicht als erfolgreiche leere Coach-Antwort gespeichert. Es gibt keine versteckten kostenpflichtigen Wiederholungen oder automatische Limiterhöhung.

Die Eingabereserve berücksichtigt die Länge der System-/Aufgabenanweisungen. Datenkontext bleibt begrenztes gültiges JSON; die Tokenrechnung ist eine vorsichtige Schätzung und kein modellgenauer Tokenizer.

## Update

Das normale `pengucoach-update` führt Migration `0011_coach_companion` aus. Sie ergänzt Gesprächsmetadaten und Tabellen für Profil, Merksätze, Check-ins, Feedback und Kalender. Bestehende Gesundheitsdaten und Gespräche bleiben erhalten. Withings bleibt entfernt.

## Validierung

Die Release-Prüfung umfasst 132 Python-Tests, Ruff, den Next.js-Produktionsbuild sowie Browserabläufe mit simulierten API-Antworten bei 1440 und 390 Pixel Breite. Geprüft wurden unter anderem Chat-Wiederaufnahme, kompakte erste Sprechblase, Merksätze, Tages-Check-in, Kalender speichern und die direkte Kalenderübernahme. Datenbankfunktionen werden zusätzlich mit einer isolierten Testdatenbank geprüft; das PostgreSQL-Migrationsskript wurde als SQL erzeugt. Kein Live-Test gegen persönliche Garmin-/SparkyFitness-Konten, das konkrete lokale Modell oder einen echten iPhone/Safari-Browser.
