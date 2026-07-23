# Guardians of the LANaxy 1.26.0

## Incident- und Abhängigkeitslogik
- Wiederkehrende Incidents desselben Guardians innerhalb von sieben Tagen werden erkannt.
- Incident-Kette mit Wiederholungszähler und Verweis auf den vorherigen Incident.
- Korrelationsschlüssel für Guardian, Gerät oder Host.
- Incident-Detail zeigt ähnliche frühere Incidents.
- Mögliche übergeordnete Ursachen werden aus der Abhängigkeitskette angezeigt.

## Hardware-Monitoring
- Neuer Hardware-Sensoren Guardian für lm-sensors und IPMI.
- Temperatur- und Lüftergrenzen.
- Neuer PCI-/Passthrough-Guardian für lspci und Proxmox-Konfigurationen.
- SMART-Verlauf als einfache Sparkline-Ansicht in den Guardian-Details.

## MiniGuard
- Agent-Version 1.4.0.
- Erweiterte Werkzeugerkennung für ZFS, Sensoren, IPMI, PCI und Paketmanager.
- Fähigkeiten für Hardware-Sensoren und PCI-Geräte.
- Veraltete Agent-Versionen werden markiert.
- Fehlende optionale Werkzeuge werden sichtbar.
- Diagnosebericht pro MiniGuard als JSON-Download.
