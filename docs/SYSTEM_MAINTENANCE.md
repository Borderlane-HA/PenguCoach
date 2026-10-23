# System & Wartung / System maintenance (Alpha.73–76)

Admin → **System & Wartung** bündelt **Updates**, **Sicherungen** und **Wiederherstellung**. Der kleine Versions-/Updatehinweis öffnet diesen Bereich. Normale Benutzer sehen eine reine Informationsseite unter Einstellungen → Updates; dort stehen Updateprüfung und Release Notes ohne Wartungsaktionen. Unter „Über PenguCoach“ bleibt ein Link dorthin. Die automatische GitHub-Prüfung bleibt sechs Stunden gecacht; „Jetzt prüfen“ ist im Updatebereich verfügbar.

## Update auf Alpha.75: Release anlegen

Ab Alpha.75 installiert die Wartung **das neueste veröffentlichte Release** (Git-Tag wie `v0.1.0-alpha.75`), nicht mehr den aktuellen Stand von `main`. Für jede neue Version deshalb nach dem Hochladen auf GitHub ein Release mit passendem Tag veröffentlichen. Ohne Tag meldet die Updateprüfung „kein passendes Release gefunden“ und es wird nichts verändert.

Der erste Wechsel von Alpha.74 auf Alpha.75 läuft noch mit dem Alpha.74-Wartungsdienst und lädt dabei wie bisher `main`. Danach startet der neue Dienst und holt die Systemschritte von Alpha.75 (Shell-Befehle, nginx, Build-Cache) automatisch einmal nach. Ein zusätzlicher Befehl ist nicht nötig.

Wer bewusst weiter dem Branch folgen möchte, setzt in `/etc/pengucoach-maintenance.json` (Docker: `/state/config.json` im Wartungscontainer) `"update_source": "branch"`.

## Automatische Einrichtung beim normalen Update

Die Dateien dieser Version zuerst wie gewohnt im Git-Repository veröffentlichen und auf dem Host aktualisieren. **Ein zusätzlicher Aktivierungsbefehl ist bei der Standardinstallation nicht erforderlich.**

**LXC – innerhalb des PenguCoach-Containers als root:**

```bash
pengucoach-update
```

Auch der erste Wechsel von Alpha.72 und älteren Versionen ist abgedeckt: Deren bereits laufender Updater führt nach dem Git-Update die vorhandene Datenbankaktualisierung aus. Nach erfolgreichem Abschluss dieses Schritts erkennt ein gezielter Übergang die verwaltete native Root-Installation und richtet den unabhängigen Dienst ein. Dies läuft nur beim Online-CLI-Befehl `upgrade` auf der lokalen Live-Datenbank `pengucoach`; Offline-SQL-Ausgaben, andere Datenbanken, Restore-Vorprüfungen und unprivilegierte Prozesse lösen keine Hosteinrichtung aus. Die neu installierte Shell-Version prüft die Einrichtung zusätzlich direkt beim Aufruf und repariert einen fehlenden Dienst auch dann, wenn der Git-Stand bereits aktuell ist.

**Docker – auf dem Linux-Dockerhost im Projektverzeichnis:**

```bash
docker compose up -d --build
```

Die mitgelieferte Compose-Datei enthält den kurzlebigen Dienst `maintenance-setup`. Er richtet den unabhängigen Wartungscontainer automatisch ein und prüft dessen Erreichbarkeit. Dabei verwendet er die tatsächlich verwendeten Compose-Projekt-/Dateilabels und benannten Daten-/Kontrollsocket-Volumes. Bei eigenen Compose-Dateien dieselben `COMPOSE_PROJECT_NAME`-/`COMPOSE_FILE`-Einstellungen wie bisher verwenden; wird ausschließlich eine eigene Datei ohne den neuen Setup-Dienst gestartet, ist diese Ergänzung entsprechend zu übernehmen. Unterstützt wird die mitgelieferte Linux-Compose-Struktur mit lokaler Docker-Engine. Ein Remote-Dockerdaemon oder eine andere Datenbank-/Redis-Topologie wird nicht automatisch umgebaut.

