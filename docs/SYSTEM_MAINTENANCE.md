# System & Wartung / System maintenance (Alpha.73)

Admin → **System & Wartung** bündelt **Updates**, **Sicherungen** und **Wiederherstellung**. Der kleine Versions-/Updatehinweis öffnet diesen Bereich. Normale Benutzer sehen eine reine Informationsseite unter Einstellungen → Updates; dort stehen Updateprüfung und Release Notes ohne Wartungsaktionen. Unter „Über PenguCoach“ bleibt ein Link dorthin. Die automatische GitHub-Prüfung bleibt sechs Stunden gecacht; „Jetzt prüfen“ ist im Updatebereich verfügbar.

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

## Updates

1. Unter Updates nach einer neuen Version suchen und die Release Notes öffnen.
2. „Update vorbereiten“ wählen und `UPDATE` bestätigen.
3. Der Dienst lädt den konfigurierten Quellbranch, hält die schreibenden Dienste an, erzeugt eine lokale Vollsicherung, baut die Anwendung, führt Migrationen aus und prüft API/Datenbank und Webserver.

Die Updatefunktion benötigt ein Git-Checkout als Installationsverzeichnis; bei einem direkt entpackten Quell-ZIP bleiben Backup/Restore nutzbar, die Updateaktion zeigt den fehlenden Git-Stand an.

Wie der bisherige Shell-Updater aktualisiert die Wartung den ausgewählten Git-Branch (standardmäßig `main`), nicht automatisch einen beliebigen Release-Download. Lokale Änderungen an versionierten Quelldateien werden ersetzt. Nicht versionierte `.env`- und Compose-Konfigurationsdateien werden beim Aufräumen geschützt. LXC-Frontend-Builds laufen bei gestopptem Webdienst mit begrenztem Node-Heap.

Fehler vor Abschluss lösen die Wiederherstellung von Quellstand/Images, Datenbank und Umgebung aus. Der Status bleibt außerhalb der App-Datenbank erhalten. Bei einer Verbindungsunterbrechung läuft der Auftrag weiter; die Seite prüft erneut. Bei einem erfolgreichen Restore werden Benutzer abgemeldet und müssen sich neu anmelden. Ein Auftrag darf während des eigentlichen Umbaus nicht per WebUI abgebrochen werden.

Neue WebUI-Updates und Backups warten auf aktive, bekannte Hintergrundaufträge. Eine zweite Wartungsaktion wird unabhängig vom verwendeten Zugang gesperrt. Die vorhandenen Shell-Kommandos bleiben für einen Administrator auch bei nicht erreichbarer WebUI nutzbar.

## Was eine Vollsicherung enthält

- PostgreSQL-Dump mit allen Benutzern, Einstellungen, LLM-Anbietern/-Modellen und deren verschlüsselten Zugangsdaten, benutzerspezifischen Prompts, Coach-Verläufen, Trainingsplänen und Analysen.
- Effektive App-Umgebung einschließlich `PENGUCOACH_ENCRYPTION_KEY`. Ohne diesen Schlüssel wären gesicherte API-Zugänge und andere verschlüsselte Inhalte auf einem neuen System nicht lesbar.
- Reguläre Dateien des App-Datenverzeichnisses, einschließlich gespeicherter Aktivitätsdateien, Telemetrie und Cache-Dateien.

Sicherungen sichern sich nicht rekursiv selbst. Redis-Warteschlangen und Celerybeat-Laufzeitdateien werden nicht wieder eingespielt; nach Restore werden alte Aufträge als beendet markiert und Warteschlangen verworfen. Gespeicherte Antworten und Fortsetzungs-Checkpoints bleiben erhalten. Die vollständigen Anwendungsdaten liegen in Datenbank und Datenverzeichnis. Docker-Images, Betriebssystem, externe Dienste, Reverse-Proxy-/TLS-Konfiguration und individuelle Host-/Compose-Dateien sind keine Bestandteile dieses App-Backups. Ziel-Datenbank, Redis, Datenpfad und die explizite Zieladresse bleiben beim Restore erhalten.

Unterstützt werden die von der Standardinstallation verwaltete lokale PostgreSQL-Datenbank `pengucoach` auf Port 5432 und Redis-Datenbank 0 auf Port 6379. Bei abweichender Infrastruktur stoppt die Aktion vor der Änderung. Backups benötigen zusätzlichen Plattenplatz für Dump, Dateikopie und verschlüsseltes Archiv; die Übertragung und Verschlüsselung arbeiten in begrenzten Blöcken.

