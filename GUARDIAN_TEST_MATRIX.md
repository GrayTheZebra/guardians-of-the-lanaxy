# Guardian-Testmatrix

Für jeden neuen oder geänderten Guardian sind mindestens folgende Fälle zu prüfen:

| Fall | Erwartung |
|---|---|
| Gültiger Normalzustand | OK mit verständlicher Meldung und Details |
| Warning-Grenze | WARNING mit konkretem Grund |
| Critical-Grenze / Ziel nicht erreichbar | CRITICAL mit konkretem Grund |
| Timeout | CRITICAL, Timeout und Ziel in der Meldung |
| Ungültige Konfiguration | Validierungsfehler vor dem Speichern oder UNKNOWN/CRITICAL mit Feldbezug |
| Fehlende Berechtigung | CRITICAL mit Betriebssystemfehler in Details |
| Abhängigkeit fehlt | CRITICAL mit Name der fehlenden Bibliothek/Ressource |
| Manuelle Prüfung | Gleiche Meldung wie Übersicht, inklusive Antwortzeit und technischen Details |
| Recovery | Nach Behebung wieder OK und Incident-Recovery |

## MQTT Topic Guardian
Broker erreichbar; Authentifizierung falsch; Topic-Timeout; retained erlaubt/erforderlich/verboten; Exakt/Enthält/Regex/JSON/numerisch; Altersgrenze; TLS gültig/ungültig.

## USB Guardian
VID/PID vorhanden/fehlend; Seriennummer eindeutig/falsch; mehrere Treffer; serial-by-id vorhanden/fehlend; Gerätenode vorhanden/fehlend; Sichtbarkeit in LXC.

## Guardians 1.15.0

### Dateialter
- OK: aktuelle Datei vorhanden
- WARNING/CRITICAL: Altersgrenzen überschreiten
- CRITICAL: kein Treffer oder Mindestgröße unterschritten

### DNS
- OK: Auflösung und erwartete Adresse stimmen
- WARNING/CRITICAL: Antwortzeitgrenzen
- CRITICAL: NXDOMAIN oder unerwartete Adresse

### Systemlast
- OK: Werte unter Grenzwerten
- WARNING/CRITICAL: Load, RAM oder Swap oberhalb der Grenzen
- CRITICAL: Mindest-Uptime unterschritten oder /proc nicht lesbar

### NTP
- OK: geringe Abweichung und gültiges Stratum
- WARNING/CRITICAL: Offset oder Roundtrip überschritten
- CRITICAL: Timeout, ungültige Antwort oder Stratum 0/>15

### Home Assistant MQTT Discovery
- Discovery aktiviert: retained Config-Topics werden veröffentlicht
- Discovery deaktiviert: keine Config-Topics
- Prefix anpassbar; Standard `homeassistant`

## Guardians 1.16.0

### Docker Container
- Engine über Unix-Socket und HTTP erreichbar/nicht erreichbar
- Container vorhanden/fehlend; running/stopped
- Docker-Healthcheck healthy/unhealthy/starting
- Warning/Critical bei Neustartzähler
- Mindestlaufzeit nach Neustart
- Fehlende Berechtigung auf `/var/run/docker.sock`

### Proxmox API
- API-Token gültig/ungültig; TLS gültig/ungültig
- Node erreichbar und Mindest-Uptime
- LXC/QEMU running/stopped sowie fehlende VMID
- Storage aktiv/inaktiv
- Warning/Critical bei Storage-Belegung

## Guardians 1.20.0

### Home Assistant API
- API erreichbar; Token gültig/ungültig; TLS gültig/ungültig
- Entity vorhanden/fehlend; unavailable/unknown
- exakter Zustand und numerischer Wertebereich
- Warning/Critical bei altem Zustand oder langsamer Antwort

### SMB/NFS
- Mountpoint vorhanden/fehlend und tatsächlich als eigener Mount eingehängt
- erwarteter Dateisystemtyp korrekt/falsch
- Lese- und optionaler Schreibtest
- Warning/Critical bei langsamer Reaktion
- lokale Ausführung und MiniGuard-Ausführung

### Backup
- mindestens ein aktuelles Backup vorhanden
- Warning/Critical bei Alter
- Mindestgröße und Mindestanzahl im Aufbewahrungszeitraum
- temporäre/unvollständige Dateien werden ignoriert
- lokale Ausführung und MiniGuard-Ausführung