Nur die Wartungshelfer erhalten `/var/run/docker.sock`; API, Worker, Scheduler und Webserver erhalten ihn nicht. `maintenance-setup` veröffentlicht keinen Port und beendet sich nach der Einrichtung. Der eigentliche Container `pengucoach-maintenance-<Compose-Projekt>` gehört weiterhin nicht zum App-Stack. WebUI-Updates bauen und starten nur die Anwendungsdienste; der Wartungscontainer läuft dabei weiter. Private Sicherungen und Auftragsdaten liegen im separaten Volume `<Compose-Projekt>_maintenance_state`.

Eine wiederholte Einrichtung lässt einen unveränderten, erreichbaren Dienst laufen. Ein laufender Wartungsauftrag wird über dieselbe Sperre erkannt; die Ersetzung des Helfers wird dann verschoben. Frische native Installationen nutzen denselben automatischen, geprüften Einrichtungsweg.

### Falls die automatische Einrichtung scheitert

Die Anwendung bleibt erreichbar. Unter Admin → System & Wartung erscheint **„Automatische Einrichtung fehlgeschlagen“** mit Prüf-/Reparaturhinweisen. Eine fehlgeschlagene Zusatzeinrichtung macht eine bereits erfolgreiche Datenbankaktualisierung nicht rückgängig. Es werden nur sichere Statuscodes angezeigt, keine Umgebungsvariablen oder Zugangsdaten.

LXC-Protokoll prüfen und den normalen Updater erneut ausführen:

```bash
tail -n 100 /var/log/pengucoach-maintenance-setup.log
pengucoach-update
```

Docker-Protokoll und gezielter erneuter Einrichtungsversuch:

```bash
docker compose logs maintenance-setup
docker compose run --rm --no-deps maintenance-setup
```

Der bisherige direkte Setup-Befehl `bash install/maintenance/install.sh native|docker <Projektpfad>` bleibt als Administrator-Reparaturwerkzeug erhalten. Er gehört nicht mehr zum normalen Updateablauf.

## Anmeldung während der Sicherung (Alpha.74)

Eine normale Sicherung ändert den Anmeldeschlüssel nicht. Während die schreibenden App-Dienste kurz angehalten sind, bleiben die bereits geprüfte Anmeldung und die angezeigten Daten im Browser erhalten. Fehlgeschlagene Sitzungsprüfungen wegen HTTP 5xx, Verbindungsfehlern oder Timeouts werden erneut versucht. Bei einem Neuladen während dieser Unterbrechung erscheint eine Verbindungsanzeige mit erneuter Prüfung. Ein tatsächlich ungültiger oder abgelaufener Zugang (HTTP 401) führt weiterhin zur Anmeldung; auch die beabsichtigte Abmeldung nach einer Wiederherstellung bleibt erhalten.

## Updates

1. Unter Updates zeigt der Bereich die installierte Version und das neueste passende Release („v0.1.0-alpha.74 → v0.1.0-alpha.75 verfügbar“). „Erneut prüfen“ fragt GitHub sofort ab.
2. „Update vorbereiten“ wählen; der Dialog nennt die Zielversion. `UPDATE` bestätigen.
3. Der Dienst holt das Release in sein eigenes Root-Checkout, prüft den freien Speicher, aktiviert den Wartungsmodus und wartet laufende Hintergrundaufgaben ab, hält die schreibenden Dienste an, erzeugt eine lokale Vollsicherung, baut die Anwendung, führt Migrationen und offene Systemschritte aus und prüft API/Datenbank und Webserver.

Es gelten dieselben Versionsregeln wie beim Updatehinweis: Stabile Installationen folgen nur stabilen Releases, Alpha-Installationen allen veröffentlichten Releases. Ein Stand, der bereits neuer ist als das Release oder es enthält (zum Beispiel ein Checkout von `main` nach dem Release), wird nie zurückgesetzt; das Update endet dann ohne Änderung.

Die Updatefunktion benötigt ein Git-Checkout als Installationsverzeichnis; bei einem direkt entpackten Quell-ZIP bleiben Backup/Restore nutzbar, die Updateaktion zeigt den fehlenden Git-Stand an.

Lokale Änderungen an versionierten Quelldateien werden ersetzt. Nicht versionierte `.env`-, `.env.maintenance`- und Compose-Konfigurationsdateien werden beim Aufräumen geschützt. LXC-Builds laufen bei gestopptem Webdienst mit begrenztem Node-Heap und eigenem Cache unter `/var/cache/pengucoach-build`.

### Bauen bei laufender App und Release-Verzeichnisse (Alpha.76)

