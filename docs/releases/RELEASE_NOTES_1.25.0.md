# Guardians of the LANaxy 1.25.0

## Proxmox-Assistent
- Vollständiger Scan über einen vorhandenen Proxmox API Guardian.
- Nodes, QEMU-VMs, LXC-Container und Storages gesammelt auswählen.
- Mehrere erkannte Objekte in einem Schritt als Guardians anlegen.
- Automatische Node-Abhängigkeiten für Gäste und Storages.
- Einheitliche Gruppen und Tags für die erzeugten Guardians.
- Optional Updates-/Neustart- sowie ZFS-/RAID-Guardian über einen MiniGuard ergänzen.

## Guardian-Verwaltung
- Statusfilter und Sortierung nach Name, Status, letzter Prüfung oder Antwortzeit.
- Filter werden lokal im Browser gespeichert.
- Massenaktionen um Testen und Duplizieren erweitert.
- Guardian-Export als JSON, wahlweise nur für markierte Guardians.
- JSON-Import mit automatischer Auflösung kollidierender IDs.
- Gruppen sind anklickbar und besitzen eine eigene Übersicht.
- Ganze Guardian-Gruppen können gemeinsam getestet werden.
- Mehrfachauswahl von Abhängigkeiten ohne gedrückte Strg-/Cmd-Taste.
