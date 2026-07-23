# LANaxy 1.18.0 – MiniGuard Remote Checks

- Remote-Ausführung für Systemd, Speicherplatz, USB, Docker, Systemlast und Dateialter.
- Bestehende Guardians können als Prüfquelle lokal oder einen registrierten MiniGuard verwenden.
- Sichere Pull-Queue: MiniGuard fragt Aufgaben ab; LANaxy muss den Agenten nicht direkt erreichen.
- Keine freie Shellausführung; nur fest definierte, validierte Checktypen.
- Capability-Erkennung und klare UNKNOWN-Meldungen bei Offline/Timeout.
- MiniGuard Agent 1.1.0.