**LXC:** Jede Version bekommt ein eigenes Verzeichnis `/opt/pengucoach-releases/<commit>`. Darin entstehen Python-Umgebung und Web-Build, **während die bisherige Version weiterläuft**. Erst danach folgen Wartungsmodus, Sicherheitskopie, Anhalten, Umschalten von `/opt/pengucoach` (ein Link auf das aktive Release), Migration, Systemschritte und Start. Die systemd-Units und nginx verwenden weiterhin `/opt/pengucoach`.

- Scheitert der Build, wird nichts angehalten und kein Wartungsmodus gesetzt; das unfertige Verzeichnis wird entfernt.
- Scheitert etwas nach dem Umschalten, zeigt der Link zurück auf die vorherige Version und die Datenbank wird aus der Sicherheitskopie zurückgespielt – ohne die vorherige Version neu zu bauen.
- Beim ersten Update mit diesem Verfahren wird das bisherige Verzeichnis unverändert nach `/opt/pengucoach-releases/legacy-<commit>` verschoben.
- Aufbewahrt werden das aktive und das vorherige Release (`keep_releases`). Ein Release belegt etwa so viel Platz wie die bisherige Installation (Python-Umgebung, Node-Module, Web-Build); die Platzprüfung berücksichtigt das vor dem Start.
- Wer lieber im bestehenden Verzeichnis aktualisiert, setzt `"release_layout": false`.
- `pengucoach-status` zeigt das aktive Release. Der alte Shell-Updater ohne Wartungsdienst verändert eine Installation mit Release-Verzeichnissen nicht.

Das Verfahren greift ab dem ersten Update **nach** Alpha.76, denn das Update auf Alpha.76 führt noch der Alpha.75-Wartungsdienst aus.

**Hinweis für Alpha.76/77:** Diese Versionen legten `/opt/pengucoach-releases` wegen der Umask des Wartungsdiensts nur für root lesbar an; der Build brach dann sofort mit `MAINTENANCE_COMMAND_FAILED:python3:1` ab (ohne Änderung an der laufenden App). Vor dem Update auf Alpha.78 einmalig im LXC ausführen:

```bash
[ -d /opt/pengucoach-releases ] && chmod 755 /opt/pengucoach-releases
```

Ab Alpha.78 setzt der Wartungsdienst die Rechte selbst.

**Docker:** Die neuen Images werden gebaut, bevor die Dienste angehalten werden. Scheitert der Build, werden Quellstand und Image-Tags zurückgesetzt; die laufenden Container bleiben unberührt.

### Voraussetzungen einer Version

Jedes Release kann in `install/release-requirements.json` festlegen, ab welcher Version ein direktes Update möglich ist (`min_upgrade_from`) und welche Docker-Compose-, Python- bzw. Node.js-Version nötig ist. Der Updatebereich zeigt die Prüfung vor dem Start; nicht erfüllte Voraussetzungen sperren das Update mit einem klaren Hinweis. Beim Update selbst wird dieselbe Datei aus dem geprüften Release-Checkout gelesen, bevor irgendetwas verändert wird.

### Systemschritte aus dem Repository

Änderungen am Host, die ein Release braucht (Shell-Befehle, nginx, systemd), liegen als nummerierte Skripte in `install/host-steps/` (`NNN-name.native.sh`, `.docker.sh` oder `.all.sh`). Der Wartungsdienst führt offene Schritte nach Build und Migration und vor dem Start der Dienste als root aus seinem eigenen Release-Checkout aus, nie aus dem Anwendungsverzeichnis. Jeder Schritt läuft genau einmal; der Stand liegt in `host-steps.json` im privaten Wartungsverzeichnis. Scheitert ein Schritt, werden Programm, Datenbank und Daten zurückgesetzt und der Schritt beim nächsten Update erneut versucht. Hoständerungen eines Schritts selbst werden nicht zurückgedreht; Schritte müssen deshalb wiederholbar und mit der Vorversion verträglich sein. Hinweise für neue Schritte stehen in `install/host-steps/README.md`.

### Wartungsmodus

