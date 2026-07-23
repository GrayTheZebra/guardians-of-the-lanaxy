# LANaxy 1.18.1 – MiniGuard Queue Reliability

- Interprozess-Sperre für die gemeinsame MiniGuard-Registry
- verhindert verlorene Check-Aufträge bei parallelen Heartbeats und Webzugriffen
- Remote-Worker-Status wird getrennt vom Heartbeat erfasst
- verständlicher Hinweis bei altem oder nicht laufendem Agenten
- Mindestzeitfenster von 15 Sekunden für Remote-Checks
- MiniGuard Agent 1.1.1 mit schnellerem Queue-Polling
