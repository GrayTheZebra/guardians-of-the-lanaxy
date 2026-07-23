# Guardians of the LANaxy 1.29.0

## MiniGuard Control Center
- Sichere Auftragswarteschlange für vordefinierte Verwaltungsaktionen.
- Direkte Agent-Aktualisierung mit SHA-256-Prüfung und automatischer Sicherung.
- Agent-Neustart, Rollback, Diagnose, Inventar- und Logabruf.
- Sichere Agent-Tokenrotation.
- Aktionsberechtigungen werden zentral verwaltet und an den Agent übertragen.
- Host-Neustart ist standardmäßig gesperrt und benötigt Freigabe sowie Texteingabe `RESTART`.
- Massenaktionen für Diagnose, Inventar, Update, Neustart, Aktivieren und Deaktivieren.
- Auftrags- und Ergebnisverlauf als Auditliste.
- Keine allgemeine Remote-Shell.

## Meldungen und Incidents
- Für registrierte MiniGuards wird automatisch ein MiniGuard Health Guardian erzeugt.
- Überwacht Offline-Status, Remote-Worker, Versionskompatibilität und wiederholte Kommunikationsfehler.
- MiniGuard-Probleme können dadurch normale Rules, Beacons und Incidents auslösen.

## MiniGuard 1.7.0
- Unterstützt Managementaktionen und lokale Berechtigungsprüfung.
- Sicheres Self-Update, Backup und Rollback.
- Agent-Protokollabruf über journalctl.
- Heartbeat alle 30 Sekunden mit Gesundheitsdaten.