Vor Update, Wiederherstellung und Vollsicherung setzt der Dienst einen kurzlebigen Wartungsmodus. Die App nimmt dann keine neuen Änderungen an (Hinweis „Gerade läuft eine Systemwartung“); Anmelden, das Abbrechen laufender Aufträge und dieser Wartungsbereich bleiben nutzbar. Der Scheduler plant keine neuen Synchronisierungen. Anschließend wartet der Dienst auf alle laufenden und bereits vorgemerkten Celery-Aufgaben – unabhängig davon, ob es Coach-, Analyse-, Garmin-, SparkyFitness- oder FIT-Aufgaben sind – standardmäßig bis zu 10 Minuten (`drain_timeout`). Danach werden verbleibende Aufgaben beim Anhalten beendet. Laufende Garmin-Workout-Exporte oder -Bereinigungen werden nie abgeschnitten: In diesem Fall startet die Wartung nicht und meldet den Grund. Ist Redis gestört, blockiert der Wartungsmodus den normalen Betrieb nicht.

Fehler vor Abschluss lösen die Wiederherstellung von Quellstand/Images, Datenbank und Umgebung aus. Der Status bleibt außerhalb der App-Datenbank erhalten. Bei einer Verbindungsunterbrechung läuft der Auftrag weiter; die Seite prüft erneut. Bei einem erfolgreichen Restore werden Benutzer abgemeldet und müssen sich neu anmelden. Ein Auftrag darf während des eigentlichen Umbaus nicht per WebUI abgebrochen werden.

Eine zweite Wartungsaktion wird unabhängig vom verwendeten Zugang gesperrt. Die vorhandenen Shell-Kommandos bleiben für einen Administrator auch bei nicht erreichbarer WebUI nutzbar.

## Was eine Vollsicherung enthält

- PostgreSQL-Dump mit allen Benutzern, Einstellungen, LLM-Anbietern/-Modellen und deren verschlüsselten Zugangsdaten, benutzerspezifischen Prompts, Coach-Verläufen, Trainingsplänen und Analysen.
- Effektive App-Umgebung einschließlich `PENGUCOACH_ENCRYPTION_KEY`. Ohne diesen Schlüssel wären gesicherte API-Zugänge und andere verschlüsselte Inhalte auf einem neuen System nicht lesbar.
- Die Anwendungsdaten im Datenverzeichnis: `fit` (Original-FIT-Dateien), `parquet` (Telemetrie), `user-assets` (Avatare/App-Icons) und `exports`.

Andere Inhalte des Datenverzeichnisses – etwa Dateien des Dienstbenutzers oder npm-/pip-Caches – sind nicht Teil der Sicherung und werden bei einer Wiederherstellung nicht verändert. Sicherungen aus Alpha.73/74 bleiben lesbar; daraus werden ebenfalls nur diese Anwendungsdaten übernommen.

Sicherungen sichern sich nicht rekursiv selbst. Redis-Warteschlangen und Celerybeat-Laufzeitdateien werden nicht wieder eingespielt; nach Restore werden alte Aufträge als beendet markiert und Warteschlangen verworfen. Gespeicherte Antworten und Fortsetzungs-Checkpoints bleiben erhalten. Die vollständigen Anwendungsdaten liegen in Datenbank und Datenverzeichnis. Docker-Images, Betriebssystem, externe Dienste, Reverse-Proxy-/TLS-Konfiguration und individuelle Host-/Compose-Dateien sind keine Bestandteile dieses App-Backups. Ziel-Datenbank, Redis, Datenpfad und die explizite Zieladresse bleiben beim Restore erhalten.

Unterstützt werden die von der Standardinstallation verwaltete lokale PostgreSQL-Datenbank `pengucoach` auf Port 5432 und Redis-Datenbank 0 auf Port 6379. Bei abweichender Infrastruktur stoppt die Aktion vor der Änderung. Eine Sicherung wird in einem Durchgang geschrieben (Dateien → tar → gzip → Verschlüsselung). Außer dem Datenbank-Dump entsteht keine unverschlüsselte Kopie; Prüfen und Exportieren entpacken nichts auf die Platte, eine Wiederherstellung entpackt einmal und verschiebt die Dateien danach an ihren Platz.

## Speicherplatz und Aufbewahrung

Vor jeder Aktion schätzt der Dienst den Platzbedarf (Datenbank plus Anwendungsdaten) und bricht ab, **bevor** ein Dienst angehalten wird, wenn danach weniger als die Reserve frei bliebe (`min_free_bytes`, Standard 1 GiB). Während des Schreibens stoppt eine zweite Prüfung, bevor der Datenträger vollläuft.