## Passwortgeschützt oder lokal gesichert

**WebUI-Vollbackup:** mindestens 12 Zeichen, zweimal eingeben, danach die `.pcbackup`-Datei herunterladen. Das Passwort separat aufbewahren. Es wird weder im Auftragsprotokoll noch im Browserspeicher gespeichert. Ohne Passwort kann eine portable Sicherung nicht entschlüsselt werden.

**Automatische Sicherung vor Update/Restore** und `pengucoach-backup` ohne Zusatzparameter: mit dem privaten Schlüssel des Wartungsdiensts verschlüsselte lokale Sicherung. In der Liste als „Lokal gesichert“ markiert. Für einen anderen Host zuerst **„Mit Passwort exportieren“** wählen und den erzeugten portablen Export herunterladen. Nur die lokale Datei ohne deren privaten Dienstschlüssel reicht für einen neuen Host nicht aus.

Das Archiv verwendet AES-256-GCM in authentifizierten 1-MiB-Blöcken und PBKDF2-SHA256 mit zufälligem Salt. Ein authentifizierter Abschluss erkennt abgeschnittene Dateien. Vor einem Restore werden Dateiliste, Größen, Hashes und zulässige Pfade geprüft; Symlinks, Spezialdateien und Pfadtraversierungen werden abgelehnt. Uploads erfolgen in kleinen, bei verloren gegangener Antwort erneut prüfbaren Blöcken; die Obergrenze beträgt 100 GiB. Automatische Sicherungen bleiben bis zur expliziten Löschung erhalten.

## Auf einem neuen System wiederherstellen

1. Dieselbe oder eine kompatible neuere PenguCoach-Version installieren und das erste Administratorkonto anlegen. Der Wartungsdienst wird automatisch eingerichtet.
2. Unter Wiederherstellung die portable `.pcbackup` hochladen und das Backup-Passwort eingeben.
3. **„Sicherung prüfen“** starten. Erst nach erfolgreicher Prüfung wird die Wiederherstellung freigegeben.
4. „Wiederherstellung vorbereiten“ wählen und `WIEDERHERSTELLEN` bestätigen. Die Daten aller Benutzer werden ersetzt.
5. Der Dienst stellt den Dump zunächst in einer separaten Datenbank wieder her und prüft die Migrationen. Erst danach hält er die App an, sichert den aktuellen Stand und ersetzt Datenbank und Dateien.
6. Anschließend mit einem Benutzerkonto **aus der Sicherung** anmelden. Der Anmeldeschlüssel wird erneuert; Sitzungen von vor dem Restore gelten nicht weiter.

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

Bei Docker `docker logs <Helfername>` und die CLI im Helfer nutzen. `recover` verwendet dieselbe Sperre und läuft nicht parallel zu einem aktiven Auftrag. Die WebUI zeigt nur feste Fehlercodes und Ablaufmeldungen, keine Passwörter, rohen Datenbankausgaben oder Providerantworten.

## Prüfung dieser Version

699 Backendtests, 17 JavaScript-Tests und 24 Browserfälle sind bestanden; der Produktionsbuild und die Shell-Syntaxprüfung sind erfolgreich. Die Browserprüfung umfasst 14 vorgegebene Themes, zwei eigene Farbpaletten und Ansichten bis 320 Pixel.

Automatisiert geprüft: echte Verschlüsselungs-/Archiv-Rundreisen, Manipulationen, portable Exporte, Dateiersetzung und Rollback mit simulierten Host-/Datenbankdiensten, Wiederanlauf zwischen Datenbankumbenennungen, gemeinsam genutzte Sperren, Adminrechte, HTTP-Upload-/Downloadabläufe und WebUI-Bedienung. Zusätzlich geprüft: automatische Einrichtung über den vorhandenen Alpha.72-Migrationsschritt, Beschränkung auf die verwaltete Root-Installation, wiederholte Einrichtung, geschützte laufende Wartungen, Reparatur unvollständiger Python-Umgebungen, Docker-Projekt-/Volume-Erkennung und sichtbare Einrichtungsfehler. Ein realer Proxmox-LXC, Dockerdaemon und PostgreSQL-Dienst stehen in der Entwicklungsumgebung nicht zur Verfügung. Diese Hostintegration muss deshalb zuerst auf einer Testinstallation mit separat gesichertem Datenstand erprobt werden; ein bestandener Mock-Test ist kein Live-Restore-Nachweis.
