# Guardians of the LANaxy 1.24.0

## Guardian-Verwaltung
- Globale Suche auf der Guardian-Übersicht.
- Tags für Guardians und Tag-Filter.
- Vorlagen für Proxmox, Home Assistant, Zigbee2MQTT, NAS und Docker.
- Bestehendes Duplizieren bleibt erhalten und ist in den Karten verfügbar.
- Massenbearbeitung: aktivieren, deaktivieren, Gruppe setzen, Tags setzen und löschen.
- Gruppen und Tags bleiben vollständig kompatibel mit bestehenden Konfigurationen.

## Proxmox und Hardware
- Automatische Proxmox-Storage-Erkennung mit ID, Typ und Belegung.
- USB Guardian prüft optional Proxmox-Passthrough an QEMU-VM oder LXC.
- SMART Guardian speichert Temperatur-, Sektor- und NVMe-Verschleißwerte als begrenzten Verlauf und weist Änderungen im Prüfergebnis aus.
- Neuer ZFS-/RAID-Guardian für ZFS-Pools und Linux MD RAID.
- Neuer Updates-/Neustart-Guardian für APT, Pacman und DNF.
- Neuer Proxmox Backup Server Guardian mit optionaler Datastore-Belegung.
- Neue lokale und MiniGuard-Checks für RAID und Paketupdates.