Von den automatischen Sicherheitskopien vor Updates und Wiederherstellungen bleiben die neuesten drei erhalten (`keep_automatic_backups`). Ältere werden nach einer erfolgreichen Aktion entfernt. Eigene Sicherungen aus der WebUI, Shell-Sicherungen, hochgeladene und exportierte Sicherungen sowie alle Sicherungen von vor Alpha.75 werden nie automatisch gelöscht. Der Bereich Sicherungen zeigt belegten und freien Speicher.

## Passwortgeschützt oder lokal gesichert

**WebUI-Vollbackup:** mindestens 12 Zeichen, zweimal eingeben, danach die `.pcbackup`-Datei herunterladen. Das Passwort separat aufbewahren. Es wird weder im Auftragsprotokoll noch im Browserspeicher gespeichert. Ohne Passwort kann eine portable Sicherung nicht entschlüsselt werden.

**Automatische Sicherung vor Update/Restore** und `pengucoach-backup` ohne Zusatzparameter: mit dem privaten Schlüssel des Wartungsdiensts verschlüsselte lokale Sicherung. In der Liste als „Lokal gesichert“ markiert. Für einen anderen Host zuerst **„Mit Passwort exportieren“** wählen und den erzeugten portablen Export herunterladen. Nur die lokale Datei ohne deren privaten Dienstschlüssel reicht für einen neuen Host nicht aus.

Das Archiv verwendet AES-256-GCM in authentifizierten 1-MiB-Blöcken und PBKDF2-SHA256 mit zufälligem Salt. Ein authentifizierter Abschluss erkennt abgeschnittene Dateien. Vor einem Restore werden Dateiliste, Größen, Hashes und zulässige Pfade geprüft; Symlinks, Spezialdateien und Pfadtraversierungen werden abgelehnt. Uploads erfolgen in kleinen, bei verloren gegangener Antwort erneut prüfbaren Blöcken; die Obergrenze beträgt 100 GiB. Ein Upload verfällt 24 Stunden nach dem zuletzt empfangenen Block.

## Auf einem neuen System wiederherstellen

1. Dieselbe oder eine kompatible neuere PenguCoach-Version installieren und das erste Administratorkonto anlegen. Der Wartungsdienst wird automatisch eingerichtet.
2. Unter Wiederherstellung die portable `.pcbackup` hochladen und das Backup-Passwort eingeben.
3. **„Sicherung prüfen“** starten. Erst nach erfolgreicher Prüfung wird die Wiederherstellung freigegeben.
4. „Wiederherstellung vorbereiten“ wählen und `WIEDERHERSTELLEN` bestätigen. Die Daten aller Benutzer werden ersetzt.
5. Der Dienst stellt den Dump zunächst in einer separaten Datenbank wieder her und prüft die Migrationen. Erst danach hält er die App an, sichert den aktuellen Stand und ersetzt Datenbank und Dateien.
6. Anschließend mit einem Benutzerkonto **aus der Sicherung** anmelden. Der Anmeldeschlüssel wird erneuert; Sitzungen von vor dem Restore gelten nicht weiter.

### Eigene Umgebungsdateien bleiben unverändert

Eine Wiederherstellung bearbeitet weder `/etc/pengucoach/pengucoach.env` noch die Docker-`.env`. Sie schreibt nur den Verschlüsselungsschlüssel aus der Sicherung und einen neuen Anmeldeschlüssel in eine eigene Wartungsdatei, die nach der Hauptdatei geladen wird und deren Werte überschreibt:

- LXC: `/etc/pengucoach/pengucoach.managed.env`, eingebunden über systemd-Drop-ins `pengucoach-{api,worker,scheduler}.service.d/10-pengucoach-maintenance-env.conf` (legt der Dienst bei Bedarf selbst an).
- Docker: `.env.maintenance` im Projektverzeichnis, eingebunden als optionale `env_file` in der mitgelieferten Compose-Datei (Docker Compose 2.24 oder neuer). Eigene Compose-Dateien müssen diesen Eintrag ebenfalls enthalten.

Vor dem Start prüft der Dienst, dass API, Worker und Scheduler die Datei tatsächlich laden; sonst wird die Wiederherstellung zurückgesetzt. Diese Datei nicht bearbeiten oder löschen – ohne sie wären die wiederhergestellten Zugangsdaten nicht mehr lesbar. Andere Einstellungen der Sicherung (z. B. Zeitlimits) werden nicht übernommen; es gelten die Einstellungen des Zielsystems. Updates schreiben keine Umgebungsdatei mehr.

