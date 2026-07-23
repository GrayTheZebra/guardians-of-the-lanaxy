# LANaxy 1.35.40

## Incident-Quittierungen zuverlässig speichern

- Quittierungen werden in einer expliziten SQLite-Schreibtransaktion gespeichert.
- Der betroffene Datensatz wird nach dem Commit über eine neue Verbindung erneut gelesen.
- Eine Erfolgsmeldung wird nur ausgegeben, wenn Zeitstempel, Benutzer und Notiz tatsächlich persistiert wurden.
- Fehler beim Speichern werden sichtbar gemeldet statt als erfolgreiche Quittierung behandelt.
- Quittierungen bleiben nach automatischer oder manueller Auflösung des Incidents erhalten.
