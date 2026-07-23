# Guardians of the LANaxy 1.17.0

## MiniGuard Foundation

- MiniGuard Manager unter **System → MiniGuards**
- serverseitig erzeugter, individueller cURL-Installationsbefehl
- einmalige Registrierungscodes mit einstellbarer Ablaufzeit
- Registrierung und Heartbeat nach MiniGuard-Protokoll v1
- gehashte Speicherung von Registrierungscode und dauerhaftem Agent-Token
- Anzeige von Onlinezustand, Hostname, Betriebssystem, Version und Capabilities
- klarer Deinstallationshinweis beim Löschen
- installierbarer Foundation-Agent mit systemd-Service
- Check-Source-Abstraktion und verbindliche Status-/Antworttypen als Grundlage für Remote-Guardians

Der Foundation-Agent führt noch keine Guardian-Prüfungen aus. Er stellt Registrierung,
Identität, Heartbeat und Capability-Aushandlung bereit. Die eigentliche Remote-Ausführung
bestehender Guardians folgt auf dieser stabilen Basis.