Eine Sicherung einer neueren, inkompatiblen Datenbank kann bei der Vorprüfung scheitern. Dann bleibt die aktive Installation unverändert. Bestehende Sicherungsverzeichnisse aus Versionen vor Alpha.73 bleiben erhalten, werden aber nicht in `.pcbackup` umgewandelt oder von dieser Oberfläche eingelesen.

## Shell und Wiederanlauf

Die gewohnten nativen Befehle bleiben:

```bash
pengucoach-update
pengucoach-backup
pengucoach-maintenance status
```

`pengucoach-backup` gibt nun den Pfad einer verschlüsselten lokalen `.pcbackup` aus. Für ein portables Backup ein privates Passwortfile anlegen und verwenden:

```bash
pengucoach-maintenance backup --password-file /root/backup-passwort
pengucoach-maintenance inspect <Backup-ID> --password-file /root/backup-passwort
pengucoach-maintenance restore <Backup-ID> --password-file /root/backup-passwort
pengucoach-maintenance export <lokale-Backup-ID> --password-file /root/backup-passwort
```

Passwörter stehen nicht in Kommandoargumenten. Ohne Passwortdatei fragen `inspect`, `restore` und `export` interaktiv nach dem Passwort. Für eine lokale automatische Sicherung bei `inspect`/`restore` leer lassen; `export` fragt nach dem neuen Exportpasswort. Shell-Restore ist eine ausdrückliche Administratoraktion und benötigt keine zusätzliche WebUI-Bestätigung.

Bei Docker bleiben `docker compose pull/build/up` wie gewohnt nutzbar. Die entsprechenden Wartungsbefehle laufen im Helfer, dessen Namen das Setup ausgibt:

```bash
docker exec -it pengucoach-maintenance-<Compose-Projekt> python3 -m pengucoach.maintenance.cli --config /state/config.json status
docker exec -it pengucoach-maintenance-<Compose-Projekt> python3 -m pengucoach.maintenance.cli --config /state/config.json backup
```

Die weiteren Operationen heißen dort ebenfalls `inspect`, `export`, `restore` und `recover`. Ein `--password-file` muss innerhalb dieses Containers verfügbar sein. Der Host-Docker-Socket wird dafür niemals an die App durchgereicht.

Nach einem Prozess-/Hostneustart prüft der Helfer sein Transaktionsjournal und versucht einen unterbrochenen Umbau zurückzusetzen. Bei bereits bestätigtem Abschluss räumt er nur die alten Daten auf. Schlägt die Rücksicherung selbst fehl, bleiben Arbeitsdaten und Journal erhalten und weitere Änderungen werden gesperrt. Hostseitig prüfen:

```bash
journalctl -u pengucoach-maintenance --no-pager -n 100
pengucoach-maintenance status
pengucoach-maintenance recover
```

Die Wiederherstellung lässt sich auch unter Admin → System & Wartung mit **„Wiederherstellung ausführen“** starten. Fehlt zu einer gesperrten Aktion das Journal, wird die Sperre aufgehoben, sobald die Anwendung wieder startet und antwortet; sonst bleibt sie bestehen.

Bei Docker `docker logs <Helfername>` und die CLI im Helfer nutzen. `recover` verwendet dieselbe Sperre und läuft nicht parallel zu einem aktiven Auftrag. Die WebUI zeigt nur feste Fehlercodes und Ablaufmeldungen, keine Passwörter, rohen Datenbankausgaben oder Providerantworten.

## Einstellungen des Wartungsdiensts

In `/etc/pengucoach-maintenance.json` (Docker: `/state/config.json` im Wartungscontainer; bleibt bei erneuter Einrichtung erhalten). Nach einer Änderung den Dienst neu starten (`systemctl restart pengucoach-maintenance` bzw. `docker restart <Helfername>`).

| Schlüssel | Standard | Bedeutung |
|---|---|---|
| `update_source` | `release` | `release`: neuestes passendes Release-Tag; `branch`: Stand von `branch` |
| `branch` | `main` | Branch für `update_source: branch` |
| `keep_automatic_backups` | `3` | Anzahl aufbewahrter Sicherheitskopien vor Update/Restore |
| `min_free_bytes` | `1073741824` | Freie Reserve, die nach einer Sicherung bleiben muss |
| `drain_timeout` | `600` | Sekunden, die auf laufende Hintergrundaufgaben gewartet wird |
| `release_layout` | `true` | LXC: Release-Verzeichnisse mit Bauen bei laufender App |
| `keep_releases` | `2` | Aufbewahrte Release-Verzeichnisse (aktiv + vorheriges) |

