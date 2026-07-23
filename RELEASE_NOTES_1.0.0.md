# Release Notes 1.0.0

## Erster öffentlicher Release

- LANaxy wird mit der stabilen Versionsnummer `1.0.0` veröffentlicht.
- Der bisherige Footer-Slogan wurde durch „Dein Netzwerk. Bewacht.“ ersetzt.
- Die umfassende README dokumentiert Installation, Updates, Guardians, Rules, Beacons, Portale, MiniGuards, Diagnose, Sicherheit sowie Backup und Wiederherstellung.
- Bestehende Installationen und Datenstrukturen bleiben mit dem regulären Updatepfad kompatibel.
- Die Weboberfläche wird produktiv über Gunicorn als WSGI-Server betrieben; der Flask-Entwicklungsserver wird nicht mehr verwendet.


## Release-Härtung

- vollständige AGPL-3.0-Lizenz und Drittanbieterhinweise ergänzt
- deutliche Warnung bei deaktiviertem Zugriffsschutz mit direktem Einrichtungslink
- zentrale HTTP-Sicherheitsheader ergänzt
- Gunicorn übernimmt Host und Port aus der LANaxy-Konfiguration
- CI und Release-Workflow prüfen WSGI-Import und Gunicorn-Konfiguration
- Release-Archive werden auf Python-Cache-Artefakte geprüft
- Abhängigkeiten auf kompatible Hauptversionen begrenzt

## Öffentlicher Ein-Befehl-Installer

- sicherer Bootstrap-Installer für `https://lanaxy.de/install.sh`
- Prüfung des GitHub-Release-Archivs per SHA-256
- Schutz vor parallelen Installationen und unsicheren Archivpfaden
- bestehende Installationen werden vor dem Austausch des Programmcodes gesichert
- automatischer Rückfall auf den vorherigen Programmstand bei einem fehlgeschlagenen Deployment
- feste GitHub-Release-Assets für Programmarchiv, Prüfsummen und Installer
- nginx- und Apache-Beispiele sowie Deployment-Skript für `lanaxy.de`
