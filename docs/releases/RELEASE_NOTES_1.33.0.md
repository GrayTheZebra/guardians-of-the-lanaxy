# Guardians of the LANaxy 1.33.0

Dieses Release konzentriert sich auf einen stabilen, alltagstauglichen Teststand.

## Update und Betrieb
- Zentraler Release-Vorabtest für Pflichtdateien, Python-Syntax, Imports und Konfiguration.
- HTTP-Healthcheck nach jedem Update.
- Erfolgreiche Programmversionen werden als Code-Rollback gesichert.
- Bei Start-, Doctor- oder Healthcheck-Fehlern wird automatisch die letzte erfolgreiche Programmversion wiederhergestellt.
- Es werden maximal drei Programm-Rollbacks aufbewahrt.

## Health und Readiness
- `/health` prüft Dienste und Datenbank.
- `/readiness` prüft zusätzlich Backup-Alter und MiniGuard-Kompatibilität.
- Dashboard und Systemseite zeigen eine kompakte Bereitschaftsanzeige.
- SQLite wird per `PRAGMA quick_check` geprüft.
- Ein Backup älter als 14 Tage erzeugt eine Bereitschaftswarnung.

## Beacons
- Fehlgeschlagene Zustellungen werden automatisch wiederholt.
- Standard: drei Versuche mit fünf Sekunden Abstand.
- Pro Beacon können `retry_attempts` und `retry_delay_seconds` gesetzt werden.
- Die bestehende Versandhistorie speichert das endgültige Ergebnis.

## Guardian-Import
- Import zeigt vor dem Speichern eine Vorschau.
- Nicht installierte Guardian-Typen werden übersprungen.
- ID-Konflikte werden sichtbar und automatisch aufgelöst.
- Erst nach Bestätigung wird die Konfiguration verändert.

## Vorhandene Funktionen
- Backup, Restore, Diagnosepaket, MiniGuard-Verwaltung, Proxmox/PBS-Assistenten und Incident-Verwaltung bleiben Bestandteil des Teststands.