## Prüfung von Alpha.76

Automatisiert geprüft: Bauen vor dem Anhalten (nativ und Docker), Verschieben des bisherigen Verzeichnisses und atomares Umschalten des Links mit einem echten Git-Export, Zurückschalten bei Fehlern in Migration, Systemschritt und Erreichbarkeitsprüfung ohne Neubau, Wiederanlauf nach einem Abbruch nach dem Umschalten, Aufbewahrung der Releases, Build-Fehler ohne Anhalten und ohne Sicherheitskopie, Voraussetzungsprüfung (Zwischenversion, Docker Compose, Python, Node.js) vor jeder Änderung und Vorschau der Voraussetzungen. Ein realer LXC- bzw. Docker-Host stand nicht zur Verfügung; das erste Update nach Alpha.76 deshalb zuerst auf einer Testinstallation ausführen.

## Prüfung von Alpha.75

Automatisiert geprüft: Auswahl des Release-Tags gegen ein echtes lokales Git-Repository (unveröffentlichter `main`-Stand wird nicht installiert, kein Zurücksetzen eines neueren Stands), Systemschritte (Reihenfolge, Bereich, einmalige Ausführung, Rollback bei Fehler, nginx-Schritt mit simulierten Befehlen), Inhalt und Streaming der Sicherung ohne Klartextkopie, Wiederherstellung einer Alpha.73-Sicherung, Export ohne Entpacken, Beschädigungen, Aufbewahrung, Platzprüfung vor dem Anhalten, Wartungsmodus in API und Scheduler, Abwarten und Schutz von Garmin-Exporten, getrennte Wartungs-Umgebungsdatei inkl. Ladeprüfung, systemd-Drop-ins, Build-Cache, Wiederherstellung über die WebUI und Shell-Fehlermeldungen. Ein realer Proxmox-LXC, Dockerdaemon, PostgreSQL- und Redis-Dienst stehen in der Entwicklungsumgebung nicht zur Verfügung. Das erste Update auf Alpha.75 deshalb zuerst auf einer Testinstallation mit separat gesichertem Datenstand ausführen.

## Prüfung von Alpha.73/74

701 Backendtests, 21 JavaScript-Tests und 13 Browserfälle zur Sitzungswiederherstellung sind bestanden; der Produktionsbuild und die Shell-Syntaxprüfung sind erfolgreich. Geprüft wurden HTTP 5xx, Verbindungsfehler, eine hängende Sitzungsprüfung, begrenzte Wiederholungen, manuelle Prüfung, echte HTTP 401 und die Rückkehr nach einer Sicherung ohne doppelten Auftrag. Die neue Verbindungsanzeige wurde in Hell und Dunkel bei 320 Pixeln geprüft. Die bestehende Alpha.73-Browserprüfung umfasste 24 Wartungsfälle mit 14 vorgegebenen Themes und zwei eigenen Farbpaletten.

Automatisiert geprüft: echte Verschlüsselungs-/Archiv-Rundreisen, Manipulationen, portable Exporte, Dateiersetzung und Rollback mit simulierten Host-/Datenbankdiensten, Wiederanlauf zwischen Datenbankumbenennungen, gemeinsam genutzte Sperren, Adminrechte, HTTP-Upload-/Downloadabläufe und WebUI-Bedienung. Zusätzlich geprüft: automatische Einrichtung über den vorhandenen Alpha.72-Migrationsschritt, Beschränkung auf die verwaltete Root-Installation, wiederholte Einrichtung, geschützte laufende Wartungen, Reparatur unvollständiger Python-Umgebungen, Docker-Projekt-/Volume-Erkennung und sichtbare Einrichtungsfehler. Ein realer Proxmox-LXC, Dockerdaemon und PostgreSQL-Dienst stehen in der Entwicklungsumgebung nicht zur Verfügung. Diese Hostintegration muss deshalb zuerst auf einer Testinstallation mit separat gesichertem Datenstand erprobt werden; ein bestandener Mock-Test ist kein Live-Restore-Nachweis.
