# LANaxy 1.20.0 – Home Assistant, Netzwerkfreigaben und Backups

## Neu

- Home Assistant API Guardian für API- und Entity-Zustände
- SMB/NFS Guardian für Mount-, Typ-, Lese-, Schreib- und Latenzprüfungen
- Backup Guardian für Alter, Größe, Anzahl und Aufbewahrungszeitraum
- SMB/NFS- und Backup-Prüfungen lokal oder über MiniGuard
- MiniGuard Agent 1.3.0 mit den Capabilities `network_share` und `backup`

## Kompatibilität

Bestehende Konfigurationen und MiniGuard-Registrierungen bleiben erhalten. Für Remote-Prüfungen der neuen Guardian-Typen muss der Agent aktualisiert werden.
