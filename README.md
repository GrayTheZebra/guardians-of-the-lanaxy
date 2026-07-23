# Guardians of the LANaxy

**Guardians of the LANaxy**, kurz **LANaxy**, ist eine selbst gehostete Verwaltungs-, Überwachungs- und Diagnoseoberfläche für Homelabs, Proxmox-, Linux-, Netzwerk- und Smart-Home-Umgebungen.

LANaxy prüft Dienste und Systeme über **Guardians**, bewertet Statusänderungen über **Rules**, meldet Ereignisse über **Beacons** und lässt sich über geschützte **Portale** von außen steuern. **MiniGuards** ergänzen die zentrale Installation um lokale Prüfungen und Hardwareinventar auf weiteren Linux-Systemen.

> Aktuelle Version: **1.0.0**

## Inhalt

- [Funktionsprinzip](#funktionsprinzip)
- [Hauptfunktionen](#hauptfunktionen)
- [Voraussetzungen](#voraussetzungen)
- [Installation](#installation)
- [Erste Schritte](#erste-schritte)
- [Guardians](#guardians)
- [Rules](#rules)
- [Beacons](#beacons)
- [Abhängigkeiten und Meldewege](#abhängigkeiten-und-meldewege)
- [Portale](#portale)
- [MiniGuards](#miniguards)
- [Incidents, Wartung und Stummschaltung](#incidents-wartung-und-stummschaltung)
- [Proxmox- und PBS-Assistenten](#proxmox--und-pbs-assistenten)
- [Backups und Wiederherstellung](#backups-und-wiederherstellung)
- [Konfiguration und wichtige Pfade](#konfiguration-und-wichtige-pfade)
- [CLI](#cli)
- [Dienste und Logs](#dienste-und-logs)
- [Updates](#updates)
- [Sicherheit](#sicherheit)
- [Fehlerdiagnose](#fehlerdiagnose)
- [Architektur](#architektur)
- [Entwicklung und Prüfungen](#entwicklung-und-prüfungen)
- [Projektstruktur](#projektstruktur)

---

## Funktionsprinzip

LANaxy trennt Erkennung, Bewertung, Benachrichtigung und externe Steuerung bewusst voneinander:

```text
Guardian  ->  Rule  ->  Beacon
     ^                    
     |                    
MiniGuard              Benachrichtigung

Portal  ->  LANaxy-Steuerbefehl
```

### Guardian

Ein Guardian prüft einen technischen Zustand, beispielsweise:

- Ist eine Website erreichbar?
- Läuft ein systemd-Dienst?
- Ist ein Datenträger fast voll?
- Ist ein Proxmox-Gast aktiv?
- Ist ein Backup zu alt?
- Liefert ein MQTT-Topic noch Daten?

Das Ergebnis ist typischerweise `ok`, `warning`, `critical` oder ein nicht eindeutig prüfbarer Zustand.

### Rule

Eine Rule entscheidet, welche Guardian-Ergebnisse eine Meldung auslösen und welche Beacons angesprochen werden. Rules können unter anderem auf Guardians, Gruppen und Statusstufen begrenzt werden.

### Beacon

Ein Beacon versendet oder signalisiert eine Meldung, zum Beispiel per Telegram, E-Mail, Discord, MQTT oder Webhook.

### Portal

Ein Portal nimmt authentifizierte Steuerbefehle entgegen. Portale überwachen keine Systeme, sondern steuern LANaxy, beispielsweise um einen Guardian sofort auszuführen oder Wartung zu aktivieren.

### MiniGuard

Ein MiniGuard läuft auf einem weiteren Linux-System und meldet Inventar, Zustand und lokale Prüfergebnisse an die zentrale LANaxy-Instanz.

---

## Hauptfunktionen

- zentrale Weboberfläche auf Port `8090`
- Guardians für Netzwerk, Linux, Proxmox, PBS, Speicher, MQTT und Smart Home
- frei kombinierbare Rules und Beacons
- sichtbare Guardian-Rule-Beacon-Abhängigkeiten
- Bewertung, ob ein Guardian Fehler- und Recovery-Meldungen senden kann
- Incidents mit Verlauf, Bestätigung und Ursachenbezug
- Wartungsfenster, Rule-Pausen und Beacon-Stummschaltungen
- MiniGuards mit Registrierung, Diagnose, Inventar und Agenten-Update
- Proxmox- und Proxmox-Backup-Server-Assistenten
- Konfigurationshistorie
- vollständige Backups und Wiederherstellung
- Auditdaten für Steuerbefehle und MiniGuard-Aktionen
- geschützte HTTP-, MQTT-, Webhook-, CLI-, Telegram- und Discord-Portale
- systemd-Dienste mit gehärteten Service-Einstellungen
- sicherer Updatepfad mit Prüfungen, Backup und Rollback
- deutsch- und teilweise englischsprachige Oberfläche

---

## Voraussetzungen

Für die reguläre Installation:

- Debian oder Ubuntu
- Root-Zugriff
- Internetzugang während der Installation
- freie TCP-Portnummer `8090`
- Python 3 aus der Distribution
- systemd

Der Installer richtet unter anderem folgende Pakete ein:

- `python3-flask`
- `python3-yaml`
- `python3-paho-mqtt`
- `python3-requests`
- `sudo`
- `avahi-daemon`
- `iputils-ping`
- `netcat-openbsd`

Andere Distributionen können grundsätzlich funktionieren, werden vom Ein-Befehl-Installer derzeit jedoch nicht automatisch eingerichtet.

---

## Installation

### Empfohlene Ein-Befehl-Installation

```bash
curl -fsSL https://lanaxy.de/install.sh | sudo bash
```

Während einer Test- oder Entwicklungsphase kann der Bootstrap-Installer direkt aus GitHub geladen werden:

```bash
curl -sLf https://raw.githubusercontent.com/GrayTheZebra/guardians-of-the-lanaxy/main/bootstrap.sh | sudo bash -
```

Der Bootstrap-Installer:

1. erkennt Debian oder Ubuntu,
2. lädt das aktuelle stabile GitHub-Release,
3. lädt die veröffentlichte SHA-256-Prüfsumme,
4. verifiziert das Archiv,
5. erkennt eine vorhandene Installation,
6. startet entweder die Neuinstallation oder den sicheren Updatepfad.

Der öffentliche Installer wird auf `lanaxy.de` als statische Datei `/install.sh` ausgeliefert. Die dafür vorgesehenen Webserver-Beispiele und das Deployment-Skript liegen unter:

```text
deploy/lanaxy.de/
scripts/deploy-public-installer.sh
```

Ausführliche Hinweise zur Veröffentlichung stehen in `deploy/lanaxy.de/README.md`.

Nach der Installation ist die Oberfläche normalerweise erreichbar unter:

```text
http://SERVER-IP:8090
```

### Manuelle Installation aus Git

```bash
git clone https://github.com/GrayTheZebra/guardians-of-the-lanaxy.git \
  /opt/guardians-of-the-lanaxy

cd /opt/guardians-of-the-lanaxy
chmod +x install.sh
sudo ./install.sh
```

### Erste technische Prüfung

```bash
lanaxy doctor
systemctl status lanaxy.service lanaxy-web.service --no-pager
```

---

## Erste Schritte

Nach der Installation empfiehlt sich folgende Reihenfolge:

1. Weboberfläche öffnen.
2. Unter den Systemeinstellungen die Web-Authentifizierung aktivieren.
3. Zeitzone, Sprache und allgemeine Einstellungen prüfen.
4. Einen Beacon anlegen und testen.
5. Einen Guardian anlegen und manuell ausführen.
6. Eine Rule erstellen, die den Guardian mit dem Beacon verbindet.
7. In der Guardian-Detailansicht den vollständigen Meldeweg prüfen.
8. Ein vollständiges Backup erstellen.

Eine minimale funktionierende Kette sieht so aus:

```text
HTTP/HTTPS Guardian
  -> Rule für warning, critical und recovery
    -> Telegram- oder E-Mail-Beacon
```

---

## Guardians

Guardians bilden die eigentlichen Prüfungen. Jeder Guardian besitzt eine eindeutige ID, einen Namen, einen Typ und typabhängige Einstellungen.

### Verfügbare integrierte Guardian-Typen

Der aktuelle Stand enthält unter anderem:

| Bereich | Guardian |
|---|---|
| Netzwerk | HTTP/HTTPS, TCP-Port, DNS, NTP, Netzwerkfreigabe |
| Linux | systemd-Dienst, Systemlast, Paketupdates, Dateialter |
| Speicher | Storage, ZFS/RAID, Backup-Dateien |
| Container | Docker-Container |
| Proxmox | Proxmox API, Proxmox Backup Server |
| Smart Home | Home Assistant API, Zigbee2MQTT, MQTT-Topic, Thread |
| Hardware | USB, PCI-Geräte, Hardware-Sensoren |
| MiniGuard | MiniGuard Health, MiniGuard Inventory |
| Automatik | Smart Guardian und benutzerdefinierte Guardians |

Die genaue Feldauswahl hängt vom Guardian-Typ ab. Hilfetexte im Formular erklären bekannte Felder und erwartete Werte.

### Statusstufen

- **OK / Recovery:** Prüfung erfolgreich oder vorheriger Fehler behoben
- **Warning:** auffälliger Zustand, der noch nicht kritisch ist
- **Critical:** erheblicher Fehler oder Ausfall
- **Unknown / nicht prüfbar:** Ergebnis konnte nicht zuverlässig bestimmt werden

### Wiederholungen und Intervalle

Guardians können mit Intervall, Timeout und Wiederholungszahl konfiguriert werden. Die Wiederholungen verhindern, dass ein einzelner kurzfristiger Fehler sofort als stabiler Zustandswechsel gewertet wird.

### Abhängigkeiten zwischen Guardians

Guardians können von anderen Guardians abhängen. LANaxy kann dadurch Folgefehler einer gemeinsamen Ursache zuordnen und Incidents bündeln.

Beispiel:

```text
Internetverbindung
  -> DNS-Auflösung
    -> Website
```

Fällt bereits die Internetverbindung aus, kann LANaxy nachgelagerte Fehler als abhängige Auswirkungen darstellen.

### Direkter Test

Ein Guardian kann in der Übersicht oder Detailansicht sofort getestet werden. Der Test läuft über den LANaxy-Dienst und verwendet dieselbe Konfiguration wie die reguläre Prüfung.

---

## Rules

Rules verbinden Guardian-Ergebnisse mit Beacons.

Eine Rule kann typischerweise festlegen:

- Name und Aktivzustand
- betroffene Guardians
- betroffene Guardian-Gruppen
- relevante Statusstufen
- direkte Beacons
- Eskalationsstufen und Verzögerungen
- Pausen oder Laufzeiteinschränkungen

### Typische Rule

```text
Name: Produktionsausfälle
Guardians: Webserver, Datenbank, Reverse Proxy
Status: warning, critical, recovery
Beacons: Telegram, E-Mail
```

### Recovery/OK beachten

Eine Rule sollte normalerweise nicht nur `warning` oder `critical`, sondern auch `recovery` berücksichtigen. Sonst kann LANaxy zwar einen Fehler melden, aber keine Entwarnung senden.

### Rule pausieren

Rules können über die Oberfläche oder ein Portal pausiert und später fortgesetzt werden. Eine Pause entfernt die Rule nicht und verändert ihre dauerhafte Konfiguration nicht.

---

## Beacons

Beacons sind Ausgabekanäle für Meldungen.

### Integrierte Beacon-Typen

- Telegram
- Discord
- E-Mail
- MQTT
- Webhook
- GET-Webhook
- benutzerdefinierte Beacons

### Beacon-Zustände

LANaxy unterscheidet unter anderem:

- aktiv und erfolgreich getestet
- aktiv, aber noch nicht eindeutig getestet
- fehlerhaft
- deaktiviert
- vorübergehend stummgeschaltet
- nicht mehr vorhanden oder nicht ladbar

Ein fehlerhafter Beacon wird in Guardian-Abhängigkeiten rot dargestellt. Deaktivierte Beacons werden nicht als nutzbarer Meldeweg gewertet.

### Beacon testen

Jeder Beacon sollte nach dem Anlegen getestet werden. Der letzte bekannte Testfehler wird in den relevanten Ansichten angezeigt, ohne Zugangsdaten offenzulegen.

---

## Abhängigkeiten und Meldewege

Die Guardian-Detailansicht zeigt den vollständigen Benachrichtigungsweg:

```text
Guardian
  -> Rule 1
      -> Beacon A
      -> Beacon B
  -> Rule 2
      -> Beacon B
      -> Beacon C
```

Zusätzlich gibt es unter Guardians eine kompakte Gesamtübersicht aller Guardian-Rule-Beacon-Wege.

### Bewertung der Meldefähigkeit

LANaxy bewertet, ob ein Guardian über aktive Rules und nutzbare Beacons sinnvoll melden kann:

- **Grün:** `warning` oder `critical` sowie `recovery`/OK können gemeldet werden
- **Gelb:** nur Fehlerzustände oder nur Recovery/OK können gemeldet werden
- **Rot:** über keine aktive Rule ist eine Meldung mit einem nutzbaren Beacon möglich

Deaktivierte Rules sowie deaktivierte, stumme, fehlerhafte oder fehlende Beacons zählen nicht als nutzbarer Meldeweg.

---

## Portale

Portale steuern LANaxy von außen. Sie sind keine Monitoring-Quellen und ersetzen keinen Guardian.

### Verfügbare Portale

- HTTP API
- MQTT
- Webhook
- CLI
- Telegram Bot
- Discord Bot
- benutzerdefinierte Portale

Jedes Portal kann auf eine Auswahl erlaubter Runtime-Befehle begrenzt werden. Bei HTTP-basierten Portalen kann zusätzlich eine IP-Allowlist gesetzt werden.

### Verfügbare Steuerbefehle

| Befehl | Zweck |
|---|---|
| `run_guardian` | Guardian sofort ausführen |
| `get_status` | Status eines oder aller Guardians abrufen |
| `get_runtime` | Wartungen, Pausen und Stummschaltungen abrufen |
| `maintenance` | Guardian in Wartung setzen |
| `end_maintenance` | Wartung beenden |
| `mute` / `unmute` | globale Meldungen stummschalten oder freigeben |
| `test_beacon` | Beacon testen |
| `pause_rule` / `resume_rule` | Rule pausieren oder fortsetzen |
| `get_incidents` | Incidents abrufen |
| `acknowledge` / `unacknowledge` | Incident bestätigen oder Bestätigung aufheben |
| `mute_beacon` / `unmute_beacon` | einzelnen Beacon stummschalten oder freigeben |

Die Portalformulare zeigen die verfügbaren Befehle mit Beschreibung und benötigten Parametern als Checkboxen an.

### Beispiel: Guardian über ein Webhook-Portal sofort testen

Die konkrete URL und das Secret werden in der Portalansicht angezeigt. Das Grundprinzip lautet:

```bash
curl -X POST \
  -H 'Content-Type: application/json' \
  -d '{"command":"run_guardian","target":"GUARDIAN_ID"}' \
  'http://LANAXY-SERVER:8090/PORTAL-URL'
```

### Beispiel: Status abrufen

```json
{
  "command": "get_status",
  "target": "GUARDIAN_ID"
}
```

Ohne `target` kann der Status aller Guardians angefordert werden, sofern der Portaltyp und die Freigabe dies erlauben.

### Telegram- und Discord-Bot-Befehle

Chat-Portale unterstützen unter anderem:

```text
/run GUARDIAN_ID
/status [GUARDIAN_ID]
/runtime
/maintenance GUARDIAN_ID [MINUTEN]
/endmaintenance GUARDIAN_ID
/testbeacon BEACON_ID
/pauserule RULE_ID [MINUTEN]
/resumerule RULE_ID
/incidents [GUARDIAN_ID]
/help
```

### Portal-Sicherheit

- nur benötigte Befehle freigeben
- für jedes Portal eigene Zugangsdaten verwenden
- Secrets nach Möglichkeit nicht in gemeinsam lesbaren Skripten hinterlegen
- IP-Allowlist verwenden, wenn die Aufrufer feste Adressen besitzen
- Portale deaktivieren oder löschen, wenn sie nicht mehr benötigt werden
- Weboberfläche und Portale hinter HTTPS oder einem vertrauenswürdigen Reverse Proxy betreiben

---

## MiniGuards

MiniGuards sind schlanke Agenten für zusätzliche Linux-Systeme.

### Typische Einsatzzwecke

- Hardwareinventar erfassen
- lokale systemd-Dienste prüfen
- Datenträger und Sensoren erfassen
- USB-, PCI- und ZFS-Informationen melden
- Prüfungen ausführen, die vom zentralen LANaxy-System nicht erreichbar sind

### Installation

Beim Anlegen eines MiniGuards erzeugt LANaxy automatisch einen passenden, einmal verwendbaren Installationsbefehl. Er enthält:

- die tatsächliche LANaxy-Adresse
- die Agent-ID
- einen zeitlich begrenzten Registrierungscode

Der Befehl wird auf dem zu überwachenden Zielsystem ausgeführt.

### Sicherheit der Registrierung

- Registrierungscode und Agent-Token sind getrennt
- zentrale Tokens werden nicht im Klartext gespeichert
- Tokens werden nicht unnötig in Logs ausgegeben
- Agenten führen keine beliebigen, vom Server gelieferten Shell-Befehle aus

### Diagnose

Die MiniGuard-Ansicht zeigt unter anderem:

- Erreichbarkeit
- Agentenversion
- Service-Status
- letzte Verbindung
- Hostname und Betriebssystem
- IP-Adressen
- Inventar
- fehlende oder veraltete Abhängigkeiten
- Updatefähigkeit
- Auftrags- und Auditinformationen

Ein bereinigter Diagnosebericht kann heruntergeladen werden.

### Agent aktualisieren

LANaxy kann kompatible MiniGuard-Agenten aktualisieren. Vor einem Update wird die Kompatibilität zwischen LANaxy-Version, Agentenversion und Protokollversion ausgewertet.

### Löschen und Deinstallieren

Das Löschen des zentralen MiniGuard-Eintrags deinstalliert den Agenten auf dem Zielsystem nicht automatisch. LANaxy zeigt deshalb einen passenden Deinstallationsbefehl und erklärt, auf welchem System er auszuführen ist.

---

## Incidents, Wartung und Stummschaltung

### Incidents

Statuswechsel können als Incidents gespeichert und gruppiert werden. Die Incident-Ansicht enthält je nach Ereignis:

- betroffenen Guardian
- aktuellen Zustand
- Verlauf und Zeitstempel
- abhängige Auswirkungen
- Notizen
- Bestätigungsstatus
- Wiederherstellung

### Wartungsmodus

Ein Guardian im Wartungsmodus wird weiterhin verwaltet, löst aber entsprechend der Laufzeitlogik keine normalen Meldungen aus. Wartung kann zeitlich begrenzt und mit einem Grund versehen werden.

### Rule-Pause

Eine Rule kann unabhängig vom Guardian pausiert werden.

### Beacon-Stummschaltung

Ein einzelner Beacon kann vorübergehend stummgeschaltet werden, ohne ihn dauerhaft zu deaktivieren oder seine Konfiguration zu ändern.

### Globale Stummschaltung

Bei geplanten Arbeiten können Meldungen global und optional nur für bestimmte Stufen unterdrückt werden.

---

## Proxmox- und PBS-Assistenten

LANaxy enthält Assistenten für Proxmox VE und Proxmox Backup Server.

### Proxmox-Assistent

Der Assistent kann über einen vorhandenen Proxmox-API-Guardian unter anderem geeignete Objekte erkennen und Guardians daraus anlegen.

### PBS-Assistent

Der PBS-Assistent erkennt abhängig von den API-Rechten unter anderem:

- Datastores
- Backup-Gruppen
- Backup-Jobs
- Remotes
- Alter und Zustand von Sicherungen

### API-Fehler

Typische Fehler wie `401 Unauthorized`, fehlende Berechtigungen, TLS-Probleme oder Verbindungsfehler werden verständlich erklärt. Die Meldung enthält einen direkten Link zum Bearbeiten des betroffenen API-Guardians. Die technische Originalmeldung bleibt für die Diagnose einsehbar.

Für Proxmox und PBS sollten nach Möglichkeit API-Tokens mit den tatsächlich benötigten Lese- und Audit-Rechten verwendet werden.

---

## Backups und Wiederherstellung

Unter **System → Backups** können vollständige Sicherungen erstellt, heruntergeladen, hochgeladen und wiederhergestellt werden.

Ein vollständiges Backup berücksichtigt die für LANaxy relevanten Konfigurations- und Laufzeitdaten. Vor einer Wiederherstellung wird die aktuelle Konfiguration zusätzlich gesichert.

### Vor größeren Änderungen

Vor Updates, umfangreichen Imports oder strukturellen Änderungen empfiehlt sich ein manuelles vollständiges Backup.

### Automatische Update-Sicherung

`update.sh` sichert vor dem Austausch des Codes Konfiguration und Datenbank. Zusätzlich werden ältere Codeversionen für einen möglichen Rollback aufbewahrt.

---

## Konfiguration und wichtige Pfade

| Zweck | Pfad |
|---|---|
| Programmcode | `/opt/guardians-of-the-lanaxy` |
| Hauptkonfiguration | `/etc/lanaxy/config.yaml` |
| zusätzliche Guardian-Konfiguration | `/etc/lanaxy/guardians.d` |
| zusätzliche Beacon-Konfiguration | `/etc/lanaxy/beacons.d` |
| zusätzliche Portal-Konfiguration | `/etc/lanaxy/portals.d` |
| vollständige Backups | `/etc/lanaxy/backups` |
| Datenbank | `/var/lib/lanaxy/lanaxy.db` |
| Statusdatei | `/var/lib/lanaxy/state.json` |
| Control-Laufzeitstatus | `/var/lib/lanaxy/control-state.json` |
| Logs | `/var/log/lanaxy` |

### Grundkonfiguration

Die neutrale Vorlage liegt unter:

```text
examples/config.yaml
```

Wichtige Hauptbereiche:

```yaml
mqtt:
  enabled: false

web:
  host: 0.0.0.0
  port: 8090
  authentication:
    enabled: false

lanaxy:
  loop_interval: 2
  heartbeat_interval: 30
  retention_days: 90
  backup_keep_count: 20

checks: []

notifications:
  channels: []
  rules: []

control:
  enabled: false
  portals: []
```

Die Weboberfläche ist in der neutralen Vorlage zunächst ohne Anmeldung erreichbar. Vor einer Veröffentlichung ins Internet muss die Authentifizierung aktiviert und ein sicherer HTTPS-Zugang eingerichtet werden.

### Konfigurationshistorie

LANaxy protokolliert Änderungen an der Konfiguration und erlaubt die Wiederherstellung älterer Stände. Die Anzahl aufbewahrter Versionen wird über `config_history_keep` begrenzt.

---

## CLI

Das Kommando `lanaxy` wird bei der Installation nach `/usr/bin/lanaxy` und `/usr/local/bin/lanaxy` verlinkt.

### Version anzeigen

```bash
lanaxy version
```

### Installation prüfen

```bash
lanaxy doctor
```

### Geladene Guardians anzeigen

```bash
lanaxy list
```

### Alle Guardians einmal ausführen

```bash
lanaxy once
```

### LANaxy im Vordergrund starten

```bash
lanaxy run
```

Im normalen Betrieb übernimmt dies `lanaxy.service`.

### Lokalen Control-Befehl ausführen

```bash
lanaxy control '{"command":"get_status"}'
```

Beispiel für einen bestimmten Guardian:

```bash
lanaxy control \
  '{"command":"run_guardian","target":"GUARDIAN_ID"}'
```

Mit einer abweichenden Konfigurationsdatei:

```bash
lanaxy --config /pfad/config.yaml doctor
```

---

## Dienste und Logs

LANaxy verwendet zwei zentrale systemd-Dienste:

| Dienst | Aufgabe |
|---|---|
| `lanaxy.service` | Guardian-Ausführung, Rules, Zustände und Hintergrundlogik |
| `lanaxy-web.service` | Weboberfläche und HTTP-Endpunkte |

### Status anzeigen

```bash
systemctl status lanaxy.service lanaxy-web.service --no-pager
```

### Dienste neu starten

```bash
systemctl restart lanaxy.service lanaxy-web.service
```

### Journald-Logs

```bash
journalctl -u lanaxy.service -n 100 --no-pager
journalctl -u lanaxy-web.service -n 100 --no-pager
```

Live verfolgen:

```bash
journalctl -u lanaxy.service -u lanaxy-web.service -f
```

### Dateilog

Das reguläre Anwendungslog liegt standardmäßig unter:

```text
/var/log/lanaxy/lanaxy.log
```

---

## Updates

### Über den Bootstrap-Installer

Der Installationsbefehl kann erneut ausgeführt werden. Eine vorhandene Installation wird erkannt:

```bash
curl -fsSL https://lanaxy.de/install.sh | sudo bash
```

### Aus einem bereits aktualisierten Projektverzeichnis

```bash
cd /opt/guardians-of-the-lanaxy

chmod +x \
  lanaxy.py \
  bin/lanaxy \
  web/run.py \
  install.sh \
  update.sh \
  scripts/setup-lanlord.sh

./update.sh
```

`update.sh` führt unter anderem aus:

- Prüfung auf Root-Rechte
- Sicherung von Konfiguration und Datenbank
- Prüfung benötigter Dateien
- Python-Syntax- und Importprüfungen
- Datenbank-Smoke-Test
- Neustart der Dienste
- `lanaxy doctor`
- HTTP-Healthcheck
- automatischen Rollback bei einem fehlgeschlagenen Update

Benutzerkonfiguration und Laufzeitdaten liegen außerhalb des Projektverzeichnisses und werden bei einem normalen Codeupdate nicht überschrieben.

---

## Sicherheit

LANaxy verwaltet Zugangsdaten, API-Tokens und Steuerendpunkte. Vor einem produktiven oder öffentlich erreichbaren Betrieb sollten mindestens folgende Punkte umgesetzt werden:

1. Web-Authentifizierung aktivieren.
2. LANaxy nur im vertrauenswürdigen Netz oder hinter VPN betreiben.
3. Für externen Zugriff HTTPS über einen Reverse Proxy verwenden.
4. Für Proxmox und PBS eigene API-Tokens mit minimal benötigten Rechten einsetzen.
5. Für jedes Portal eigene Secrets verwenden.
6. Portalbefehle auf den benötigten Umfang begrenzen.
7. IP-Allowlisten einsetzen, wo möglich.
8. Konfigurations- und Backupverzeichnisse nicht über Webfreigaben veröffentlichen.
9. Diagnoseberichte vor dem Weitergeben prüfen.
10. Updates nur aus vertrauenswürdigen Releases installieren.

### systemd-Härtung

Die ausgelieferten Service-Dateien verwenden unter anderem:

- eigenen Benutzer `lanlord`
- `NoNewPrivileges=true`
- `ProtectSystem=strict`
- `ProtectHome=true`
- eingeschränkte schreibbare Pfade
- eingeschränkte Linux-Capabilities
- private temporäre Verzeichnisse

Einige Guardians benötigen für ICMP-Prüfungen `CAP_NET_RAW`; die Weboberfläche besitzt diese Capability nicht.

### Secrets und Logs

Tokens und Zugangsdaten dürfen nicht unnötig in Logs, Fehlermeldungen oder Screenshots veröffentlicht werden. LANaxy versucht technische Fehler verständlich darzustellen, ohne Geheimnisse offenzulegen.

---

## Fehlerdiagnose

### Allgemeine Diagnose

```bash
lanaxy doctor
```

### Weboberfläche nicht erreichbar

```bash
systemctl status lanaxy-web.service --no-pager
journalctl -u lanaxy-web.service -n 100 --no-pager
ss -lntp | grep 8090
```

### Guardians werden nicht ausgeführt

```bash
systemctl status lanaxy.service --no-pager
journalctl -u lanaxy.service -n 100 --no-pager
lanaxy list
```

### Konfiguration prüfen

```bash
python3 - <<'PY'
from config import load_config
config = load_config('/etc/lanaxy/config.yaml')
print('Konfiguration geladen:', bool(config))
PY
```

### Nach Änderungen neu starten

```bash
systemctl restart lanaxy.service lanaxy-web.service
```

### Proxmox oder PBS meldet 401/403

- API-Token-ID und Secret prüfen
- API-Adresse und Port prüfen
- benötigte Audit-/Leserechte ergänzen
- TLS-Einstellung bewusst wählen
- den direkten Bearbeitungslink in der Fehlermeldung verwenden

### Beacon bleibt fehlerhaft

- Beacon in der Beacon-Übersicht erneut testen
- Zieladresse, Token oder Chat-/Channel-ID prüfen
- Erreichbarkeit vom LANaxy-Server testen
- letzten technischen Fehler in der Beacon-Ansicht öffnen

### MiniGuard offline

- Deinstallations- oder Diagnosebefehl nicht auf dem LANaxy-Server, sondern auf dem MiniGuard-Zielsystem ausführen
- Agentendienst auf dem Zielsystem prüfen
- LANaxy-Adresse und Netzwerkzugriff prüfen
- Diagnosebericht aus der MiniGuard-Ansicht herunterladen

---

## Architektur

LANaxy ist eine Python-Anwendung mit serverseitiger Weboberfläche.

### Zentrale Komponenten

- **Flask:** Weboberfläche und Portalendpunkte
- **Gunicorn:** produktionsgeeigneter WSGI-Server für den Webdienst
- **Jinja2:** HTML-Templates
- **SQLite:** Ergebnisse, Incidents und Laufzeitdaten
- **PyYAML:** Konfiguration
- **paho-mqtt:** MQTT-Kommunikation
- **requests:** HTTP- und API-Aufrufe
- **systemd:** dauerhafter Betrieb und Diensthärtung

### Webserverbetrieb

Die Flask-Anwendung wird produktiv nicht über den eingebauten Entwicklungsserver gestartet. `lanaxy-web.service` verwendet Gunicorn mit der WSGI-Anwendung `web.run:app`.

LANaxy verwendet bewusst einen Gunicorn-Worker mit mehreren Threads. Die Portal-Listener für MQTT, Telegram und Discord laufen im Webprozess und dürfen nicht von mehreren Worker-Prozessen gleichzeitig gestartet werden. Die Thread-Konfiguration ermöglicht dennoch mehrere parallele HTTP-Anfragen.

Die zentrale Konfiguration befindet sich in:

```text
web/gunicorn.conf.py
```

Der Dienst kann wie gewohnt geprüft werden:

```bash
systemctl status lanaxy-web.service
journalctl -u lanaxy-web.service -n 100 --no-pager
```

### Datenfluss

```text
Guardian Manager
  -> Guardian ausführen
  -> Ergebnis normalisieren
  -> Zustand und Datenbank aktualisieren
  -> Incident synchronisieren
  -> passende Rules bestimmen
  -> Beacons ausführen
  -> Weboberfläche und Portale stellen Zustand bereit
```

### Erweiterbarkeit

Guardian-, Beacon- und Portaltypen sind modular aufgebaut. Benutzerdefinierte Erweiterungen können über die Oberfläche importiert und separat verwaltet werden. Eigene Erweiterungen sollten dieselben Basisklassen, Validierungsregeln und Sicherheitsgrenzen verwenden wie die integrierten Module.

---

## Entwicklung und Prüfungen

### Abhängigkeiten für eine Entwicklungsumgebung

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Python-Syntax prüfen

```bash
python3 -m compileall -q .
```

### Shell-Skripte prüfen

```bash
bash -n bootstrap.sh
bash -n install.sh
bash -n update.sh
bash -n scripts/setup-lanlord.sh
```

### Release-Prüfung

```bash
python3 release_validation.py
```

Zusätzlich enthält das Repository:

- `.github/workflows/ci.yml`
- `.github/workflows/release.yml`
- `GUARDIAN_TEST_MATRIX.md`
- `MINIGUARD_TEST_MATRIX.md`

### Grundsätze für Änderungen

- bestehende Funktionen nicht unbemerkt entfernen
- Konfigurations- und Datenbankkompatibilität erhalten
- neue Felder mit sinnvollen Standardwerten ergänzen
- Tokens und Secrets nicht loggen
- Shell-Eingaben nicht ungeprüft übernehmen
- sichtbare Änderungen mit konsistenten Hilfetexten versehen
- vor einem Release Neuinstallation und Updatepfad prüfen

---

## Projektstruktur

```text
guardians-of-the-lanaxy/
├── lanaxy.py                 # Hauptprozess und CLI
├── database.py               # SQLite-Datenmodell und Migrationen
├── guardian_manager.py       # Laden und Ausführen der Guardians
├── notification_manager.py   # Rules und Beacons
├── control.py                # Steuerbefehle und Laufzeitstatus
├── miniguard_manager.py      # zentrale MiniGuard-Verwaltung
├── miniguard_agent.py        # Agentenimplementierung
├── guardians/                # integrierte Guardian-Typen
├── beacons/                  # integrierte Beacon-Typen
├── portals/                  # integrierte Portaltypen
├── web/
│   ├── app.py                # Flask-Anwendung
│   ├── run.py                # WSGI-Einstiegspunkt
│   ├── gunicorn.conf.py      # produktive WSGI-Konfiguration
│   ├── templates/            # Jinja2-Templates
│   └── static/               # CSS, JavaScript und Assets
├── examples/config.yaml      # neutrale Konfigurationsvorlage
├── systemd/                  # systemd-Service-Dateien
├── scripts/                  # Installations- und Hilfsskripte
├── docs/                     # zusätzliche Dokumentation
├── install.sh                # Neuinstallation
├── update.sh                 # sicherer Updatepfad
├── bootstrap.sh              # GitHub-Release-Installer
└── release_validation.py     # Release- und Datenbankprüfung
```

---

## Projektlinks

- Projektseite: `https://lanaxy.de`
- GitHub: `https://github.com/GrayTheZebra/guardians-of-the-lanaxy`

Fehlerberichte sollten die LANaxy-Version, den betroffenen Bereich, die ausgeführte Aktion und einen bereinigten Diagnoseauszug enthalten. Zugangsdaten, Portal-Secrets und MiniGuard-Tokens dürfen nicht veröffentlicht werden.


## Lizenz

Guardians of the LANaxy wird unter der **GNU Affero General Public License
v3.0 oder später** veröffentlicht (`AGPL-3.0-or-later`). Der vollständige
Lizenztext liegt in [`LICENSE`](LICENSE). Drittanbieter-Komponenten und ihre
Lizenzen sind in [`THIRD_PARTY_LICENSES.md`](THIRD_PARTY_LICENSES.md) aufgeführt.
Die Weboberfläche verlinkt auf das öffentliche Quellcode-Repository.

## Zugriffsschutz beim ersten Start

LANaxy kann in einem isolierten, vollständig vertrauenswürdigen Netz ohne
Anmeldung betrieben werden. Solange die Authentifizierung deaktiviert ist,
zeigt die Oberfläche jedoch dauerhaft eine deutliche Warnung mit direktem Link
zu **System → Allgemein → Zugriffsschutz**. Für jeden darüber hinausgehenden
Zugriff sind Anmeldung und HTTPS einzurichten.
