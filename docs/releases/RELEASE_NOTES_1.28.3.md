# Guardians of the LANaxy 1.28.3

- MiniGuard auf Version 1.6.1 angehoben, damit die ZFS-Korrektur tatsächlich als Agent-Update erkannt wird.
- In der MiniGuard-Verwaltung wurde die fälschlich noch auf 1.5.0 stehende Zielversion auf 1.6.1 korrigiert.
- ZFS-Auswertung erkennt erfolgreiche Ausgaben zuverlässig über `all pools are healthy` oder eine auf `is healthy` endende Meldung.
- Diagnosewerte `normalized_output` und `healthy_detected` ergänzen die technischen Details.
